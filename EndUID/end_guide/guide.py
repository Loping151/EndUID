"""攻略模块 — 从 Skland Wiki 获取角色攻略图文."""
import html as html_lib
import io
import json
import time
from pathlib import Path
from typing import Optional, Union

import aiofiles
from PIL import Image
from base64 import b64encode
from jinja2 import Environment, FileSystemLoader

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

from ..end_config import EndConfig
from ..end_wiki.skland_wiki import wiki_client
from ..utils.image import pic_download_from_url
from ..utils.path import TEMP_PATH, WIKI_CACHE_PATH, WIKI_GUIDE_CACHE
from ..utils.render_utils import render_html

# ==================== 攻略 ID 映射 ====================

GUIDE_MAP_PATH = WIKI_CACHE_PATH / "guide_map.json"
GUIDE_CACHE_PATH = WIKI_GUIDE_CACHE
GUIDE_MAP_REFRESH_SECONDS = 86400  # 1 day — normal refresh interval
GUIDE_MAP_RETRY_BACKOFF = 300  # 5 min — min gap between refresh attempts
GUIDE_DETAIL_EXPIRE_SECONDS = 259200  # 3 days

# Tabs with at least this much running text are rendered as a single image
# (text + images + tables) instead of stitching only images.
RICH_RENDER_TEXT_THRESHOLD = 100

# Bumped to invalidate caches missing the structured-block schema.
GUIDE_CACHE_SCHEMA = 2

GUIDE_WIKI_URL = (
    "https://wiki.skland.com/endfield/detail"
    "?mainTypeId=2&subTypeId=11&gameEntryId={item_id}"
)
JPG_MAX_DIMENSION = 65535

_guide_map: dict | None = None
_guide_map_last_attempt: float = 0

# Jinja env for the rich-render template
_GUIDE_TEMPLATE_DIR = TEMP_PATH
_guide_templates = Environment(
    loader=FileSystemLoader(str(_GUIDE_TEMPLATE_DIR)),
    autoescape=False,
)


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


async def _try_refresh_guide_map() -> bool:
    """Attempt a guide catalog refresh, honoring retry backoff."""
    global _guide_map, _guide_map_last_attempt
    now = time.time()
    if (now - _guide_map_last_attempt) < GUIDE_MAP_RETRY_BACKOFF:
        return False
    _guide_map_last_attempt = now
    logger.info("[EndGuide] Refreshing guide ID map...")
    try:
        items = await _fetch_guide_items()
        if not items:
            return False
        data = {"items": items, "fetch_time": time.time()}
        await _save_guide_map(data)
        _guide_map = data
        logger.info(f"[EndGuide] Guide map refreshed: {len(items)} guides")
        return True
    except Exception as e:
        logger.error(f"[EndGuide] Failed to refresh guide map: {e}")
        return False


async def _ensure_guide_map() -> dict:
    """Return the guide name->ID catalog, refreshing if stale."""
    global _guide_map

    if _guide_map is None:
        _guide_map = _load_guide_map()

    fetch_time = (_guide_map or {}).get("fetch_time", 0)
    if (time.time() - fetch_time) >= GUIDE_MAP_REFRESH_SECONDS:
        await _try_refresh_guide_map()

    return _guide_map or {}


def resize_for_jpg(img: Image.Image) -> Image.Image:
    """如果图片尺寸超过 JPG 限制，按比例缩放。"""
    width, height = img.size
    if width <= JPG_MAX_DIMENSION and height <= JPG_MAX_DIMENSION:
        return img

    scale = min(JPG_MAX_DIMENSION / width, JPG_MAX_DIMENSION / height)
    new_width = int(width * scale)
    new_height = int(height * scale)
    logger.info(
        f"[EndGuide] 攻略图尺寸{width}x{height}超过JPG限制，"
        f"缩放至{new_width}x{new_height}"
    )
    return img.resize((new_width, new_height), Image.LANCZOS)


