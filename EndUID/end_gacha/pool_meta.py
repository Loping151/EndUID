"""卡池元数据：解析森空岛百科「干员寻访速览 / 武器获取速览」，得到每期卡池的 UP 与常驻名单"""
import re
import json
import time
import asyncio
from typing import Optional

import aiofiles

from gsuid_core.logger import logger

from ..utils.path import MAIN_PATH
from ..end_wiki.skland_wiki import wiki_client

META_PATH = MAIN_PATH / "gacha_pool_meta.json"

OVERVIEW_CHAR = "干员寻访速览"
ARSENAL_QUOTA_ITEM = "武库配额"
OVERVIEW_WEAPON = "武器获取速览"

REFRESH_INTERVAL = 6 * 3600
MISS_RETRY_INTERVAL = 30 * 60
FETCH_TIMEOUT = 15

CHAR_SECTION_KIND = {"特许寻访": "special", "重构寻访": "rerun", "特殊寻访": "joint"}
WEAPON_SECTION_KIND = {"限时特卖": "weapon", "重构申领": "weapon_rerun", "常驻售卖": "weapon_constant"}

_NAME_RE = re.compile(r"「(.+?)」")

_meta: Optional[dict] = None
_last_attempt: float = 0
_lock = asyncio.Lock()
_bg_task: Optional[asyncio.Task] = None


def _empty_meta() -> dict:
    return {
        "fetch_time": 0,
        "pools": {},
        "standard_chars": [],
        "standard_weapons": [],
        "covers": {},
    }


def _cell_blocks(doc: dict, cell: dict) -> list[dict]:
    """单元格内每个文本块 -> {ids: [条目id], text: 纯文本(含链接文字)}"""
    out = []
    block_map = doc.get("blockMap", {})
    for child_id in cell.get("childIds", []):
        block = block_map.get(child_id, {})
        if block.get("kind") != "text":
            continue
        ids: list[str] = []
        parts: list[str] = []
        for el in block.get("text", {}).get("inlineElements", []):
            kind = el.get("kind")
            if kind == "entry":
                ids.append(str(el.get("entry", {}).get("id", "")))
            elif kind == "text":
                parts.append(el.get("text", {}).get("text", ""))
            elif kind == "link":
                parts.append(el.get("link", {}).get("text", ""))
        out.append({"ids": [i for i in ids if i], "text": "".join(parts)})
    return out


def _iter_tables(item: dict):
    """遍历速览条目里的所有表格，产出 (章节标题, 行[单元格[文本块]])"""
    document = item.get("document", {})
    widgets = document.get("widgetCommonMap", {})
    doc_map = document.get("documentMap", {})
    for chapter in document.get("chapterGroup", []):
        title = chapter.get("title", "")
        for widget in chapter.get("widgets", []):
            wc = widgets.get(widget.get("id", ""), {})
            tab_map = wc.get("tabDataMap", {})
            for tab in tab_map.values():
                doc = doc_map.get((tab or {}).get("content", ""))
                if not doc:
                    continue
                for block_id in doc.get("blockIds", []):
                    block = doc.get("blockMap", {}).get(block_id, {})
                    if block.get("kind") != "table":
                        continue
                    table = block.get("table", {})
                    cell_map = table.get("cellMap", {})
                    rows = [
                        [
                            _cell_blocks(doc, cell_map.get(f"{r}_{c}", {}))
                            for c in table.get("columnIds", [])
                        ]
                        for r in table.get("rowIds", [])
                    ]
                    yield title, rows


def _cell_text(cell: list[dict]) -> str:
    return " ".join(b["text"] for b in cell if b["text"]).strip()


def _pick_name(text: str, weapon: bool) -> str:
    for name in _NAME_RE.findall(text):
        if name.endswith("申领") == weapon:
            return name
    return ""


def _char_kind(section: str, text: str) -> str:
    if section in CHAR_SECTION_KIND:
        return CHAR_SECTION_KIND[section]
    for marker, kind in CHAR_SECTION_KIND.items():
        if marker in text:
            return kind
    return "special"


def _parse_char_overview(item: dict, id_name: dict, meta: dict):
    std: set[str] = set()
    for section, rows in _iter_tables(item):
        if not rows:
            continue
        header = [_cell_text(c) for c in rows[0]]
        if len(header) < 2 or header[0] != "寻访":
            continue
        if "6星" not in header[1]:
            # 基础与启程寻访：首块为全部 6 星
            for row in rows[1:]:
                if len(row) > 1 and row[1] and row[1][0]["ids"]:
                    std.update(id_name.get(i, "") for i in row[1][0]["ids"])
            continue
        for row in rows[1:]:
            if len(row) < 3 or not row[1] or not row[1][0]["ids"]:
                continue
            info = _cell_text(row[2])
            name = _pick_name(info, weapon=False)
            if not name:
                continue
            kind = _char_kind(section, info)
            first = [id_name.get(i, "") for i in row[1][0]["ids"]]
            first = [n for n in first if n]
            if not first:
                continue
            if kind != "joint" and len(row[1]) > 1:
                std.update(id_name.get(i, "") for i in row[1][1]["ids"])
            old = meta["pools"].get(name)
            if old and section not in CHAR_SECTION_KIND:
                continue
            meta["pools"][name] = {"kind": kind, "up": first if kind == "joint" else first[:1]}
    meta["standard_chars"] = sorted(n for n in std if n)


