def hide_uid(uid, user_pref: str = "") -> str:
    """user_pref: 该 uid 对应 EndUser.hide_uid_self_value, 由 caller 传入。

    "on" 强制隐藏 / "off" 强制不隐藏 / "" 跟随全局 HideUid。
    """
    from ..end_config import EndConfig

    uid_str = str(uid) if uid is not None else ""
    if user_pref == "off":
        return uid_str
    if user_pref != "on":
        if not EndConfig.get_config("HideUid").data:
            return uid_str
    if len(uid_str) < 2:
        return uid_str
    return uid_str[:2] + "*" * 4 + uid_str[-2:]
