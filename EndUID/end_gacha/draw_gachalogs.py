"""抽卡记录渲染上下文构建"""
import io
import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Union

from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.database.models import EndBind
from ..utils.util import get_hide_uid_pref, hide_uid
from ..utils.api.model import CardDetailResponse
from ..utils.alias_map import get_avatar_by_name, get_portrait_by_name
from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..end_config import PREFIX
from ..utils.tips import TIP_NOT_BOUND
from ..utils.path import (
    AVATAR_CACHE_PATH,
    EQUIP_CACHE_PATH,
    PILE_CACHE_PATH,
    PLAYER_PATH,
    WIKI_IMG_CACHE,
)
from ..utils.player_store import read_player_json, player_json_exists
from .get_gachalogs import load_gachalogs
from .pool_meta import ARSENAL_QUOTA_ITEM, get_pool_meta
from .analysis import WEAPON_PREFIX, analyze, summarize


MODULE_PATH = Path(__file__).parent.parent
TEXTURE_PATH = MODULE_PATH / "end_char" / "texture2d"
GACHA_TEXTURE_PATH = Path(__file__).parent / "texture2d"
TEMPLATE_PATH = MODULE_PATH / "templates"

end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

ICON_SIZE = (128, 128)
MINOR_ICON_SIZE = (64, 64)
ART_SIZE = (264, 370)
CARD_WIDTH = 1200
# 卡片几何，需与 end_gacha_card.html 的尺寸一致；*_CAP 为跨 1..N 列时一行放得下的六星数，
# 武器接续段用缩小的头像排两行
CHAR_TILE_CAP = (7, 15)
WEAPON_TILE_CAP = (4, 9, 13, 18)
WEAPON_CONT_CAP = (5, 11, 17, 24)
CARD_INNER_W = (514, 1072)
TILE_STEP = 72
RUSH_LABEL_W = 104
RUSH_MAX_ROWS = 3


@lru_cache(maxsize=1)
def card_textures() -> dict:
    tex = {k: image_to_base64(GACHA_TEXTURE_PATH / f"{f}.webp") for k, f in (
        ("bg", "bg_tile"), ("belt", "belt_tile"), ("header", "header_bg"),
        ("plate6", "plate_6"), ("plate5", "plate_5"), ("plate4", "plate_4"),
    )}
    tex["logo"] = image_to_base64(MODULE_PATH / "end_daily" / "texture2d" / "logo.png")
    tex["up"] = image_to_base64(TEXTURE_PATH / "up_tag.png")
    return tex


async def _load_card_maps(uid: str, user_pref: str = "") -> tuple:
    """读取 card_detail.json 并构建头像映射
    返回 (name, level, avatar_b64, char_map, weapon_map, ok)
    """
    name = uid
    level = 0
    avatar_b64 = ""
    char_map: dict[str, str] = {}
    weapon_map: dict[str, str] = {}
    ok = False

    card_path = PLAYER_PATH / uid / "card_detail.json"

    try:
        card_res = await read_player_json(card_path)
        if card_res is None:
            return name, level, avatar_b64, char_map, weapon_map, ok
        if card_res.get("code") == 0:
            detail = CardDetailResponse.model_validate(card_res).data.detail
            base = detail.base
            if base:
                name = base.name or hide_uid(uid, user_pref=user_pref)
                level = base.level
                if base.avatarUrl:
                    avatar_b64 = await get_image_b64_with_cache(
                        base.avatarUrl, AVATAR_CACHE_PATH
                    )

            for char in detail.chars:
                cd = char.charData
                if cd and cd.name and cd.avatarSqUrl:
                    char_map[cd.name] = cd.avatarSqUrl

                wd = char.weapon.weaponData if char.weapon else None
                if wd and wd.name and wd.iconUrl:
                    weapon_map[wd.name] = wd.iconUrl

            ok = True
    except Exception as e:
        logger.warning(f"[ENDUID·抽卡] 读取卡片详情失败: {e}")

    return name, level, avatar_b64, char_map, weapon_map, ok