def compress_image_to_jpg(img: Image.Image, max_size_mb: int) -> bytes:
    """将图片转为 JPG，若超过 max_size_mb 则逐步降低质量压缩。"""
    max_size_bytes = max_size_mb * 1024 * 1024

    img = resize_for_jpg(img)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=95)
    result = buffer.getvalue()

    if len(result) <= max_size_bytes:
        return result

    for quality in range(90, 10, -5):
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        result = buffer.getvalue()
        if len(result) <= max_size_bytes:
            logger.info(
                f"[EndGuide] 攻略图压缩至quality={quality}, "
                f"大小={len(result) / 1024 / 1024:.2f}MB"
            )
            return result

    logger.warning(
        f"[EndGuide] 攻略图压缩至最低质量仍超过{max_size_mb}MB, "
        f"当前大小={len(result) / 1024 / 1024:.2f}MB"
    )
    return result


def compress_image_bytes_to_jpg(image_bytes: bytes, max_size_mb: int) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        return compress_image_to_jpg(img, max_size_mb)


async def _fetch_guide_items() -> dict[str, dict]:
    """Fetch guide entries from catalog API (1 request)."""
    catalog_items = await wiki_client.get_catalog_items(
        sub_type_names={"干员攻略"}
    )
    guide_entries = catalog_items.get("干员攻略", [])
    if not guide_entries:
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
    items = guide_map.get("items", {})
    for item_id_str, meta in items.items():
        if meta.get("char_name") == char_name:
            return int(item_id_str)
    return None


# ==================== 富文本块解析 ====================


def _inline_html(elements: list) -> str:
    """Render Skland inlineElements to HTML (preserves bold/italic/links)."""
    out: list[str] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        kind = el.get("kind")
        if kind == "text":
            text = el.get("text", {}).get("text", "") or ""
            if not text:
                continue
            piece = html_lib.escape(text).replace("\n", "<br>")
            if el.get("bold"):
                piece = f"<b>{piece}</b>"
            if el.get("italic"):
                piece = f"<i>{piece}</i>"
            out.append(piece)
        elif kind == "link":
            text = el.get("text", {}).get("text", "") or ""
            href = el.get("link", {}).get("url", "") or "#"
            out.append(
                f'<a href="{html_lib.escape(href)}">'
                f"{html_lib.escape(text)}</a>"
            )
        elif kind == "br":
            out.append("<br>")
    return "".join(out)


def _inline_plain_len(elements: list) -> int:
    """Count visible characters in inlineElements (for threshold check)."""
    n = 0
    for el in elements:
        if not isinstance(el, dict):
            continue
        if el.get("kind") in ("text", "link"):
            t = el.get("text", {}).get("text", "")
            if isinstance(t, str):
                n += len(t.strip())
    return n


def _build_global_block_index(document_map: dict) -> dict:
    """Flatten every doc's blockMap into one lookup."""
    idx: dict = {}
    for doc_obj in document_map.values():
        bm = doc_obj.get("blockMap", {})
        for bid, blk in bm.items():
            idx[bid] = blk
    return idx


def _block_to_struct(blk: dict, blocks: dict) -> Optional[dict]:
    """Convert a raw Skland block to our cache-friendly struct.

    Returns None for unsupported / empty blocks.
    """
    if not isinstance(blk, dict):
        return None
    kind = blk.get("kind")

    if kind == "text":
        t = blk.get("text", {})
        text_kind = t.get("kind", "body")
        elements = t.get("inlineElements", [])
        plain_len = _inline_plain_len(elements)
        if not elements:
            return {"kind": "p", "html": "", "plain_len": 0, "empty": True}
        if text_kind in ("heading1", "heading2"):
            return {
                "kind": "h2",
                "html": _inline_html(elements),
                "plain_len": plain_len,
            }
        if text_kind in ("heading3", "heading4", "heading5"):
            return {
                "kind": "h3",
                "html": _inline_html(elements),
                "plain_len": plain_len,
            }
        return {
            "kind": "p",
            "html": _inline_html(elements),
            "plain_len": plain_len,
        }

    if kind == "image":
        img = blk.get("image", {})
        url = img.get("url", "")
        if not url:
            return None
        return {
            "kind": "image",
            "url": url,
            "width": img.get("width", ""),
            "height": img.get("height", ""),
        }

    if kind == "table":
        tbl = blk.get("table", {})
        row_ids = tbl.get("rowIds", [])
        col_ids = tbl.get("columnIds", [])
        cell_map = tbl.get("cellMap", {})
        rows: list[list[dict]] = []
        for rid in row_ids:
            row: list[dict] = []
            for cid in col_ids:
                cell = cell_map.get(f"{rid}_{cid}", {})
                child_ids = cell.get("childIds", [])
                child_blocks = []
                for chid in child_ids:
                    sub = blocks.get(chid)
                    if not sub:
                        continue
                    sub_struct = _block_to_struct(sub, blocks)
                    if sub_struct:
                        child_blocks.append(sub_struct)
                row.append({
                    "blocks": child_blocks,
                    "row_span": int(cell.get("rowSpan", 1) or 1),
                    "col_span": int(cell.get("colSpan", 1) or 1),
                })
            rows.append(row)
        if not rows:
            return None
        return {
            "kind": "table",
            "row_header": bool(tbl.get("rowHeader", False)),
            "col_header": bool(tbl.get("colHeader", False)),
            "rows": rows,
        }

    return None


