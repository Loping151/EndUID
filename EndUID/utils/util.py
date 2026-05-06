def hide_uid(uid, user_pref: str = "") -> str:
    """user_pref: 该 uid 对应 EndUser.hide_uid_self_value, 由 caller 传入。

    "on" 强制隐藏 / "off" 强制不隐藏 / "" 跟随全局 HideUid。
    """
    from ..end_config import EndConfig

    user_pref = user_pref or ""
    uid_str = str(uid) if uid is not None else ""
    if user_pref == "off":
        return uid_str
    if user_pref != "on":
        if not EndConfig.get_config("HideUid").data:
            return uid_str
    if len(uid_str) < 2:
        return uid_str
    return uid_str[:2] + "*" * 4 + uid_str[-2:]


async def get_hide_uid_pref(uid: str, user_id: str, bot_id: str) -> str:
    """读 EndUser.hide_uid_self_value, 没绑定就回空 (走全局 HideUid)。"""

    from .database.models import EndUser
    from .constants import ENDFIELD_GAME_ID

    try:
        user = await EndUser.select_end_user(
            uid,
            user_id,
            bot_id,
            game_id=ENDFIELD_GAME_ID,
        )
        return user.hide_uid_self_value if user else ""
    except Exception:
        return ""
