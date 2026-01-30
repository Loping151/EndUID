from gsuid_core.sv import SV, get_plugin_available_prefix
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.alias_map import get_alias_display_name, resolve_alias_entry
from ..utils.database.models import EndBind, EndUser


GAME_TITLE = "[终末地]"
PREFIX = get_plugin_available_prefix("EndUID")

END_USER_MAP = {
    "体力背景": "stamina_bg",
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

    if not value:
        await EndUser.update_data_by_data(
            select_data={
                "user_id": ev.user_id,
                "bot_id": ev.bot_id,
                "uid": uid,
            },
            update_data={f"{field}_value": ""},
        )
        return f"{GAME_TITLE} 已清除{func}\n特征码[{uid}]"

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
    return f"{GAME_TITLE} 设置成功!\n特征码[{uid}]\n当前{func}:{display}"


@end_user_config.on_prefix("设置", block=True)
async def handle_end_user_config(bot: Bot, ev: Event):
    text = ev.text.strip()

    func = None
    value = ""
    if "体力背景" in text:
        func = "体力背景"
        value = text.replace("体力背景", "").strip()
    if not func:
        return

    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        msg = f"{GAME_TITLE} 未绑定终末地账号，请先使用「{PREFIX}绑定」"
        return await _send_text(bot, ev, msg)

    msg = await _set_end_user_value(ev, func, uid, value)
    return await _send_text(bot, ev, msg)