def _struct_text_chars(structs: list[dict]) -> int:
    """Sum visible-text chars across a list of structured blocks (recursive)."""
    n = 0
    for s in structs:
        if not isinstance(s, dict):
            continue
        if s.get("kind") in ("p", "h2", "h3"):
            n += int(s.get("plain_len", 0) or 0)
        elif s.get("kind") == "table":
            for row in s.get("rows", []):
                for cell in row:
                    n += _struct_text_chars(cell.get("blocks", []))
    return n


def _extract_guide_tabs(item: dict) -> list[dict]:
    """Extract structured guide tabs from a wiki item.

    Each tab → {author, blocks (structured), images (legacy URL list),
    text_chars}.
    """
    doc = item.get("document", {})
    document_map = doc.get("documentMap", {})
    widget_common_map = doc.get("widgetCommonMap", {})
    chapter_group = doc.get("chapterGroup", [])

    all_blocks = _build_global_block_index(document_map)

    tabs: list[dict] = []

    for group in chapter_group:
        for widget_ref in group.get("widgets", []):
            wid = widget_ref.get("id", "")
            widget = widget_common_map.get(wid, {})
            tab_list = widget.get("tabList", [])
            tab_data_map = widget.get("tabDataMap", {})

            for tab in tab_list:
                tab_id = tab.get("tabId", "")
                author = tab.get("title", "")
                tab_data = tab_data_map.get(tab_id, {})
                content_id = tab_data.get("content", "")
                if not content_id or content_id not in document_map:
                    continue

                content_doc = document_map[content_id]
                content_blocks = content_doc.get("blockMap", {})

                structured: list[dict] = []
                images: list[str] = []
                for bid in content_doc.get("blockIds", []):
                    blk = content_blocks.get(bid, {})
                    s = _block_to_struct(blk, all_blocks)
                    if s is None:
                        continue
                    structured.append(s)
                    if s.get("kind") == "image":
                        images.append(s["url"])

                if not structured:
                    continue

                tabs.append({
                    "author": author,
                    "blocks": structured,
                    "images": images,
                    "text_chars": _struct_text_chars(structured),
                })

    return tabs


# ==================== 缓存管理 ====================


def _guide_cache_path(item_id: int) -> Path:
    return GUIDE_CACHE_PATH / f"{item_id}.json"


def _is_guide_cache_expired(item_id: int) -> bool:
    cache_path = _guide_cache_path(item_id)
    if not cache_path.exists():
        return True
    try:
        raw = cache_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if int(data.get("schema", 1)) < GUIDE_CACHE_SCHEMA:
            return True
        ft = data.get("fetch_time", 0)
        return (time.time() - ft) > GUIDE_DETAIL_EXPIRE_SECONDS
    except Exception:
        return True


