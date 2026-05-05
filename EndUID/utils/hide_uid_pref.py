"""EndUID 自有的 hide_uid 偏好缓存. EndUser 表独立, 不与 WavesUser 共享。

值: "on" 强制隐藏 / "off" 强制不隐藏 / "" (未存) → 跟随全局 HideUid 配置。
"""
from typing import Dict

from gsuid_core.logger import logger

_PREF_CACHE: Dict[str, str] = {}


def get_pref(uid) -> str:
    return _PREF_CACHE.get(str(uid), "")


def set_pref(uid, value: str) -> None:
    key = str(uid)
    if value:
        _PREF_CACHE[key] = value
    else:
        _PREF_CACHE.pop(key, None)


async def init_from_db() -> None:
    try:
        from .database.models import EndUser
        prefs = await EndUser.get_all_hide_uid_prefs()
        _PREF_CACHE.update(prefs)
        if prefs:
            logger.info(f"[EndUID] 已载入 {len(prefs)} 条 hide_uid 用户偏好")
    except Exception as e:
        logger.warning(f"[EndUID] hide_uid 偏好缓存初始化失败: {e}")
