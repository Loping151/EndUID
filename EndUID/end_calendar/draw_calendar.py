import asyncio
import io
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

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
from ..utils.path import CALENDAR_IMG_CACHE
from ..end_wiki.skland_wiki import wiki_client
from .official_calendar import append_official_calendar

TEXTURE_PATH = Path(__file__).parent.parent / "end_char" / "texture2d"
TEMPLATE_PATH = Path(__file__).parent.parent / "templates"

calendar_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

CACHE_DURATION = 3600  # 1 hour
_cache: Dict[str, dict] = {}
_cache_time: float = 0
_fetch_lock = asyncio.Lock()

LANDING_ENDPOINTS = ("char-pool", "activity", "banner", "weapon-pool")

# 同 wiki 角标
DOT_LABELS = {
    "label_type_up": ("UP", "yellow"),
    "label_type_new": ("NEW", "yellow"),
    "label_type_remake": ("复刻", "yellow"),
    "label_type_time_limited": ("限时", "yellow"),
    "label_type_limited": ("限定", "yellow"),
    "label_type_preview": ("预告", "blue"),
    "label_type_foresee": ("前瞻", "blue"),
    "un_online": ("未上线", "gray"),
}

ACTIVITY_PERMANENT = 2
STATE_ORDER = {"ongoing": 0, "upcoming": 1, "ended": 2, "none": 3, "permanent": 3}


async def _fetch_landing_http() -> Optional[Dict[str, dict]]:
    out: Dict[str, dict] = {}
    for ep in LANDING_ENDPOINTS:
        data = await wiki_client.get_landing(ep)
        if data is None:
            logger.warning(f"[ENDUID·日历] HTTP 拉取 {ep} 失败")
            return None
        out[ep] = data
    return out


async def _fetch_wiki_data() -> Optional[Dict]:
    """先走 HTTP 直连 zonai；拿不全才 fallback playwright 拦截。"""
    global _cache, _cache_time

    now = time.time()
    if _cache and (now - _cache_time) < CACHE_DURATION:
        logger.debug("[ENDUID·日历] 使用缓存数据")
        return _cache

    async with _fetch_lock:
        # 拿锁后 double-check：等待期间另一协程可能已刷新
        now = time.time()
        if _cache and (now - _cache_time) < CACHE_DURATION:
            logger.debug("[ENDUID·日历] 使用缓存数据（等待后命中）")
            return _cache

        results = await _fetch_landing_http()
        if results:
            _cache = results
            _cache_time = time.time()
            logger.info(f"[ENDUID·日历] HTTP 获取数据: {list(results.keys())}")
            return results

        logger.warning("[ENDUID·日历] HTTP 拉取失败，fallback 到 playwright")
        results = await _fetch_wiki_data_via_playwright()
        if not results:
            return None

        _cache = results
        _cache_time = time.time()
        logger.info(f"[ENDUID·日历] playwright 获取数据: {list(results.keys())}")
        return results


async def _fetch_wiki_data_via_playwright() -> Optional[Dict]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("[ENDUID·日历] Playwright 未安装")
        return None

    results: Dict[str, dict] = {}
    targets = LANDING_ENDPOINTS

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
            browser = await p.chromium.launch(headless=True, args=["--disable-gpu"])
            page = await browser.new_page()
            page.on('response', on_response)

            try:
                await page.goto(
                    'https://wiki.skland.com/endfield',
                    timeout=30000,
                )
                await page.wait_for_timeout(6000)
            except Exception as e:
                logger.warning(f"[ENDUID·日历] 页面加载异常: {e}")

            await browser.close()
    except Exception as e:
        logger.error(f"[ENDUID·日历] Playwright 异常: {e}")
        return None

    return results if results else None


def _ts_to_str(ts_str: str, fmt: str = "%m.%d %H:%M") -> str:
    try:
        return datetime.fromtimestamp(int(ts_str)).strftime(fmt)
    except Exception:
        return ""


def _get_event_status(start_ts: str, end_ts: str) -> dict:
    try:
        start = int(start_ts)
        end = int(end_ts)
    except (ValueError, TypeError):
        start = end = 0
    if start <= 0 or end <= 0:
        return {"state": "none", "status": "", "progress": 0, "color": "#555", "remaining": ""}

    now = time.time()
    if now < start:
        return {
            "state": "upcoming",
            "status": "未开始",
            "progress": 0,
            "color": "#555",
            "remaining": f"{_fmt_remaining(start - now)}后开启",
        }
    if now > end:
        return {"state": "ended", "status": "已结束", "progress": 100, "color": "#555", "remaining": ""}
    remaining = end - now
    return {
        "state": "ongoing",
        "status": "进行中",
        "progress": min(100, round((now - start) / max(end - start, 1) * 100)),
        "color": "#ef4444" if remaining < 3 * 86400 else "#ffe600",
        "remaining": f"还剩{_fmt_remaining(remaining)}",
    }


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


async def _build_icons(items: List[dict]) -> List[dict]:
    icons = []
    for it in items:
        pic_url = it.get("pic", "")
        label, tone = DOT_LABELS.get(it.get("dotType", ""), ("", ""))
        icons.append({
            "pic": await get_image_b64_with_cache(pic_url, CALENDAR_IMG_CACHE) if pic_url else "",
            "rarity": it.get("rarity", ""),
            "label": label,
            "tone": tone,
        })
    return icons


async def _build_pools(pools: List[dict], icon_key: str) -> List[dict]:
    out = []
    for pool in pools:
        start_ts = pool.get("poolStartAtTs", "0")
        end_ts = pool.get("poolEndAtTs", "0")
        out.append({
            "name": pool.get("name", ""),
            "icons": await _build_icons(pool.get(icon_key) or []),
            "startTime": _ts_to_str(start_ts),
            "endTime": _ts_to_str(end_ts),
            **_get_event_status(start_ts, end_ts),
        })
    out.sort(key=lambda x: STATE_ORDER[x["state"]])
    return out


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

    char_pools = await _build_pools(data.get("char-pool", {}).get("list", []), "chars")
    weapon_pools = await _build_pools(data.get("weapon-pool", {}).get("list", []), "weapons")

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
        if act.get("activityType") == ACTIVITY_PERMANENT:
            st = {"state": "permanent", "status": "常驻活动", "progress": 0, "color": "#555", "remaining": ""}
        else:
            st = _get_event_status(start_ts, end_ts)

        activities.append({
            "name": act.get("name", ""),
            "description": act.get("description", ""),
            "pic": pic_b64,
            "startTime": _ts_to_str(start_ts),
            "endTime": _ts_to_str(end_ts),
            **st,
        })
    activities.sort(key=lambda x: STATE_ORDER[x["state"]])

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
        img = await append_official_calendar(Image.open(io.BytesIO(img_bytes)))
        return await convert_img(img)

    return "❌ HTML 渲染失败"