async def _get_guide_data(item_id: int) -> Optional[list[dict]]:
    """Get structured guide tabs with caching."""
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

    item = await wiki_client.get_item_info(item_id)
    if not item:
        return None

    tabs = _extract_guide_tabs(item)
    if not tabs:
        return None

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "schema": GUIDE_CACHE_SCHEMA,
            "fetch_time": time.time(),
            "tabs": tabs,
        }
        async with aiofiles.open(
            cache_path, "w", encoding="utf-8"
        ) as f:
            await f.write(json.dumps(cache_data, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"[EndGuide] Failed to save cache {item_id}: {e}")

    return tabs


# ==================== 图片拼接（少文本路径） ====================

GUIDE_IMG_CACHE = WIKI_GUIDE_CACHE / "img"


async def _download_and_stitch(
    image_urls: list[str],
    max_size_mb: int,
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
        return compress_image_to_jpg(images[0], max_size_mb)

    max_width = max(img.width for img in images)
    total_height = 0
    for img in images:
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

    return compress_image_to_jpg(canvas, max_size_mb)


# ==================== HTML 渲染（多文本路径） ====================


def _render_struct_html(blocks: list[dict]) -> str:
    """Render a list of structured blocks to HTML (recursive for tables)."""
    out: list[str] = []
    for blk in blocks:
        kind = blk.get("kind")
        if kind == "h2":
            out.append(f"<h2>{blk.get('html', '')}</h2>")
        elif kind == "h3":
            out.append(f"<h3>{blk.get('html', '')}</h3>")
        elif kind == "p":
            inner = blk.get("html", "")
            if not inner or blk.get("empty"):
                out.append('<p class="empty">&nbsp;</p>')
            else:
                out.append(f"<p>{inner}</p>")
        elif kind == "image":
            url = html_lib.escape(blk.get("url", ""))
            if url:
                out.append(f'<img src="{url}" referrerpolicy="no-referrer">')
        elif kind == "table":
            rows_html: list[str] = []
            row_header = blk.get("row_header", False)
            for ridx, row in enumerate(blk.get("rows", [])):
                cells_html: list[str] = []
                for cell in row:
                    inner = _render_struct_html(cell.get("blocks", []))
                    rs = int(cell.get("row_span", 1) or 1)
                    cs = int(cell.get("col_span", 1) or 1)
                    span_attrs = ""
                    if rs > 1:
                        span_attrs += f' rowspan="{rs}"'
                    if cs > 1:
                        span_attrs += f' colspan="{cs}"'
                    tag = "th" if (row_header and ridx == 0) else "td"
                    cells_html.append(
                        f"<{tag}{span_attrs}>{inner}</{tag}>"
                    )
                rows_html.append("<tr>" + "".join(cells_html) + "</tr>")
            out.append("<table>" + "".join(rows_html) + "</table>")
    return "".join(out)


async def _render_rich_tab(
    tab: dict, char_name: str, source_url: str, max_size_mb: int
) -> Optional[bytes]:
    """Render a text-heavy tab (text + images + tables) to a single image."""
    body_html = _render_struct_html(tab.get("blocks", []))
    if not body_html:
        return None

    context = {
        "title": f"{char_name} · 攻略",
        "author": tab.get("author", "未知"),
        "body_html": body_html,
        "source_url": source_url,
    }
    try:
        rendered = await render_html(
            _guide_templates, "end_guide_card.html", context
        )
        return compress_image_bytes_to_jpg(rendered, max_size_mb)
    except Exception as e:
        logger.warning(f"[EndGuide] Rich render failed: {e}")
        return None


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

    if item_id is None and original_name and original_name != char_name:
        item_id = _find_guide_id(guide_map, original_name)

    if item_id is None and await _try_refresh_guide_map():
        gm = _guide_map or {}
        item_id = _find_guide_id(gm, char_name)
        if item_id is None and original_name and original_name != char_name:
            item_id = _find_guide_id(gm, original_name)

    if item_id is None:
        return

    tabs = await _get_guide_data(item_id)
    if not tabs:
        return

    wiki_url = GUIDE_WIKI_URL.format(item_id=item_id)
    max_size_mb = EndConfig.get_config("EndGuideMaxSize").data

    msgs: list = []
    for tab in tabs:
        author = tab.get("author", "未知")
        text_chars = int(tab.get("text_chars", 0) or 0)
        image_urls = tab.get("images", [])
        blocks = tab.get("blocks", [])

        msgs.append(f"攻略作者：{author}")

        # Rich path: substantial text → render text+images+tables as one image
        if text_chars >= RICH_RENDER_TEXT_THRESHOLD and blocks:
            rendered = await _render_rich_tab(
                tab, char_name, wiki_url, max_size_mb
            )
            if rendered:
                msgs.append(f"base64://{b64encode(rendered).decode()}")
                continue
            # Fall through to image-stitching on render failure

        # Legacy path: stitch images vertically
        if image_urls:
            stitched = await _download_and_stitch(image_urls, max_size_mb)
            if stitched:
                msgs.append(f"base64://{b64encode(stitched).decode()}")
            else:
                for url in image_urls:
                    msgs.append(url)

    msgs.append(f"来源：{wiki_url}")

    await bot.send(msgs)
