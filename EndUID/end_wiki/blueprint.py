"""蓝图搜索模块 — 从 Skland Wiki 获取蓝图数据."""
import io
import json
import time
from pathlib import Path
from typing import Union

import aiofiles
from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from ..end_config import EndConfig
from ..utils.render_utils import render_html, image_to_base64
from ..utils.path import WIKI_CACHE_PATH, WIKI_BP_RENDER_CACHE
from .skland_wiki import wiki_client

# ==================== 路径 ====================

BP_MAP_PATH = WIKI_CACHE_PATH / "blueprint_map.json"
BP_RENDER_CACHE = WIKI_BP_RENDER_CACHE
BP_MAP_REFRESH_SECONDS = 86400  # 1 day
BP_DETAIL_EXPIRE_SECONDS = 259200  # 3 days

TEXTURE_PATH = Path(__file__).parent.parent / "end_char" / "texture2d"
TEMPLATE_PATH = Path(__file__).parent.parent / "templates"
bp_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

# ==================== 蓝图索引 ====================

_bp_map: dict | None = None
_bp_map_time: float = 0


def _load_bp_map() -> dict | None:
    if not BP_MAP_PATH.exists():
        return None
    try:
        raw = BP_MAP_PATH.read_text(encoding="utf-8")
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"[EndBP] Failed to load blueprint map: {e}")
        return None


async def _save_bp_map(data: dict) -> None:
    try:
        BP_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(
            BP_MAP_PATH, "w", encoding="utf-8"
        ) as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"[EndBP] Failed to save blueprint map: {e}")


def _extract_bp_info(item: dict) -> dict:
    """Extract blueprint metadata from a wiki item."""
    doc = item.get("document", {})
    wcm = doc.get("widgetCommonMap", {})
    dm = doc.get("documentMap", {})
    brief = item.get("brief", {})

    info: dict[str, str] = {}
    preview_url = ""

    for wid, wdata in wcm.items():
        tdm = wdata.get("tabDataMap", {})
        if "default" not in tdm:
            continue
        content_id = tdm["default"].get("content", "")
        if not content_id or content_id not in dm:
            continue
        d = dm[content_id]
        for bid in d.get("blockIds", []):
            block = d.get("blockMap", {}).get(bid, {})
            if block.get("kind") == "text":
                texts = []
                for elem in block.get("text", {}).get(
                    "inlineElements", []
                ):
                    if elem.get("kind") == "text":
                        texts.append(elem["text"]["text"])
                t = "".join(texts)
                if "：" in t:
                    key, val = t.split("：", 1)
                    info[key.strip()] = val.strip()
            elif block.get("kind") == "image":
                url = block.get("image", {}).get("url", "")
                if url:
                    preview_url = url

    return {
        "name": item.get("name", ""),
        "cover": brief.get("cover", ""),
        "preview_url": preview_url,
        "size": info.get("蓝图尺寸", ""),
        "materials": info.get("蓝图原料", ""),
        "intermediates": info.get("蓝图中间产物", ""),
        "products": info.get("蓝图最终产物", ""),
        "unlock": info.get("完成", ""),
    }


async def _fetch_blueprints() -> dict[str, dict]:
    """Fetch all blueprints from catalog, then get detail for each."""
    # Step 1: Get all blueprint IDs from catalog (1 API call)
    catalog_items = await wiki_client.get_catalog_items(
        sub_type_names={"系统蓝图"}
    )
    bp_entries = catalog_items.get("系统蓝图", [])
    if not bp_entries:
        return {}

    logger.info(f"[EndBP] Catalog returned {len(bp_entries)} blueprints")

    # Step 2: Fetch detail for each to get materials/products
    items: dict[str, dict] = {}
    for entry in bp_entries:
        item_id = str(entry.get("itemId", ""))
        if not item_id:
            continue

        item = await wiki_client.get_item_info(int(item_id))
        if not item:
            continue

        bp_info = _extract_bp_info(item)
        items[item_id] = bp_info
        logger.debug(f"[EndBP] Loaded blueprint {item_id}: {bp_info['name']}")

    return items


async def _ensure_bp_map() -> dict:
    """Get or refresh the blueprint map."""
    global _bp_map, _bp_map_time

    if _bp_map and (time.time() - _bp_map_time) < BP_MAP_REFRESH_SECONDS:
        return _bp_map

    loaded = _load_bp_map()
    if loaded:
        ft = loaded.get("fetch_time", 0)
        if (time.time() - ft) < BP_MAP_REFRESH_SECONDS:
            _bp_map = loaded
            _bp_map_time = time.time()
            return _bp_map

    logger.info("[EndBP] Refreshing blueprint map...")
    try:
        items = await _fetch_blueprints()
        if items:
            data = {"items": items, "fetch_time": time.time()}
            await _save_bp_map(data)
            _bp_map = data
            _bp_map_time = time.time()
            logger.info(f"[EndBP] Blueprint map refreshed: {len(items)}")
            return _bp_map
    except Exception as e:
        logger.error(f"[EndBP] Failed to refresh blueprint map: {e}")

    if loaded:
        _bp_map = loaded
        _bp_map_time = time.time()
        return _bp_map

    return {}