def _collect_gacha_char_names(pool_data: dict) -> set:
    """收集抽卡记录中所有六星角色名"""
    names: set = set()
    for pn, records in pool_data.items():
        if pn.startswith(WEAPON_PREFIX):
            continue
        for r in records:
            if r.get("rarity") == 6:
                cn = r.get("charName")
                if cn:
                    names.add(cn)
    return names


def _pool_names(pool_data: dict) -> set:
    names: set = set()
    for key, recs in pool_data.items():
        if key.startswith(WEAPON_PREFIX):
            names.add(key[len(WEAPON_PREFIX):])
        elif key not in ("基础寻访", "启程寻访"):
            names.update(r.get("poolName") for r in recs if r.get("poolName"))
    return names


def _major_names(groups: list) -> dict:
    """6 星与各期 UP -> 类型"""
    wanted: dict[str, str] = {}
    for g in groups:
        kind = "weapon" if g["type"] == "weapon" else "char"
        for b in g["banners"]:
            for n in b["featured"]:
                wanted[n] = kind
            for s in b["six"]:
                wanted[s["name"]] = kind
    return wanted


def _minor_names(groups: list, rush_only: bool = False) -> dict:
    """加急十连与各金期间的 5/4 星 -> 类型"""
    wanted: dict[str, str] = {}
    for g in groups:
        for b in g["banners"]:
            for fb in b.get("free_batches", []):
                wanted.update((it["name"], "char") for it in fb["items"] if it["rarity"] < 6)
            if rush_only:
                continue
            for s in b["six"]:
                for it in s.get("five_items", []) + s.get("four_items", []):
                    wanted[it["name"]] = "char"
    return wanted


async def _resolve_icons(
    wanted: dict, char_map: dict, weapon_map: dict, covers: dict, size: tuple
) -> dict:
    """图标：自己的卡片 → 别名表 → 百科封面"""
    async def one(name: str, kind: str) -> tuple[str, str]:
        if kind == "weapon":
            urls = [
                weapon_map.get(name),
                covers.get(name),
                f"https://imgheybox.max-c.com/endfield/icon/{name.rstrip('.')}.png",
            ]
            cache = EQUIP_CACHE_PATH
        else:
            urls = [char_map.get(name), get_avatar_by_name(name), covers.get(name)]
            cache = AVATAR_CACHE_PATH
        for url in urls:
            if not url:
                continue
            b64 = await get_image_b64_with_cache(
                url, cache, quality=85, cover_size=size
            )
            if b64:
                return name, b64
        return name, ""

    pairs = await asyncio.gather(*(one(n, k) for n, k in wanted.items()))
    return {n: b64 for n, b64 in pairs if b64}


async def _resolve_arts(groups: list) -> dict:
    """角色池各期 UP 的半身像，与角色面板共用 pile 缓存"""
    names = {n for g in groups if g["type"] == "char" for b in g["banners"] for n in b["featured"]}

    async def one(name: str) -> tuple[str, str]:
        url = get_portrait_by_name(name)
        if not url:
            return name, ""
        return name, await get_image_b64_with_cache(url, PILE_CACHE_PATH, quality=80, cover_size=ART_SIZE)

    pairs = await asyncio.gather(*(one(n) for n in names))
    return {n: b64 for n, b64 in pairs if b64}


