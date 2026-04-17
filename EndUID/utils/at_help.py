from typing import Optional

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


async def get_at_avatar_b64(ev: Event) -> Optional[str]:
    """@ 查询时返回被 @ 用户的 QQ 头像 base64（仅 onebot 平台），否则返回 None"""
    if not is_valid_at(ev):
        return None
    if ev.bot_id != "onebot" or not ev.at:
        return None
    try:
        from .path import AVATAR_CACHE_PATH
        from .render_utils import get_image_b64_with_cache

        url = f"http://q1.qlogo.cn/g?b=qq&nk={ev.at}&s=640"
        return await get_image_b64_with_cache(url, AVATAR_CACHE_PATH)
    except Exception:
        return None