def _parse_weapon_overview(item: dict, id_name: dict, meta: dict):
    std: set[str] = set()
    for section, rows in _iter_tables(item):
        if not rows:
            continue
        header = [_cell_text(c) for c in rows[0]]
        if len(header) < 3 or header[0] != "武库申领":
            continue
        for row in rows[1:]:
            if len(row) < 3:
                continue
            if "概率提升" in header[1]:
                # 常驻售卖：申领名 | UP | 其它 6 星
                name = _cell_text(row[0])
                ups = [id_name.get(i, "") for b in row[1] for i in b["ids"]]
                others = [id_name.get(i, "") for b in row[2] for i in b["ids"]]
            else:
                info = _cell_text(row[2])
                name = _pick_name(info, weapon=True)
                ids = [i for b in row[1] for i in b["ids"]]
                ups = [id_name.get(i, "") for i in ids[:1]]
                others = [id_name.get(i, "") for i in ids[1:]]
            ups = [n for n in ups if n]
            if not name or not ups:
                continue
            std.update(n for n in others if n)
            meta["pools"][name] = {"kind": WEAPON_SECTION_KIND.get(section, "weapon"), "up": ups[:1]}
    meta["standard_weapons"] = sorted(std)


async def _fetch_meta() -> Optional[dict]:
    catalog = await wiki_client.get_catalog(1)
    id_name: dict[str, str] = {}
    covers: dict[str, str] = {}
    for cat in catalog:
        for sub in cat.get("typeSub", []):
            unit = sub.get("name") in ("干员", "武器")
            for it in sub.get("items", []):
                name = (it.get("name") or "").strip()
                if not name or not (unit or name == ARSENAL_QUOTA_ITEM):
                    continue
                if unit:
                    id_name[str(it.get("itemId"))] = name
                cover = (it.get("brief") or {}).get("cover") or ""
                if cover:
                    covers[name] = cover
    if not id_name:
        return None

    overview_ids: dict[str, int] = {}
    for cat in await wiki_client.get_catalog(2):
        for sub in cat.get("typeSub", []):
            for it in sub.get("items", []):
                if it.get("name") in (OVERVIEW_CHAR, OVERVIEW_WEAPON):
                    overview_ids[it["name"]] = int(it["itemId"])
    if len(overview_ids) < 2:
        logger.warning(f"[ENDUID·卡池] 百科速览条目缺失: {list(overview_ids)}")
        return None

    meta = _empty_meta()
    char_item = await wiki_client.get_item_info(overview_ids[OVERVIEW_CHAR])
    weapon_item = await wiki_client.get_item_info(overview_ids[OVERVIEW_WEAPON])
    if not char_item or not weapon_item:
        return None
    _parse_char_overview(char_item, id_name, meta)
    _parse_weapon_overview(weapon_item, id_name, meta)
    if not meta["pools"]:
        return None
    meta["covers"] = covers
    meta["fetch_time"] = time.time()
    return meta


async def _load_disk() -> Optional[dict]:
    if not META_PATH.exists():
        return None
    try:
        async with aiofiles.open(META_PATH, "r", encoding="utf-8") as f:
            return json.loads(await f.read())
    except Exception as e:
        logger.warning(f"[ENDUID·卡池] 读取卡池缓存失败: {e}")
        return None


async def _save_disk(meta: dict):
    try:
        async with aiofiles.open(META_PATH, "w", encoding="utf-8") as f:
            await f.write(json.dumps(meta, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"[ENDUID·卡池] 写入卡池缓存失败: {e}")


async def _refresh() -> None:
    global _meta, _last_attempt
    if _lock.locked():
        return
    async with _lock:
        _last_attempt = time.time()
        try:
            meta = await asyncio.wait_for(_fetch_meta(), FETCH_TIMEOUT)
        except Exception as e:
            logger.warning(f"[ENDUID·卡池] 拉取百科卡池失败: {e}")
            meta = None
        if meta:
            _meta = meta
            await _save_disk(meta)
            logger.info(f"[ENDUID·卡池] 百科卡池已更新: {len(meta['pools'])} 个")


async def get_pool_meta(pool_names: Optional[set] = None) -> dict:
    """返回卡池元数据；过期或缺少 pool_names 中的卡池时刷新，失败沿用旧缓存。"""
    global _meta, _bg_task
    if _meta is None:
        _meta = await _load_disk() or _empty_meta()

    now = time.time()
    stale = now - _meta.get("fetch_time", 0) > REFRESH_INTERVAL
    missing = bool(pool_names and set(pool_names) - set(_meta["pools"])) or ARSENAL_QUOTA_ITEM not in _meta["covers"]
    if (stale or missing) and now - _last_attempt > MISS_RETRY_INTERVAL:
        if _meta["pools"]:
            _bg_task = asyncio.create_task(_refresh())
        else:
            await _refresh()
    return _meta