async def build_gacha_payload(
    uid: str, ev: Event, user_pref: str = "", with_trays: bool = False
) -> tuple[Union[dict, None], Union[str, None]]:
    """加载抽卡记录并分析（图片与网页共用）。返回 (payload, err)。"""
    gacha_data = await load_gachalogs(uid)
    if not gacha_data:
        return None, f"未找到抽卡记录，请先使用「{PREFIX}导入抽卡记录」导入"

    pool_data = gacha_data.get("data", {})
    if not pool_data:
        return None, "抽卡记录为空"

    card_path = PLAYER_PATH / uid / "card_detail.json"

    # card_detail.json 不存在时先刷新一次
    if not player_json_exists(card_path):
        try:
            from ..end_char import refresh_card_data
            await refresh_card_data(ev.user_id, ev.bot_id, do_upload=True)
        except Exception as e:
            logger.debug(f"[ENDUID·抽卡] 自动刷新失败: {e}")

    (
        name, level, avatar_b64,
        char_avatar_map, weapon_icon_map, _ok,
    ) = await _load_card_maps(uid, user_pref)

    # 若抽卡记录中存在 card_detail 里没有的六星角色，触发一次刷新并重新加载
    missing_chars = _collect_gacha_char_names(pool_data) - set(char_avatar_map.keys())
    if missing_chars:
        logger.info(
            f"[ENDUID·抽卡] 六星角色头像缺失 {missing_chars}，触发刷新"
        )
        try:
            from ..end_char import refresh_card_data
            ok_refresh, _err = await refresh_card_data(ev.user_id, ev.bot_id, do_upload=True)
            if ok_refresh:
                (
                    name, level, avatar_b64,
                    char_avatar_map, weapon_icon_map, _ok,
                ) = await _load_card_maps(uid, user_pref)
        except Exception as e:
            logger.debug(f"[ENDUID·抽卡] 刷新头像失败: {e}")

    meta = await get_pool_meta(_pool_names(pool_data))
    groups = analyze(pool_data, meta)
    covers = meta.get("covers", {})
    maps = (char_avatar_map, weapon_icon_map, covers)
    icons = await _resolve_icons(_major_names(groups), *maps, ICON_SIZE)
    icons_minor = await _resolve_icons(_minor_names(groups, rush_only=not with_trays), *maps, MINOR_ICON_SIZE)
    quota_url = covers.get(ARSENAL_QUOTA_ITEM)
    quota_icon = await get_image_b64_with_cache(quota_url, WIKI_IMG_CACHE, quality=85, cover_size=MINOR_ICON_SIZE) if quota_url else ""

    return {
        "name": name,
        "level": level,
        "avatar": avatar_b64,
        "groups": groups,
        "summary": summarize(groups),
        "icons": icons,
        "icons_minor": icons_minor,
        "arts": await _resolve_arts(groups),
        "quota_icon": quota_icon,
        "data_time": gacha_data.get("data_time", ""),
    }, None


