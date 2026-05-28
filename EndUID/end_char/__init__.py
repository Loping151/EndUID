import re
import json
from pathlib import Path

import aiofiles
from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger

from .draw_char_card import draw_char_card
from .draw_card import draw_card
from ..utils.api.requests import end_api
from ..utils.api.model import CardDetailResponse
from ..utils.alias_map import update_alias_map_from_chars
from ..utils.database.models import EndBind, EndUser
from ..utils.util import get_hide_uid_pref, hide_uid
from ..end_config import PREFIX
from ..utils import CHAR_NAME_PATTERN
from ..utils.path import PLAYER_PATH


async def refresh_card_data(user_id: str, bot_id: str) -> tuple[bool, str]:
    """刷新卡片数据

    Args:
        user_id: 用户ID
        bot_id: 机器人ID

    Returns:
        (是否成功, 错误消息或空字符串)
    """
    uid = await EndBind.get_bound_uid(user_id, bot_id)
    if not uid:
        return False, f"未绑定终末地账号，请先使用「{PREFIX}登录」"

    _, cred = await end_api.get_ck_result(uid, user_id, bot_id)
    if not cred:
        return False, f"❌ 未找到可用凭证，请使用「{PREFIX}登录」重新绑定"

    user_record = await EndUser.select_end_user(uid, user_id, bot_id)
    skland_user_id = user_record.skland_user_id if user_record and user_record.skland_user_id else None
    server_id = user_record.server_id if user_record and user_record.server_id else "1"

    res = await end_api.get_card_detail(
        cred,
        uid,
        server_id=server_id,
        user_id=skland_user_id,
        qq_user_id=user_id,
        bot_id=bot_id,
    )
    if not res:
        return False, "❌ 刷新失败：请求卡片详情失败"

    if res.get("code") != 0:
        message = res.get("message", "未知错误")
        return False, f"❌ 刷新失败: {message}"

    try:
        player_dir = PLAYER_PATH / uid
        player_dir.mkdir(parents=True, exist_ok=True)
        save_path = player_dir / "card_detail.json"
        async with aiofiles.open(save_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"[ENDUID·角色] 卡片详情写入失败: {e}")
        return False, "❌ 刷新失败：保存卡片详情失败"

    try:
        detail = CardDetailResponse.model_validate(res).data.detail
        if detail.chars:
            update_alias_map_from_chars(detail.chars)
    except Exception as e:
        logger.warning(f"[ENDUID·角色] 刷新后别名更新失败: {e}")

    return True, ""

sv_char_query = SV("End角色查询")
sv_refresh = SV("End数据刷新")
sv_card = SV("End卡片")

@sv_char_query.on_regex(
    f"^查询\s*({CHAR_NAME_PATTERN})$|^({CHAR_NAME_PATTERN})面板$|^({CHAR_NAME_PATTERN})mb$",
    to_ai="""查询自己终末地某个角色的面板（属性 / 模组 / 武器 / 等级等）。

当用户问「<角色名>面板 / 查询<角色名> / <角色名>mb / 我的终末地某角色练度」时调用。
需绑定终末地 UID。

Args:
    raw_text: 必须形如 "查询<角色名>" / "<角色名>面板" / "<角色名>mb"。
""",
)
async def send_char_card_handler(bot: Bot, ev: Event):
    char_name = ""
    if getattr(ev, "regex_group", None):
        char_name = ev.regex_group[0] or ev.regex_group[1] or ""
        if char_name == "刷新":
            return
    if not char_name:
        match = re.search(f"^查询\s*({CHAR_NAME_PATTERN})$|^({CHAR_NAME_PATTERN})面板$", ev.raw_text)
        if match:
            char_name = match.group(1) or match.group(2) or ""

    if not char_name:
        return

    char_name = char_name.strip()
    logger.info(f"[ENDUID·角色] 收到角色查询请求: {char_name}")

    im = await draw_char_card(ev, char_name)
    await bot.send(im)


@sv_refresh.on_command(
    ("刷新", "更新", "刷新数据", "刷新面板", "更新数据", "upd"),
    block=True,
    to_ai="""刷新自己终末地全部角色面板的缓存数据（实时拉接口）。

当用户问「终末地刷新 / end 更新数据 / 帮我刷新面板 / 更新一下终末地」时调用。
需绑定终末地 UID 和有效 token。

Args:
    text: 无需参数。
""",
)
async def refresh_card_detail_handler(bot: Bot, ev: Event):
    from ..utils.at_help import ruser_id
    at_sender = True if ev.group_id else False
    target_user_id = ruser_id(ev)
    target_uid = await EndBind.get_bound_uid(target_user_id, ev.bot_id)
    success, error_msg = await refresh_card_data(target_user_id, ev.bot_id)
    if not success:
        return await bot.send(error_msg, at_sender=at_sender)

    role_name = ""
    try:
        card_path = PLAYER_PATH / target_uid / "card_detail.json"
        async with aiofiles.open(card_path, "r", encoding="utf-8") as f:
            raw = await f.read()
        detail = CardDetailResponse.model_validate(json.loads(raw)).data.detail
        if detail.base and detail.base.name:
            role_name = detail.base.name
    except Exception as e:
        logger.debug(f"[ENDUID·角色] 读取角色名失败: {e}")

    hide_uid_pref = await get_hide_uid_pref(
        target_uid,
        target_user_id,
        ev.bot_id,
    )
    display_uid = hide_uid(target_uid, user_pref=hide_uid_pref)
    label = f"{role_name}({display_uid})" if role_name else str(display_uid)
    return await bot.send(f"✅ 刷新成功 {label}", at_sender=at_sender)


@sv_card.on_command(
    ("卡片", "kp", "card"),
    block=True,
    to_ai="""查询自己终末地账号的综合信息卡片（管理员等级、好感度、资历等综合面板）。

当用户问「终末地卡片 / end 卡片 / 我的终末地信息 / 我的终末地资料卡」时调用。
需绑定终末地 UID。

Args:
    text: 无需参数。
""",
)
async def send_card_handler(bot: Bot, ev: Event):
    im = await draw_card(ev)
    await bot.send(im)
