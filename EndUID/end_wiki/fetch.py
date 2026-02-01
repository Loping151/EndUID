import asyncio
import json
import time
from urllib.parse import quote

import aiofiles
import aiohttp

from pathlib import Path

from gsuid_core.logger import logger

from ..utils.path import WIKI_CACHE_PATH, WIKI_CHAR_CACHE, WIKI_WEAPON_CACHE
from .models import (
    CharListEntry,
    CharWiki,
    WeaponListEntry,
    WeaponWiki,
    WikiListData,
)
from .parser import parse_char_wiki, parse_homepage, parse_weapon_wiki

WIKI_BASE_URL = "https://wiki.biligame.com/zmd/"
WIKI_HOME_URL = "https://wiki.biligame.com/zmd/%E9%A6%96%E9%A1%B5"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://wiki.biligame.com/zmd/",
}

LIST_JSON_PATH = WIKI_CACHE_PATH / "list.json"
DETAIL_EXPIRE_SECONDS = 86400  # 1 day
# Gacha banners are considered expired if fetch_time is older than 6 hours
GACHA_CHECK_SECONDS = 21600

# Global lock for all bilibili wiki requests
_fetch_lock = asyncio.Lock()


async def _fetch_page(url: str) -> str | None:
    """Fetch a wiki page HTML with the global lock."""
    async with _fetch_lock:
        try:
            async with aiohttp.ClientSession(headers=HEADERS) as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            f"[EndWiki] 请求失败: HTTP {resp.status} {url}"
                        )
                        return None
                    html = await resp.text()
                    if (
                        "AccessDeny" in html[:500]
                        or "Restricted Access" in html[:500]
                    ):
                        logger.warning(f"[EndWiki] 请求被 WAF 拦截: {url}")
                        return None
                    return html
        except Exception as e:
            logger.error(f"[EndWiki] 请求异常: {url} {e}")
            return None


async def fetch_wiki_page(name: str) -> str | None:
    """Fetch a wiki page by name."""
    url = WIKI_BASE_URL + quote(name)
    return await _fetch_page(url)


# ==================== list.json 管理 ====================


def _load_list_data() -> WikiListData | None:
    """Load list.json synchronously (small file, OK to block briefly)."""
    if not LIST_JSON_PATH.exists():
        return None
    try:
        raw = LIST_JSON_PATH.read_text(encoding="utf-8")
        return WikiListData.model_validate_json(raw)
    except Exception as e:
        logger.warning(f"[EndWiki] 读取 list.json 失败: {e}")
        return None


async def _save_list_data(data: WikiListData) -> None:
    """Save list.json."""
    try:
        LIST_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(
            LIST_JSON_PATH, "w", encoding="utf-8"
        ) as f:
            await f.write(data.model_dump_json(indent=2))
    except Exception as e:
        logger.warning(f"[EndWiki] 写入 list.json 失败: {e}")


def _is_list_stale(data: WikiListData | None) -> bool:
    """Check if list data needs re-fetching.

    Stale if fetch_time and now are separated by a 12:00 boundary
    (noon or midnight).
    """
    if data is None or data.fetch_time == 0:
        return True
    from datetime import datetime, timedelta

    ft = datetime.fromtimestamp(data.fetch_time)
    now = datetime.now()

    # Walk forward from fetch_time, hitting each 12:00 boundary
    boundary = ft.replace(hour=12, minute=0, second=0, microsecond=0)
    if boundary <= ft:
        boundary += timedelta(hours=12)

    return now >= boundary


async def _refresh_list() -> WikiListData | None:
    """Fetch homepage and rebuild list.json."""
    logger.info("[EndWiki] 正在刷新首页数据...")
    html = await _fetch_page(WIKI_HOME_URL)
    if not html:
        return None

    data = parse_homepage(html)
    if not data:
        return None

    data.fetch_time = time.time()
    await _save_list_data(data)
    logger.info(
        f"[EndWiki] 首页数据已刷新: "
        f"{sum(len(v) for v in data.characters.values())} 角色, "
        f"{sum(len(v) for v in data.weapons.values())} 武器, "
        f"{len(data.gacha)} 卡池"
    )
    return data


