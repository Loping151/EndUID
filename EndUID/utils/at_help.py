from gsuid_core.models import Event


def ruser_id(ev: Event) -> str:
    """若开启 AtCheck 且消息中 @ 了他人，则以被 @ 用户作为查询对象，否则返回发送者"""
    from ..end_config.config_default import EndConfig

    at_check = EndConfig.get_config("AtCheck").data
    if at_check and ev.at and ev.at != ev.bot_self_id:
        return ev.at
    return ev.user_id


def is_valid_at(ev: Event) -> bool:
    return ev.user_id != ruser_id(ev)


async def get_query_avatar_b64(ev: Event, fallback_url: str = "") -> str:
    """各指令展示头像: 优先被查询者的平台头像(@他人则取被@者, 否则发送者), 回退游戏卡片头像。"""
    from .path import AVATAR_CACHE_PATH
    from .render_utils import get_image_b64_with_cache
    from .util import get_sender_avatar

    if is_valid_at(ev) and ev.bot_id == "onebot" and ev.at:
        url = f"http://q1.qlogo.cn/g?b=qq&nk={ev.at}&s=640"
    else:
        url = get_sender_avatar(ev)

    for u in (url, fallback_url):
        if not u:
            continue
        try:
            b64 = await get_image_b64_with_cache(u, AVATAR_CACHE_PATH)
            if b64:
                return b64
        except Exception:
            pass
    return ""
