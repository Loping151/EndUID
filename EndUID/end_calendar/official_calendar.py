"""官网版本日历（endfield.hypergryph.com/#calendar）：title + timeline + content 拼图，拼到日历右侧。"""
import re
import time
import asyncio
import hashlib
from typing import Dict, Optional
from pathlib import Path

import httpx
from PIL import Image

from gsuid_core.logger import logger

from ..utils.path import CALENDAR_OFFICIAL_CACHE
from ..utils.image import pic_download_from_url

OFFICIAL_URL = "https://endfield.hypergryph.com/"
CACHE_DURATION = 3600

# 官网 CSS：title/content 宽 141.375rem，timeline 宽 146.7243rem，三者右对齐
TIMELINE_WIDTH_RATIO = 146.7243 / 141.375
TITLE_GAP = 3
TIMELINE_GAP = 8

_IMG_RE = re.compile(r'<img[^>]*?src="([^"]+)"[^>]*?alt="calendar\.(title|timeline|content)"')

_lock = asyncio.Lock()
_checked_at: float = 0
_current: Optional[Path] = None


async def _fetch_image_urls() -> Dict[str, str]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(OFFICIAL_URL, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    urls: Dict[str, str] = {}
    for src, key in _IMG_RE.findall(resp.text):
        urls.setdefault(key, src)
    return urls


def _stitch(title: Image.Image, content: Image.Image, timeline: Optional[Image.Image]) -> Image.Image:
    w = content.width
    title = title.resize((w, round(title.height * w / title.width)), Image.Resampling.LANCZOS)
    layers = [(title, 0)]
    y = title.height + TITLE_GAP
    if timeline is not None:
        tw = round(w * TIMELINE_WIDTH_RATIO)
        th = round(timeline.height * tw / timeline.width)
        timeline = timeline.resize((tw, th), Image.Resampling.LANCZOS).crop((tw - w, 0, tw, th))
        layers.append((timeline, y))
        y += th + TIMELINE_GAP
    layers.append((content, y))

    canvas = Image.new("RGBA", (w, y + content.height), (255, 255, 255, 255))
    for layer, top in layers:
        canvas.alpha_composite(layer.convert("RGBA"), (0, top))
    return canvas.convert("RGB")


async def _update() -> Path:
    urls = await _fetch_image_urls()
    if "title" not in urls or "content" not in urls:
        raise ValueError(f"官网未找到日历图片: {list(urls)}")

    key = hashlib.md5("|".join(urls[k] for k in sorted(urls)).encode()).hexdigest()[:12]
    out = CALENDAR_OFFICIAL_CACHE / f"calendar_{key}.webp"
    if out.exists():
        return out

    title = await pic_download_from_url(CALENDAR_OFFICIAL_CACHE, urls["title"])
    content = await pic_download_from_url(CALENDAR_OFFICIAL_CACHE, urls["content"])
    timeline = None
    if "timeline" in urls:
        timeline = await pic_download_from_url(CALENDAR_OFFICIAL_CACHE, urls["timeline"])

    img = await asyncio.to_thread(_stitch, title, content, timeline)
    tmp = out.with_suffix(".tmp")
    await asyncio.to_thread(img.save, tmp, "WEBP", quality=90)
    tmp.replace(out)
    logger.info(f"[ENDUID·日历] 官网日历已更新: {out.name}")
    return out


def _latest_cached() -> Optional[Path]:
    files = sorted(CALENDAR_OFFICIAL_CACHE.glob("calendar_*.webp"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


async def get_official_calendar() -> Optional[Path]:
    global _checked_at, _current
    async with _lock:
        if _current is not None and _current.exists() and time.time() - _checked_at < CACHE_DURATION:
            return _current
        try:
            _current = await _update()
        except Exception as e:
            logger.warning(f"[ENDUID·日历] 官网日历获取失败，使用本地缓存: {e}")
            _current = _latest_cached()
        _checked_at = time.time()
        return _current


def _append_right(img: Image.Image, side_path: Path) -> Image.Image:
    side = Image.open(side_path).convert("RGB")
    side_w = round(side.width * img.height / side.height)
    side = side.resize((side_w, img.height), Image.Resampling.LANCZOS)
    out = Image.new("RGB", (img.width + side_w, img.height))
    out.paste(img.convert("RGB"), (0, 0))
    out.paste(side, (img.width, 0))
    return out


async def append_official_calendar(img: Image.Image) -> Image.Image:
    side_path = await get_official_calendar()
    if side_path is None:
        return img
    try:
        return await asyncio.to_thread(_append_right, img, side_path)
    except Exception as e:
        logger.warning(f"[ENDUID·日历] 拼接官网日历失败: {e}")
        return img
