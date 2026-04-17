"""Wiki data fetching — backed by Skland Wiki catalog API."""
import json
import time

import aiofiles

from gsuid_core.logger import logger

from ..utils.path import WIKI_CACHE_PATH, WIKI_CHAR_CACHE, WIKI_WEAPON_CACHE
from .models import (
    CharListEntry,
    CharWiki,
    WeaponListEntry,
    WeaponWiki,
    WikiListData,
)
from .constants import ATTR_ID_MAP, PROF_ID_MAP, RARITY_ID_MAP
from .parser import parse_skland_char_wiki, parse_skland_weapon_wiki
from .skland_wiki import wiki_client

# ==================== Catalog cache (name -> ID) ====================

ID_MAP_PATH = WIKI_CACHE_PATH / "id_map.json"
ID_MAP_REFRESH_SECONDS = 86400  # 1 day — normal refresh interval
ID_MAP_RETRY_BACKOFF = 300  # 5 min — min gap between refresh attempts

_id_map: dict | None = None
_id_map_last_attempt: float = 0  # time of last refresh attempt (success or fail)


def _load_id_map() -> dict | None:
    if not ID_MAP_PATH.exists():
        return None
    try:
        raw = ID_MAP_PATH.read_text(encoding="utf-8")
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"[EndWiki] Failed to load id_map: {e}")
        return None


async def _save_id_map(data: dict) -> None:
    try:
        ID_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(ID_MAP_PATH, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"[EndWiki] Failed to save id_map: {e}")


async def _refresh_id_map() -> dict:
    """Rebuild id_map from catalog API (1 request, all items)."""
    logger.info("[EndWiki] Refreshing ID map from catalog...")
    catalog_items = await wiki_client.get_catalog_items(
        sub_type_names={"干员", "武器"}
    )

    items: dict[str, dict] = {}
    for sub_type_name, entries in catalog_items.items():
        for entry in entries:
            item_id = str(entry.get("itemId", ""))
            name = entry.get("name", "")
            brief = entry.get("brief", {})
            cover = brief.get("cover", "")
            sub_type_list = brief.get("subTypeList", [])

            meta: dict = {
                "name": name,
                "sub_type": sub_type_name,
                "cover": cover,
            }
            for st in sub_type_list:
                sid = st.get("subTypeId", "")
                val = st.get("value", "")
                if sid == "10000":
                    meta["rarity_tag"] = val
                elif sid == "10100":
                    meta["attr_tag"] = val
                elif sid == "10200":
                    meta["prof_tag"] = val

            items[item_id] = meta

    data = {"items": items, "fetch_time": time.time()}
    await _save_id_map(data)
    logger.info(f"[EndWiki] ID map refreshed: {len(items)} items")
    return data


async def _try_refresh_id_map() -> bool:
    """Attempt a catalog refresh, honoring retry backoff.

    Returns True only when the in-memory map was successfully replaced.
    """
    global _id_map, _id_map_last_attempt
    now = time.time()
    if (now - _id_map_last_attempt) < ID_MAP_RETRY_BACKOFF:
        return False
    _id_map_last_attempt = now
    try:
        _id_map = await _refresh_id_map()
        return True
    except Exception as e:
        logger.error(f"[EndWiki] Failed to refresh ID map: {e}")
        return False


async def _ensure_id_map() -> dict:
    """Return the name->ID catalog, refreshing if stale."""
    global _id_map

    if _id_map is None:
        _id_map = _load_id_map()

    fetch_time = (_id_map or {}).get("fetch_time", 0)
    if (time.time() - fetch_time) >= ID_MAP_REFRESH_SECONDS:
        await _try_refresh_id_map()

    return _id_map or {}


def _find_item_id(
    id_map: dict, name: str, sub_type: str = "干员"
) -> int | None:
    for item_id_str, meta in id_map.get("items", {}).items():
        if meta.get("name") == name and meta.get("sub_type") == sub_type:
            return int(item_id_str)
    return None


# ==================== Detail cache ====================

DETAIL_EXPIRE_SECONDS = 86400  # 1 day


def _is_detail_expired(cache_path) -> bool:
    if not cache_path.exists():
        return True
    try:
        raw = cache_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        fetch_time = data.get("fetch_time", 0)
        return (time.time() - fetch_time) > DETAIL_EXPIRE_SECONDS
    except Exception:
        return True


# ==================== Public API ====================


async def ensure_list_data() -> WikiListData | None:
    """Build WikiListData from the catalog (for 角色列表/武器列表)."""
    id_map = await _ensure_id_map()
    items = id_map.get("items", {})
    if not items:
        return None

    characters: dict[str, list[CharListEntry]] = {}
    weapons: dict[str, list[WeaponListEntry]] = {}

    for item_id_str, meta in items.items():
        name = meta.get("name", "")
        sub_type = meta.get("sub_type", "")
        cover = meta.get("cover", "")

        if sub_type == "干员":
            rarity = RARITY_ID_MAP.get(meta.get("rarity_tag", ""), 0)
            attribute = ATTR_ID_MAP.get(meta.get("attr_tag", ""), "")
            profession = PROF_ID_MAP.get(meta.get("prof_tag", ""), "")

            entry = CharListEntry(
                name=name,
                rarity=rarity,
                profession=profession,
                attribute=attribute,
                avatar_url=cover,
                wiki_item_id=int(item_id_str),
            )
            characters.setdefault(attribute, []).append(entry)

        elif sub_type == "武器":
            entry_w = WeaponListEntry(
                name=name,
                rarity=0,
                weapon_type="",
                icon_url=cover,
                wiki_item_id=int(item_id_str),
            )
            weapons.setdefault("武器", []).append(entry_w)

    for attr in characters:
        characters[attr].sort(key=lambda x: x.rarity, reverse=True)

    return WikiListData(
        characters=characters,
        weapons=weapons,
        gacha=[],
        fetch_time=time.time(),
    )


async def get_char_wiki(
    char_name: str, force_refresh: bool = False
) -> CharWiki | None:
    """Get character wiki detail from Skland wiki API."""
    id_map = await _ensure_id_map()
    item_id = _find_item_id(id_map, char_name, "干员")
    if item_id is None:
        # Unknown name — may be a newly launched character; try a fresh pull
        if await _try_refresh_id_map():
            item_id = _find_item_id(_id_map or {}, char_name, "干员")
        if item_id is None:
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
            logger.warning(f"[EndWiki] Cache load failed {char_name}: {e}")

    item = await wiki_client.get_item_info(item_id)
    if not item:
        return None

    wiki = parse_skland_char_wiki(item)
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
        logger.warning(f"[EndWiki] Cache save failed {char_name}: {e}")

    return wiki


async def get_weapon_wiki(
    weapon_name: str, force_refresh: bool = False
) -> WeaponWiki | None:
    """Get weapon wiki detail from Skland wiki API."""
    id_map = await _ensure_id_map()
    item_id = _find_item_id(id_map, weapon_name, "武器")
    if item_id is None:
        if await _try_refresh_id_map():
            item_id = _find_item_id(_id_map or {}, weapon_name, "武器")
        if item_id is None:
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
            logger.warning(f"[EndWiki] Cache load failed {weapon_name}: {e}")

    item = await wiki_client.get_item_info(item_id)
    if not item:
        return None

    wiki = parse_skland_weapon_wiki(item)
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
        logger.warning(f"[EndWiki] Cache save failed {weapon_name}: {e}")

    return wiki
