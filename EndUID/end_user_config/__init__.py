from gsuid_core.sv import SV, get_plugin_available_prefix
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.alias_map import get_alias_display_name, resolve_alias_entry
from ..utils.database.models import EndBind, EndUser
from ..utils.util import get_hide_uid_pref, hide_uid as _mask_uid


GAME_TITLE = "「终末地」"
PREFIX = get_plugin_available_prefix("EndUID")

END_USER_MAP = {
    "体力背景": "stamina_bg",
    "隐藏UID": "hide_uid_self",
}

end_user_config = SV("End用户配置")


async def _send_text(bot: Bot, ev: Event, msg: str):
    at_sender = True if ev.group_id else False
    return await bot.send(
        (" " if at_sender else "") + msg,
        at_sender=at_sender,
    )


async def _set_end_user_value(ev: Event, func: str, uid: str, value: str) -> str:
    field = END_USER_MAP.get(func)
    if not field:
        return f"{GAME_TITLE} 配置项不存在"

    if func == "隐藏UID":
        # value 已是 "on"/"off" (由调度层判定); 落库即可, hide_uid 用 value 即时回显
        await EndUser.update_data_by_data(
            select_data={
                "user_id": ev.user_id,
                "bot_id": ev.bot_id,
                "uid": uid,
            },
            update_data={f"{field}_value": value},
        )
        action = "已开启" if value == "on" else "已关闭"
        return f"{GAME_TITLE} {action}隐藏UID!\nUID[{_mask_uid(uid, user_pref=value)}]"

    if not value:
        masked_uid = _mask_uid(
            uid,
            user_pref=await get_hide_uid_pref(uid, ev.user_id, ev.bot_id),
        )
        await EndUser.update_data_by_data(
            select_data={
                "user_id": ev.user_id,
                "bot_id": ev.bot_id,
                "uid": uid,
            },
            update_data={f"{field}_value": ""},
        )
        return f"{GAME_TITLE} 已清除{func}\n特征码[{masked_uid}]"

    resolved = resolve_alias_entry(value)
    if not resolved:
        return f"{GAME_TITLE} 未找到对应角色，请先「{PREFIX}刷新」更新别名"

    key, entry = resolved
    name = str(entry.get("name", "")).strip() if isinstance(entry, dict) else ""
    raw_value = value.strip()
    store_value = name
    if not store_value:
        if raw_value and not raw_value.isdigit():
            store_value = raw_value
        elif key and not key.isdigit():
            store_value = key
        else:
            store_value = raw_value or key
    await EndUser.update_data_by_data(
        select_data={
            "user_id": ev.user_id,
            "bot_id": ev.bot_id,
            "uid": uid,
        },
        update_data={f"{field}_value": store_value},
    )

    display = get_alias_display_name(store_value) or value
    masked_uid = _mask_uid(
        uid,
        user_pref=await get_hide_uid_pref(uid, ev.user_id, ev.bot_id),
    )
    return f"{GAME_TITLE} 设置成功!\n特征码[{masked_uid}]\n当前{func}:{display}"


@end_user_config.on_prefix("设置", block=True)
async def handle_end_user_config(bot: Bot, ev: Event):
    text = ev.text.strip()

    func = None
    value = ""
    if "体力背景" in text:
        func = "体力背景"
        value = text.replace("体力背景", "").strip()
    elif "隐藏uid" in text.lower():
        func = "隐藏UID"
        # 设置隐藏UID → on; 设置取消隐藏UID → off
        value = "off" if "取消" in text else "on"
    if not func:
        return

    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        msg = f"{GAME_TITLE} 未绑定终末地账号，请先使用「{PREFIX}登录」"
        return await _send_text(bot, ev, msg)

    if func == "隐藏UID":
        # 登录前置: 必须存在该 uid 的 EndUser 行
        end_user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
        if not end_user:
            msg = f"{GAME_TITLE} 当前UID[{_mask_uid(uid)}]未登录终末地, 请先使用「{PREFIX}登录」"
            return await _send_text(bot, ev, msg)

    msg = await _set_end_user_value(ev, func, uid, value)
    return await _send_text(bot, ev, msg)
