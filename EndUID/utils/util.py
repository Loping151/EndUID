def get_sender_avatar(ev) -> str:
    """取发送者平台头像url(适配器填的 sender.avatar; onebot 回退 QQ 头像)。"""
    sender = ev.sender or {}
    avatar = sender.get("avatar") or ""
    if not avatar and ev.bot_id == "onebot" and str(ev.user_id).isdigit():
        avatar = f"http://q1.qlogo.cn/g?b=qq&nk={ev.user_id}&s=640"
    return avatar


async def record_group_and_profile(ev, uid: str) -> None:
    """查询时把本人 uid 记入当前群(进群即入榜) + 从事件更新平台头像/昵称，供群排行使用。
    仅记录发送者本人（@ 他人查询时跳过）。
    """
    from gsuid_core.logger import logger
    try:
        from .at_help import is_valid_at
        from .database.models import EndBind, EndUser
        if is_valid_at(ev):
            return
        if ev.group_id:
            await EndBind.add_group(ev.user_id, ev.bot_id, ev.group_id)
        sender = ev.sender or {}
        nickname = sender.get("nickname") or sender.get("card") or ""
        avatar = get_sender_avatar(ev)
        kw = {}
        if nickname:
            kw["platform_nickname"] = nickname
        if avatar:
            kw["platform_avatar"] = avatar
        if kw:
            await EndUser.update_data_by_uid(uid, ev.bot_id, **kw)
    except Exception as e:
        logger.warning(f"[ENDUID] 入群榜/资料记录失败: {e}")


def scrub_urls(obj):
    """递归把 http(s) URL 字符串置空，用于落盘存档瘦身(URL 信息量低)"""
    if isinstance(obj, dict):
        return {k: scrub_urls(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_urls(v) for v in obj]
    if isinstance(obj, str) and obj.startswith(("http://", "https://")):
        return ""
    return obj


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
