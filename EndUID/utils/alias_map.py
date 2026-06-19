import json
from typing import Any, Dict, Iterable, Optional, Tuple

from gsuid_core.logger import logger

from pathlib import Path

from .path import MAP_PATH, TEMPLATE_MAP_PATH

WEAPON_MAP_PATH = Path(__file__).parent / "map_weapon.json"


AliasEntry = Dict[str, Any]
AliasMap = Dict[str, AliasEntry]


def _normalize(text: str) -> str:
    return text.strip().lower()


def _merge_alias_maps(map1: AliasMap, map2: AliasMap) -> AliasMap:
    """合并两个别名映射

    Args:
        map1: 第一个映射（通常是模板）
        map2: 第二个映射（通常是数据文件）

    Returns:
        合并后的映射，保留双方的 key，只合并 alias 字段
    """
    all_keys = set(map1.keys()) | set(map2.keys())
    result = {}

    for key in all_keys:
        entry1 = map1.get(key, {})
        entry2 = map2.get(key, {})

        # 优先使用 map2 的完整数据，只合并 alias
        if isinstance(entry2, dict):
            result[key] = entry2.copy()
        elif isinstance(entry1, dict):
            result[key] = entry1.copy()
        else:
            result[key] = {}

        # 合并 alias 字段（去重）
        alias1 = _get_alias_list(entry1) if isinstance(entry1, dict) else []
        alias2 = _get_alias_list(entry2) if isinstance(entry2, dict) else []
        merged_alias = list(dict.fromkeys(alias1 + alias2))  # 保持顺序并去重

        if merged_alias:
            result[key]["alias"] = merged_alias
        elif "alias" not in result[key]:
            result[key]["alias"] = []

    return result


def _ensure_map_file():
    """确保 map.json 存在，并与模板文件合并"""
    try:
        MAP_PATH.parent.mkdir(parents=True, exist_ok=True)

        # 读取模板文件
        template_data = {}
        if TEMPLATE_MAP_PATH.exists():
            try:
                template_raw = TEMPLATE_MAP_PATH.read_text(encoding="utf-8")
                template_data = json.loads(template_raw or "{}")
                if not isinstance(template_data, dict):
                    template_data = {}
            except Exception as e:
                logger.warning(f"[ENDUID·别名映射] 读取模板 map.json 失败: {e}")
                template_data = {}

        # 读取现有的数据文件
        data_map = {}
        if MAP_PATH.exists():
            try:
                data_raw = MAP_PATH.read_text(encoding="utf-8")
                data_map = json.loads(data_raw or "{}")
                if not isinstance(data_map, dict):
                    data_map = {}
            except Exception as e:
                logger.warning(f"[ENDUID·别名映射] 读取 map.json 失败: {e}")
                data_map = {}

        # 合并模板和数据
        merged_data = _merge_alias_maps(template_data, data_map)

        # 保存合并后的数据
        MAP_PATH.write_text(
            json.dumps(merged_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"[ENDUID·别名映射] map.json 已合并更新")
    except Exception as e:
        logger.warning(f"[ENDUID·别名映射] 初始化 map.json 失败: {e}")


def _load_alias_map() -> AliasMap:
    _ensure_map_file()
    if not MAP_PATH.exists():
        return {}
    try:
        raw = MAP_PATH.read_text(encoding="utf-8")
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"[ENDUID·别名映射] 读取 map.json 失败: {e}")
        return {}


def _save_alias_map(data: AliasMap) -> None:
    try:
        MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        MAP_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"[ENDUID·别名映射] 写入 map.json 失败: {e}")


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
        # 将原名作为 alias，而不是 ID
        if char_name and char_name not in alias_list:
            alias_list.append(char_name)
            changed = True

        _set_alias_list(entry, alias_list)

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

    if changed:
        _save_alias_map(data)


_AVATAR_BY_ID_CACHE: Dict[str, Any] = {"mtime": None, "map": {}}