# ==================== 搜索 ====================

def _split_items(text: str) -> list[str]:
    """Split '赤铜矿、清水' into ['赤铜矿', '清水']."""
    import re
    return [s.strip() for s in re.split(r"[、，,]", text) if s.strip()]


def search_blueprints(
    bp_map: dict, query: str, max_results: int = 5
) -> list[tuple[str, dict, str]]:
    """Search blueprints by query.

    Search priority: 最终产物 > 中间产物 > 原料 > 名称
    Returns list of (item_id, bp_info, match_reason).
    """
    items = bp_map.get("items", {})
    if not items:
        return []

    results_product: list[tuple[str, dict, str]] = []
    results_intermediate: list[tuple[str, dict, str]] = []
    results_material: list[tuple[str, dict, str]] = []
    results_name: list[tuple[str, dict, str]] = []

    seen_ids: set[str] = set()

    for item_id, info in items.items():
        products = info.get("products", "")
        intermediates = info.get("intermediates", "")
        materials = info.get("materials", "")
        name = info.get("name", "")

        # Match products
        if products and query in products:
            if item_id not in seen_ids:
                results_product.append(
                    (item_id, info, f"最终产物: {products}")
                )
                seen_ids.add(item_id)
            continue

        # Match intermediates
        if intermediates and query in intermediates:
            if item_id not in seen_ids:
                results_intermediate.append(
                    (item_id, info, f"中间产物: {intermediates}")
                )
                seen_ids.add(item_id)
            continue

        # Match materials
        if materials and query in materials:
            if item_id not in seen_ids:
                results_material.append(
                    (item_id, info, f"原料: {materials}")
                )
                seen_ids.add(item_id)
            continue

        # Match name
        if query in name:
            if item_id not in seen_ids:
                results_name.append(
                    (item_id, info, f"蓝图名: {name}")
                )
                seen_ids.add(item_id)

    combined = (
        results_product
        + results_intermediate
        + results_material
        + results_name
    )
    return combined[:max_results]


# ==================== 渲染 ====================


async def _render_blueprint_card(
    item_id: str, info: dict
) -> Union[bytes, str]:
    """Render a single blueprint card as image, with disk cache."""
    BP_RENDER_CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = BP_RENDER_CACHE / f"{item_id}.png"

    # Check render cache
    if cache_file.exists():
        try:
            cache_age = time.time() - cache_file.stat().st_mtime
            if cache_age < BP_DETAIL_EXPIRE_SECONDS:
                return cache_file.read_bytes()
        except Exception:
            pass

    bg = image_to_base64(TEXTURE_PATH / "bg.png", quality=75)
    end_logo = image_to_base64(TEXTURE_PATH / "end.png", quality=75)

    context = {
        "bp": info,
        "item_id": item_id,
        "bg": bg,
        "end_logo": end_logo,
    }

    img_bytes = await render_html(
        bp_templates, "end_wiki_blueprint.html", context
    )
    if not img_bytes:
        return "蓝图渲染失败"

    result = await convert_img(Image.open(io.BytesIO(img_bytes)))

    # Save to disk cache
    if isinstance(result, bytes):
        try:
            cache_file.write_bytes(result)
        except Exception as e:
            logger.warning(f"[EndBP] Failed to cache render: {e}")

    return result


# ==================== 指令入口 ====================


async def handle_blueprint_search(
    bot: Bot, ev: Event, query: str
):
    """Handle blueprint search command."""
    query = query.strip()
    if not query:
        return await bot.send("请输入要搜索的蓝图关键词")

    bp_map = await _ensure_bp_map()
    if not bp_map or not bp_map.get("items"):
        return await bot.send("蓝图数据加载失败，请稍后重试")

    max_results: int = EndConfig.get_config("BlueprintMaxResults").data
    results = search_blueprints(bp_map, query, max_results)

    if not results:
        # No match — stay silent to avoid echoing random input
        return

    if len(results) == 1:
        item_id, info, reason = results[0]
        card = await _render_blueprint_card(item_id, info)
        return await bot.send(card)

    if len(results) == 2:
        # 2 results — send directly
        for item_id, info, reason in results:
            card = await _render_blueprint_card(item_id, info)
            await bot.send(card)
        return

    # >2 results — send as forwarded message
    msgs: list = [f"找到 {len(results)} 个与「{query}」相关的蓝图："]
    for item_id, info, reason in results:
        card = await _render_blueprint_card(item_id, info)
        if isinstance(card, bytes):
            msgs.append(card)
        else:
            msgs.append(f"{info['name']} ({reason})")

    await bot.send(msgs)
