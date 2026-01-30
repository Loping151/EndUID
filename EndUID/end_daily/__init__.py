from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_end_daily import draw_end_daily_img
from ..end_config import PREFIX
from ..utils.database.models import EndBind

end_daily = SV("End每日")


@end_daily.on_fullmatch((
    "每日",
    "理智",
    "日常",
    "体力",
    "mr",
))
async def send_daily_info_pic(bot: Bot, ev: Event):
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(f"❌ 未绑定终末地账号，请先使用「{PREFIX}绑定」")

    return await bot.send(await draw_end_daily_img(ev, uid))