def _avatar_index() -> Dict[str, AliasEntry]:
    """id -> entry 索引，仅在 map.json 变更时重建；只读不触发合并写盘。"""
    try:
        mtime = MAP_PATH.stat().st_mtime if MAP_PATH.exists() else None
    except Exception:
        mtime = None
    if _AVATAR_BY_ID_CACHE["mtime"] != mtime:
        index: Dict[str, AliasEntry] = {}
        try:
            if MAP_PATH.exists():
                raw = json.loads(MAP_PATH.read_text(encoding="utf-8") or "{}")
                for entry in raw.values():
                    cid = str(entry.get("id", "")).strip() if isinstance(entry, dict) else ""
                    if cid:
                        index[cid] = entry
        except Exception as e:
            logger.warning(f"[ENDUID·别名映射] 构建头像索引失败: {e}")
        _AVATAR_BY_ID_CACHE["mtime"] = mtime
        _AVATAR_BY_ID_CACHE["map"] = index
    return _AVATAR_BY_ID_CACHE["map"]


def get_avatar_by_id(char_id: str, prefer: str = "rt") -> str:
    """按角色 ID 从别名映射取头像 URL（与角色面板同一份 map.json）。

    prefer: "rt"=半身像(与危机/丰碑接口 avatarUrl 同图) / "sq"=方头像。
    找不到返回 ""，由调用方回退接口自带 URL。
    """
    cid = str(char_id or "").strip()
    if not cid:
        return ""
    entry = _avatar_index().get(cid)
    if not isinstance(entry, dict):
        return ""
    order = ("avatarRtUrl", "avatarSqUrl") if prefer == "rt" else ("avatarSqUrl", "avatarRtUrl")
    for key in order:
        if entry.get(key):
            return entry[key]
    return ""


def resolve_alias_entry(value: str) -> Optional[Tuple[str, AliasEntry]]:
    if not value:
        return None

    data = _load_alias_map()
    if value in data:
        return value, data[value]

    normalized = _normalize(value)

    # Exact ID match
    for key, entry in data.items():
        entry_id = str(entry.get("id", "")).strip()
        if entry_id and value == entry_id:
            return key, entry

    # Exact alias match (normalized)
    for key, entry in data.items():
        for alias in [key] + _get_alias_list(entry):
            if normalized == _normalize(alias):
                return key, entry

    # Partial alias match (substring)
    for key, entry in data.items():
        for alias in [key] + _get_alias_list(entry):
            alias_norm = _normalize(alias)
            if alias_norm and (normalized in alias_norm or alias_norm in normalized):
                return key, entry

    return None


ADMIN_GENDER_ALIASES: Dict[str, str] = {
    "男管理员": "管理员 (男)",
    "管理员男": "管理员 (男)",
    "男管": "管理员 (男)",
    "女管理员": "管理员 (女)",
    "管理员女": "管理员 (女)",
    "女管": "管理员 (女)",
    "管理员": "管理员 (女)",
}


def resolve_admin_gender(name: str) -> Optional[str]:
    if not name:
        return None
    return ADMIN_GENDER_ALIASES.get(name.strip())


def get_alias_url(value: str) -> Optional[str]:
    resolved = resolve_alias_entry(value)
    if not resolved:
        return None
    _, entry = resolved
    url = entry.get("avatarRtUrl") or entry.get("illustrationUrl") or entry.get("avatarSqUrl")
    return str(url).strip() if url else None


def get_alias_display_name(value: str) -> Optional[str]:
    resolved = resolve_alias_entry(value)
    if not resolved:
        return None
    key, _ = resolved
    return key


def _load_weapon_map() -> dict:
    if not WEAPON_MAP_PATH.exists():
        return {}
    try:
        raw = WEAPON_MAP_PATH.read_text(encoding="utf-8")
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def resolve_weapon_alias(value: str) -> Optional[str]:
    """Resolve weapon alias to weapon name.

    E.g., "莱万汀专武" → "熔铸火焰"
    """
    if not value:
        return None

    data = _load_weapon_map()
    if not data:
        return None

    # Direct key match
    if value in data:
        return value

    normalized = _normalize(value)

    # Exact alias match
    for key, entry in data.items():
        aliases = entry.get("alias", [])
        for alias in [key] + aliases:
            if _normalize(alias) == normalized:
                return key

    # Partial match
    for key, entry in data.items():
        aliases = entry.get("alias", [])
        for alias in [key] + aliases:
            alias_norm = _normalize(alias)
            if alias_norm and (
                normalized in alias_norm or alias_norm in normalized
            ):
                return key

    return None
