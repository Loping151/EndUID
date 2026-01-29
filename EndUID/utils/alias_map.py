import json
from typing import Any, Dict, Iterable, Optional, Tuple

from gsuid_core.logger import logger

from .path import MAP_PATH


AliasEntry = Dict[str, Any]
AliasMap = Dict[str, AliasEntry]


def _normalize(text: str) -> str:
    return text.strip().lower()


def _ensure_map_file():
    if MAP_PATH.exists():
        return
    try:
        MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        MAP_PATH.write_text("{}", encoding="utf-8")
    except Exception as e:
        logger.warning(f"[EndUID] 初始化 map.json 失败: {e}")


def _load_alias_map() -> AliasMap:
    _ensure_map_file()
    if not MAP_PATH.exists():
        return {}
    try:
        raw = MAP_PATH.read_text(encoding="utf-8")
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"[EndUID] 读取 map.json 失败: {e}")
        return {}


def _save_alias_map(data: AliasMap) -> None:
    try:
        MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        MAP_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"[EndUID] 写入 map.json 失败: {e}")


def _get_alias_list(entry: AliasEntry) -> list[str]:
    aliases = entry.get("alias", [])
    if not isinstance(aliases, list):
        return []
    return [str(a) for a in aliases if a]


def _set_alias_list(entry: AliasEntry, aliases: Iterable[str]) -> None:
    entry["alias"] = list(dict.fromkeys([a for a in aliases if a]))


def load_alias_map() -> AliasMap:
    return _load_alias_map()


def save_alias_map(data: AliasMap) -> None:
    _save_alias_map(data)


def get_alias_list(entry: AliasEntry) -> list[str]:
    return _get_alias_list(entry)


def set_alias_list(entry: AliasEntry, aliases: Iterable[str]) -> None:
    _set_alias_list(entry, aliases)


def update_alias_map_from_chars(chars: Iterable[Any]) -> None:
    data = _load_alias_map()
    changed = False

    for char in chars:
        char_data = getattr(char, "charData", None)
        if not char_data:
            continue

        char_id = str(getattr(char_data, "id", "") or getattr(char, "id", "")).strip()
        char_name = str(getattr(char_data, "name", "") or "").strip()
        if not char_name:
            continue
        avatar_sq = getattr(char_data, "avatarSqUrl", "") or ""
        avatar_rt = getattr(char_data, "avatarRtUrl", "") or ""
        illustration_url = getattr(char_data, "illustrationUrl", "") or ""

        entry = data.get(char_name)
        if not isinstance(entry, dict):
            migrated = None
            if char_id:
                for key, value in data.items():
                    if isinstance(value, dict) and str(value.get("id", "")).strip() == char_id:
                        migrated = key
                        entry = value
                        break
            if migrated:
                if migrated != char_name:
                    data[char_name] = entry
                    data.pop(migrated, None)
                    changed = True
            else:
                entry = {}
                data[char_name] = entry
                changed = True

        alias_list = _get_alias_list(entry)
        if char_id and char_id not in alias_list:
            alias_list.append(char_id)
            changed = True

        _set_alias_list(entry, alias_list)

        if entry.get("name") != char_name:
            entry["name"] = char_name
            changed = True

        if char_id and entry.get("id") != char_id:
            entry["id"] = char_id
            changed = True

        if avatar_sq and entry.get("avatarSqUrl") != avatar_sq:
            entry["avatarSqUrl"] = avatar_sq
            changed = True

        if avatar_rt and entry.get("avatarRtUrl") != avatar_rt:
            entry["avatarRtUrl"] = avatar_rt
            changed = True

        if illustration_url and entry.get("illustrationUrl") != illustration_url:
            entry["illustrationUrl"] = illustration_url
            changed = True

        preferred_url = avatar_rt or illustration_url or avatar_sq
        if preferred_url and entry.get("url") != preferred_url:
            entry["url"] = preferred_url
            changed = True

    if changed:
        _save_alias_map(data)


def resolve_alias_entry(value: str) -> Optional[Tuple[str, AliasEntry]]:
    if not value:
        return None

    data = _load_alias_map()
    if value in data:
        return value, data[value]

    normalized = _normalize(value)

    for key, entry in data.items():
        aliases = [key] + _get_alias_list(entry)
        name = str(entry.get("name", "")).strip()
        if name:
            aliases.append(name)
        entry_id = str(entry.get("id", "")).strip()
        if entry_id:
            aliases.append(entry_id)
        for alias in aliases:
            if normalized == _normalize(alias):
                return key, entry

    for key, entry in data.items():
        aliases = [key] + _get_alias_list(entry)
        name = str(entry.get("name", "")).strip()
        if name:
            aliases.append(name)
        entry_id = str(entry.get("id", "")).strip()
        if entry_id:
            aliases.append(entry_id)
        for alias in aliases:
            alias_norm = _normalize(alias)
            if alias_norm and (normalized in alias_norm or alias_norm in normalized):
                return key, entry

    return None


def get_alias_url(value: str) -> Optional[str]:
    resolved = resolve_alias_entry(value)
    if not resolved:
        return None
    _, entry = resolved
    url = entry.get("avatarRtUrl") or entry.get("illustrationUrl") or entry.get("url") or entry.get("avatarSqUrl")
    return str(url).strip() if url else None


def get_alias_display_name(value: str) -> Optional[str]:
    resolved = resolve_alias_entry(value)
    if not resolved:
        return None
    key, entry = resolved
    name = str(entry.get("name", "")).strip()
    if name:
        return name
    return key
