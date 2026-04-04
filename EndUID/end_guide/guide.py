"""攻略模块 — 从 Skland Wiki 获取角色攻略图片."""
import io
import json
import time
from typing import Optional, Union

import aiofiles
from PIL import Image

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from base64 import b64encode

from ..end_wiki.skland_wiki import wiki_client
from ..utils.image import pic_download_from_url
from ..utils.path import WIKI_CACHE_PATH, WIKI_GUIDE_CACHE

# ==================== 攻略 ID 映射 ====================

GUIDE_MAP_PATH = WIKI_CACHE_PATH / "guide_map.json"
GUIDE_CACHE_PATH = WIKI_GUIDE_CACHE
GUIDE_MAP_REFRESH_SECONDS = 86400  # 1 day
GUIDE_DETAIL_EXPIRE_SECONDS = 259200  # 3 days

GUIDE_WIKI_URL = (
    "https://wiki.skland.com/endfield/detail"
    "?mainTypeId=2&subTypeId=11&gameEntryId={item_id}"
)

_guide_map: dict | None = None
_guide_map_time: float = 0


def _load_guide_map() -> dict | None:
    if not GUIDE_MAP_PATH.exists():
        return None
    try:
        raw = GUIDE_MAP_PATH.read_text(encoding="utf-8")
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"[EndGuide] Failed to load guide map: {e}")
        return None


async def _save_guide_map(data: dict) -> None:
    try:
        GUIDE_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(
            GUIDE_MAP_PATH, "w", encoding="utf-8"
        ) as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"[EndGuide] Failed to save guide map: {e}")


def _extract_char_name(guide_name: str) -> str:
    """Extract character name from guide title like '【玩家攻略】洛茜'."""
    for prefix in ("【玩家攻略】", "【官方攻略】", "【攻略】"):
        if guide_name.startswith(prefix):
            return guide_name[len(prefix):]
    return guide_name


async def _ensure_guide_map() -> dict:
    """Get or refresh the guide name->ID mapping."""
    global _guide_map, _guide_map_time

    if _guide_map and (time.time() - _guide_map_time) < GUIDE_MAP_REFRESH_SECONDS:
        return _guide_map

    loaded = _load_guide_map()
    if loaded:
        ft = loaded.get("fetch_time", 0)
        if (time.time() - ft) < GUIDE_MAP_REFRESH_SECONDS:
            _guide_map = loaded
            _guide_map_time = time.time()
            return _guide_map

    # Scan guide items
    logger.info("[EndGuide] Refreshing guide ID map...")
    try:
        items = await _fetch_guide_items()
        if items:
            data = {"items": items, "fetch_time": time.time()}
            await _save_guide_map(data)
            _guide_map = data
            _guide_map_time = time.time()
            logger.info(f"[EndGuide] Guide map refreshed: {len(items)} guides")
            return _guide_map
    except Exception as e:
        logger.error(f"[EndGuide] Failed to refresh guide map: {e}")

    if loaded:
        _guide_map = loaded
        _guide_map_time = time.time()
        return _guide_map

    return {}


async def _fetch_guide_items() -> dict[str, dict]:
    """Fetch guide entries from catalog API (1 request)."""
    # typeMainId=2 for 攻略百科
    catalog_items = await wiki_client.get_catalog_items(
        sub_type_names={"干员攻略"}
    )
    guide_entries = catalog_items.get("干员攻略", [])
    if not guide_entries:
        # Try typeMainId=2 explicitly
        catalog = await wiki_client.get_catalog(type_main_id=2)
        for cat in catalog:
            for sub in cat.get("typeSub", []):
                if sub.get("name") == "干员攻略":
                    guide_entries = sub.get("items", [])
                    break

    items: dict[str, dict] = {}
    for entry in guide_entries:
        item_id = str(entry.get("itemId", ""))
        name = entry.get("name", "")
        char_name = _extract_char_name(name)

        items[item_id] = {
            "name": name,
            "char_name": char_name,
        }
        logger.debug(f"[EndGuide] Catalog guide {item_id}: {char_name}")

    return items


def _find_guide_id(guide_map: dict, char_name: str) -> int | None:
    """Look up a guide item ID by character name."""
    items = guide_map.get("items", {})
    for item_id_str, meta in items.items():
        if meta.get("char_name") == char_name:
            return int(item_id_str)
    return None


# ==================== 攻略内容提取 ====================