async def ensure_list_data() -> WikiListData | None:
    """Get list data, refreshing from homepage if stale."""
    data = _load_list_data()
    if _is_list_stale(data):
        refreshed = await _refresh_list()
        if refreshed:
            return refreshed
        # If refresh failed, return stale data if available
        return data
    return data


def find_char_in_list(
    data: WikiListData, name: str
) -> bool:
    """Check if a character name exists in list data."""
    for entries in data.characters.values():
        for entry in entries:
            if entry.name == name:
                return True
    return False


def find_weapon_in_list(
    data: WikiListData, name: str
) -> bool:
    """Check if a weapon name exists in list data."""
    for entries in data.weapons.values():
        for entry in entries:
            if entry.name == name:
                return True
    return False


def get_char_entry(
    data: WikiListData, name: str
) -> CharListEntry | None:
    """Get character entry from list data."""
    for entries in data.characters.values():
        for entry in entries:
            if entry.name == name:
                return entry
    return None


def get_weapon_entry(
    data: WikiListData, name: str
) -> WeaponListEntry | None:
    """Get weapon entry from list data."""
    for entries in data.weapons.values():
        for entry in entries:
            if entry.name == name:
                return entry
    return None


# ==================== 角色/武器详情缓存 ====================


def _is_detail_expired(cache_path: Path) -> bool:
    """Check if a detail cache file is expired (>1 day old)."""
    if not cache_path.exists():
        return True
    try:
        raw = cache_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        fetch_time = data.get("fetch_time", 0)
        return (time.time() - fetch_time) > DETAIL_EXPIRE_SECONDS
    except Exception:
        return True


async def get_char_wiki(
    char_name: str, force_refresh: bool = False
) -> CharWiki | None:
    """Get character wiki detail, with 1-day JSON cache.

    Only fetches from wiki if the character exists in list.json.
    """
    list_data = await ensure_list_data()

    # Check list.json first — skip fetch for unknown names
    if list_data and not find_char_in_list(list_data, char_name):
        return None

    cache_path = WIKI_CHAR_CACHE / f"{char_name}.json"

    if not force_refresh and not _is_detail_expired(cache_path):
        try:
            async with aiofiles.open(
                cache_path, "r", encoding="utf-8"
            ) as f:
                data = json.loads(await f.read())
            return CharWiki.model_validate(data)
        except Exception as e:
            logger.warning(
                f"[EndWiki] 读取角色缓存失败 {char_name}: {e}"
            )

    html = await fetch_wiki_page(char_name)
    if not html:
        return None

    wiki = parse_char_wiki(html, char_name)
    if not wiki:
        return None

    wiki.fetch_time = time.time()

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(
            cache_path, "w", encoding="utf-8"
        ) as f:
            await f.write(wiki.model_dump_json(indent=2))
    except Exception as e:
        logger.warning(f"[EndWiki] 写入角色缓存失败 {char_name}: {e}")

    return wiki


async def get_weapon_wiki(
    weapon_name: str, force_refresh: bool = False
) -> WeaponWiki | None:
    """Get weapon wiki detail, with 1-day JSON cache.

    Only fetches from wiki if the weapon exists in list.json.
    """
    list_data = await ensure_list_data()

    # Check list.json first — skip fetch for unknown names
    if list_data and not find_weapon_in_list(list_data, weapon_name):
        return None

    cache_path = WIKI_WEAPON_CACHE / f"{weapon_name}.json"

    if not force_refresh and not _is_detail_expired(cache_path):
        try:
            async with aiofiles.open(
                cache_path, "r", encoding="utf-8"
            ) as f:
                data = json.loads(await f.read())
            return WeaponWiki.model_validate(data)
        except Exception as e:
            logger.warning(
                f"[EndWiki] 读取武器缓存失败 {weapon_name}: {e}"
            )

    html = await fetch_wiki_page(weapon_name)
    if not html:
        return None

    wiki = parse_weapon_wiki(html, weapon_name)
    if not wiki:
        return None

    wiki.fetch_time = time.time()

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(
            cache_path, "w", encoding="utf-8"
        ) as f:
            await f.write(wiki.model_dump_json(indent=2))
    except Exception as e:
        logger.warning(f"[EndWiki] 写入武器缓存失败 {weapon_name}: {e}")

    return wiki