def _rush_cols(items: list, room: int) -> int:
    """加急结果在 room 宽内最少排几行，返回列数；排满 RUSH_MAX_ROWS 行仍放不下返回 0"""
    sizes = sorted((28 if it["rarity"] == 6 else 24 for it in items), reverse=True)
    for rows in range(1, RUSH_MAX_ROWS + 1):
        cols = -(-len(sizes) // rows)
        if 16 + max(RUSH_LABEL_W, sum(sizes[:cols]) + 3 * (cols - 1)) <= room:
            return cols
    return 0


def _flow(cards: list, caps: tuple, cont_caps: tuple) -> list:
    """按顺序排进 len(caps) 列的网格；放不下时先用本行剩余列排一行，余下的六星换行接续，
    接续段没有标题，按两行排以对齐同行卡片。返回各行的段。"""
    cols = len(caps)
    rows: list[list[dict]] = [[]]
    used = 0
    for card in cards:
        tiles, head = card["tiles"], True
        while True:
            if used == cols:
                rows.append([])
                used = 0
            free = cols - used
            per, lim = (1, caps) if head else (2, cont_caps)
            need = next((k for k, cap in enumerate(lim, 1) if len(tiles) <= cap * per), cols)
            lines = max(1, -(-len(tiles) // lim[need - 1]))
            if need <= free or len(tiles) <= lim[free - 1] * lines:
                span = min(need, free)
                rows[-1].append({**card, "tiles": tiles, "span": span, "head": head, "tail": True})
                used += span
                break
            cut = caps[free - 1]
            rows[-1].append({**card, "tiles": tiles[:cut], "span": free, "head": head, "tail": False})
            used = cols
            tiles, head = tiles[cut:], False
    return [row for row in rows if row]


def _char_cards(g: dict) -> dict:
    """角色池卡片的两列排布：返回按行展开的卡片与合并成一行的其余卡池。"""
    cards, rest = [], []
    for i, b in enumerate(g["banners"]):
        if i and not b["six"] and not b["free_batches"]:
            rest.append(b)
            continue
        tiles = [s for s in b["six"] if not s["free"]]
        span = 2 if len(tiles) > CHAR_TILE_CAP[0] else 1
        cards.append({"b": b, "tiles": tiles, "span": span, "first": i == 0})

    rows: list[list[dict]] = []
    open_row = None
    for c in cards:
        if c["span"] == 2:
            rows.append([c])
        elif open_row is not None:
            open_row.append(c)
            open_row = None
        else:
            open_row = [c]
            rows.append(open_row)
    for row in rows:
        if len(row) == 1 and len(row[0]["b"]["free_batches"]) > 1:
            row[0]["span"] = 2
        inner = CARD_INNER_W[row[0]["span"] - 1]
        for c in row:
            fbs, tiles = c["b"]["free_batches"], len(c["tiles"]) * TILE_STEP - 8
            fits = len(fbs) == 1 and 0 < tiles <= inner
            c["rush_cols"] = _rush_cols(fbs[0]["items"], inner - tiles - 8) if fits else 0
        inline = all(c["rush_cols"] for c in row if c["b"]["free_batches"] and c["tiles"])
        for c in row:
            fbs = c["b"]["free_batches"]
            c["inline"] = inline and c["rush_cols"] > 0
            if not c["inline"]:
                c["rush_cols"] = len(fbs[0]["items"]) if c["span"] == 2 and len(fbs) > 1 else 0
    return {"cards": [c for row in rows for c in row], "rest": rest}


def _weapon_cards(g: dict) -> dict:
    """武器池卡片排布：只列出过六星的池（当期限定池始终保留），其余合并成一行。"""
    cards, rest = [], []
    for i, b in enumerate(g["banners"]):
        first = i == 0 and g["key"] == "weapon"
        if b["six"] or first:
            cards.append({"b": b, "tiles": b["six"], "first": first})
        else:
            rest.append(b)
    return {"cards": [c for row in _flow(cards, WEAPON_TILE_CAP, WEAPON_CONT_CAP) for c in row], "rest": rest}


async def draw_gacha_card(ev: Event) -> Union[bytes, str]:
    """绘制抽卡记录卡片"""
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return TIP_NOT_BOUND
    user_pref = await get_hide_uid_pref(uid, ev.user_id, ev.bot_id)

    payload, err = await build_gacha_payload(uid, ev, user_pref)
    if err or payload is None:
        return err or "抽卡记录为空"

    icons = {**payload["icons_minor"], **payload["icons"]}
    context = {
        "name": payload["name"],
        "uid": hide_uid(uid, user_pref=user_pref),
        "avatar": payload["avatar"],
        "level": payload["level"],
        "groups": payload["groups"],
        "char_cards": {
            g["key"]: _char_cards(g) for g in payload["groups"] if g["key"] in ("special", "rerun", "joint")
        },
        "weapon_cards": {g["key"]: _weapon_cards(g) for g in payload["groups"] if g["type"] == "weapon"},
        "summary": payload["summary"],
        "icons": icons,
        "icon_cls": {n: f"i{i}" for i, n in enumerate(icons)},
        "arts": payload["arts"],
        "art_cls": {n: f"a{i}" for i, n in enumerate(payload["arts"])},
        "quota_icon": payload["quota_icon"],
        "card_width": CARD_WIDTH,
        "tex": card_textures(),
        "data_time": payload.get("data_time", ""),
        "end_logo": image_to_base64(TEXTURE_PATH / "end.png", quality=75),
    }

    img_bytes = await render_html(end_templates, "end_gacha_card.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))

    return "HTML 渲染失败"


async def draw_gacha_help() -> Union[bytes, str]:
    """绘制抽卡帮助页"""
    context = {
        "prefix": PREFIX,
        "bg": image_to_base64(TEXTURE_PATH / "bg.png", quality=75),
        "end_logo": image_to_base64(TEXTURE_PATH / "end.png", quality=75),
    }

    img_bytes = await render_html(end_templates, "end_gacha_help.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))

    return "HTML 渲染失败"
