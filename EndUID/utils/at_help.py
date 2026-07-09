import hashlib

from gsuid_core.models import Event

# qlogo 对无效号/无头像返回 QQ 企鹅占位图(HTTP 200)，按 md5 识别并视为无头像
_QQ_DEFAULT_AVATAR_MD5 = frozenset({
    "bad9cbb852b22fe58e62f3f23c7d63d2",  # q1.qlogo 个人号占位 (s>=140)
    "4700116072a9eba9330a81fbbe49b7d5",  # q1.qlogo 个人号占位 (s=100)
    "bb7257abd317126fc3fd3e29ea118958",  # q.qlogo 官机(qqgroup)占位
})


async def _is_qq_default_avatar_url(url: str) -> bool:
    if not url or "qlogo.cn" not in url:
        return False
    from gsuid_core.utils.image.utils import sget
    try:
        content = (await sget(url)).content
        return hashlib.md5(content).hexdigest() in _QQ_DEFAULT_AVATAR_MD5
    except Exception:
        return False


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

    is_at = is_valid_at(ev) and bool(ev.at)
    if is_at and ev.bot_id == "onebot":
        url = f"http://q1.qlogo.cn/g?b=qq&nk={ev.at}&s=640"
    elif is_at and ev.bot_id == "qqgroup":
        url = f"https://q.qlogo.cn/qqapp/{ev.bot_self_id}/{ev.at}/100"
    elif is_at:
        url = ""  # 其它平台无被@者头像来源, 不回退到发送者
    else:
        url = get_sender_avatar(ev)

    if url and await _is_qq_default_avatar_url(url):
        url = ""  # 企鹅占位视为无头像, 回退游戏卡片头像

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
