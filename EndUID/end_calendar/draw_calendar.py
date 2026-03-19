import io
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

import aiofiles
from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..utils.path import CACHE_BASE

TEXTURE_PATH = Path(__file__).parent.parent / "end_char" / "texture2d"
TEMPLATE_PATH = Path(__file__).parent.parent / "templates"
CALENDAR_CACHE_PATH = CACHE_BASE / "calendar"
CALENDAR_CACHE_PATH.mkdir(parents=True, exist_ok=True)
CALENDAR_IMG_CACHE = CALENDAR_CACHE_PATH / "img"
CALENDAR_IMG_CACHE.mkdir(parents=True, exist_ok=True)

calendar_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

CACHE_DURATION = 3600  # 1 hour
_cache: Dict[str, dict] = {}
_cache_time: float = 0


async def _fetch_wiki_data() -> Optional[Dict]:
    """Use Playwright to intercept wiki API responses."""
    global _cache, _cache_time

    now = time.time()
    if _cache and (now - _cache_time) < CACHE_DURATION:
        logger.debug("[EndUID][Calendar] 使用缓存数据")
        return _cache

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("[EndUID][Calendar] Playwright 未安装")
        return None

    results: Dict[str, dict] = {}
    targets = ['char-pool', 'activity', 'banner', 'weapon-pool']

    async def on_response(resp):
        url = resp.url
        for key in targets:
            if key in url:
                try:
                    body = await resp.json()
                    if body.get("code") == 0:
                        results[key] = body.get("data", {})
                except Exception:
                    pass

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            page.on('response', on_response)

            try:
                await page.goto(
                    'https://wiki.skland.com/endfield',
                    timeout=30000,
                )
                await page.wait_for_timeout(6000)
            except Exception as e:
                logger.warning(f"[EndUID][Calendar] 页面加载异常: {e}")

            await browser.close()
    except Exception as e:
        logger.error(f"[EndUID][Calendar] Playwright 异常: {e}")
        return None

    if not results:
        logger.warning("[EndUID][Calendar] 未获取到任何数据")
        return None

    _cache = results
    _cache_time = time.time()
    logger.info(f"[EndUID][Calendar] 获取数据: {list(results.keys())}")
    return results


def _ts_to_str(ts_str: str, fmt: str = "%m.%d %H:%M") -> str:
    try:
        return datetime.fromtimestamp(int(ts_str)).strftime(fmt)
    except Exception:
        return ""


def _get_event_status(start_ts: str, end_ts: str):
    """Return (status_text, progress_pct, color, remaining_text)."""
    now = time.time()
    try:
        start = int(start_ts)
        end = int(end_ts)
    except (ValueError, TypeError):
        return "未知", 0, "#555", ""

    if now < start:
        delta = start - now
        return "未开始", 0, "#555", _fmt_remaining(delta)
    elif now > end:
        return "已结束", 100, "#555", ""
    else:
        elapsed = now - start
        total = end - start
        pct = min(100, round(elapsed / total * 100)) if total > 0 else 0
        remaining = end - now
        color = "#ef4444" if remaining < 3 * 86400 else "#ffe600"
        return "进行中", pct, color, _fmt_remaining(remaining)


def _fmt_remaining(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    if days > 0:
        return f"{days}天{hours}小时"
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}小时{minutes}分"
    return f"{minutes}分钟"


async def draw_calendar(ev: Event) -> Union[bytes, str]:
    data = await _fetch_wiki_data()
    if not data:
        return "❌ 获取日历数据失败，请稍后重试"

    now = datetime.now()

    # Banner
    banner_b64 = ""
    banners = data.get("banner", {}).get("list", [])
    if banners:
        banner_url = banners[0].get("pic", "")
        if banner_url:
            banner_b64 = await get_image_b64_with_cache(
                banner_url, CALENDAR_IMG_CACHE
            )

    # Char pools
    char_pools = []
    for pool in data.get("char-pool", {}).get("list", []):
        chars = []
        for ch in pool.get("chars", []):
            pic_url = ch.get("pic", "")
            pic_b64 = ""
            if pic_url:
                pic_b64 = await get_image_b64_with_cache(
                    pic_url, CALENDAR_IMG_CACHE
                )
            chars.append({
                "name": ch.get("name", ""),
                "pic": pic_b64,
                "rarity": ch.get("rarity", ""),
                "dotType": ch.get("dotType", ""),
            })

        start_ts = pool.get("poolStartAtTs", "0")
        end_ts = pool.get("poolEndAtTs", "0")
        status, pct, color, remaining = _get_event_status(start_ts, end_ts)

        char_pools.append({
            "name": pool.get("name", ""),
            "chars": chars,
            "startTime": _ts_to_str(start_ts),
            "endTime": _ts_to_str(end_ts),
            "status": status,
            "progress": pct,
            "color": color,
            "remaining": remaining,
        })

    # Weapon pools
    weapon_pools = []
    for pool in data.get("weapon-pool", {}).get("list", []):
        start_ts = pool.get("poolStartAtTs", "0")
        end_ts = pool.get("poolEndAtTs", "0")
        status, pct, color, remaining = _get_event_status(start_ts, end_ts)
        weapon_pools.append({
            "name": pool.get("name", ""),
            "startTime": _ts_to_str(start_ts),
            "endTime": _ts_to_str(end_ts),
            "status": status,
            "progress": pct,
            "color": color,
            "remaining": remaining,
        })

    # Activities
    activities = []
    for act in data.get("activity", {}).get("list", []):
        pic_url = act.get("pic", "")
        pic_b64 = ""
        if pic_url:
            pic_b64 = await get_image_b64_with_cache(
                pic_url, CALENDAR_IMG_CACHE
            )

        start_ts = act.get("activityStartAtTs", "0")
        end_ts = act.get("activityEndAtTs", "0")
        status, pct, color, remaining = _get_event_status(start_ts, end_ts)

        activities.append({
            "name": act.get("name", ""),
            "description": act.get("description", ""),
            "pic": pic_b64,
            "startTime": _ts_to_str(start_ts),
            "endTime": _ts_to_str(end_ts),
            "status": status,
            "progress": pct,
            "color": color,
            "remaining": remaining,
        })

    context = {
        "now": now.strftime("%Y-%m-%d %H:%M"),
        "banner": banner_b64,
        "charPools": char_pools,
        "weaponPools": weapon_pools,
        "activities": activities,
        "bg": image_to_base64(TEXTURE_PATH / "bg.png", quality=75),
        "end_logo": image_to_base64(TEXTURE_PATH / "end.png", quality=75),
    }

    img_bytes = await render_html(
        calendar_templates, "end_calendar.html", context
    )
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))

    return "❌ HTML 渲染失败"