def _extract_guide_tabs(item: dict) -> list[dict]:
    """Extract guide tabs from wiki item.

    Returns list of {author, images: [url, ...]}
    """
    doc = item.get("document", {})
    document_map = doc.get("documentMap", {})
    widget_common_map = doc.get("widgetCommonMap", {})
    chapter_group = doc.get("chapterGroup", [])

    tabs: list[dict] = []

    for group in chapter_group:
        for widget_ref in group.get("widgets", []):
            wid = widget_ref["id"]
            widget = widget_common_map.get(wid, {})
            tab_list = widget.get("tabList", [])
            tab_data_map = widget.get("tabDataMap", {})

            for tab in tab_list:
                tab_id = tab.get("tabId", "")
                author = tab.get("title", "")
                tab_data = tab_data_map.get(tab_id, {})
                content_id = tab_data.get("content", "")

                images: list[str] = []
                if content_id and content_id in document_map:
                    content_doc = document_map[content_id]
                    for block_id in content_doc.get("blockIds", []):
                        block = content_doc.get("blockMap", {}).get(
                            block_id, {}
                        )
                        if block.get("kind") == "image":
                            url = block.get("image", {}).get("url", "")
                            if url:
                                images.append(url)

                if images:
                    tabs.append({"author": author, "images": images})

    return tabs


# ==================== 缓存管理 ====================


def _guide_cache_path(item_id: int):
    return GUIDE_CACHE_PATH / f"{item_id}.json"


def _is_guide_cache_expired(item_id: int) -> bool:
    cache_path = _guide_cache_path(item_id)
    if not cache_path.exists():
        return True
    try:
        raw = cache_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        ft = data.get("fetch_time", 0)
        return (time.time() - ft) > GUIDE_DETAIL_EXPIRE_SECONDS
    except Exception:
        return True


async def _get_guide_data(
    item_id: int,
) -> Optional[list[dict]]:
    """Get guide tabs with caching."""
    cache_path = _guide_cache_path(item_id)

    if not _is_guide_cache_expired(item_id):
        try:
            async with aiofiles.open(
                cache_path, "r", encoding="utf-8"
            ) as f:
                data = json.loads(await f.read())
            return data.get("tabs", [])
        except Exception as e:
            logger.warning(
                f"[EndGuide] Failed to load cache {item_id}: {e}"
            )

    # Fetch from API
    item = await wiki_client.get_item_info(item_id)
    if not item:
        return None

    tabs = _extract_guide_tabs(item)
    if not tabs:
        return None

    # Save cache
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {"tabs": tabs, "fetch_time": time.time()}
        async with aiofiles.open(
            cache_path, "w", encoding="utf-8"
        ) as f:
            await f.write(json.dumps(cache_data, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"[EndGuide] Failed to save cache {item_id}: {e}")

    return tabs


# ==================== 图片拼接 ====================

GUIDE_IMG_CACHE = WIKI_GUIDE_CACHE / "img"


async def _download_and_stitch(
    image_urls: list[str],
) -> Union[bytes, None]:
    """Download images and stitch them vertically into one."""
    GUIDE_IMG_CACHE.mkdir(parents=True, exist_ok=True)

    images: list[Image.Image] = []
    for url in image_urls:
        try:
            img = await pic_download_from_url(GUIDE_IMG_CACHE, url)
            images.append(img.convert("RGB"))
        except Exception as e:
            logger.warning(f"[EndGuide] Image download failed: {e}")

    if not images:
        return None

    if len(images) == 1:
        buf = io.BytesIO()
        images[0].save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    # Stitch vertically: uniform width, sum of heights
    max_width = max(img.width for img in images)
    total_height = 0
    for img in images:
        # Scale to max_width
        scale = max_width / img.width
        total_height += int(img.height * scale)

    canvas = Image.new("RGB", (max_width, total_height), (0, 0, 0))
    y = 0
    for img in images:
        if img.width != max_width:
            scale = max_width / img.width
            new_h = int(img.height * scale)
            img = img.resize((max_width, new_h), Image.LANCZOS)
        canvas.paste(img, (0, y))
        y += img.height

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


# ==================== 发送攻略 ====================


async def get_guide(
    bot: Bot,
    ev: Event,
    char_name: str,
    original_name: str = "",
):
    """Fetch and send character guide."""
    guide_map = await _ensure_guide_map()
    item_id = _find_guide_id(guide_map, char_name)

    # Also try original name if alias-resolved name didn't match
    if item_id is None and original_name and original_name != char_name:
        item_id = _find_guide_id(guide_map, original_name)

    if item_id is None:
        return

    tabs = await _get_guide_data(item_id)
    if not tabs:
        return

    wiki_url = GUIDE_WIKI_URL.format(item_id=item_id)

    # Build forwarded message: author+stitched_image pairs, then URL at end
    msgs: list = []
    for tab in tabs:
        author = tab.get("author", "未知")
        image_urls = tab.get("images", [])
        if not image_urls:
            continue

        msgs.append(f"攻略作者：{author}")

        stitched = await _download_and_stitch(image_urls)
        if stitched:
            msgs.append(f"base64://{b64encode(stitched).decode()}")
        else:
            # Fallback: send URLs directly
            for url in image_urls:
                msgs.append(url)

    msgs.append(f"来源：{wiki_url}")

    await bot.send(msgs)
