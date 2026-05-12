from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_end_daily import draw_end_daily_img
from ..end_config import PREFIX
from ..utils.database.models import EndBind

end_daily = SV("End每日")


@end_daily.on_fullmatch(
    (
        "每日",
        "理智",
        "日常",
        "体力",
        "mr",
    ),
    to_ai="""查询自己终末地账号的每日体力/理智、日常任务、签到进度。

当用户问「终末地体力 / 终末地理智 / end 每日 / 我的终末地日常」时调用。
需绑定终末地 UID。

Args:
    text: 无需参数。
""",
)
async def send_daily_info_pic(bot: Bot, ev: Event):
    from ..utils.at_help import ruser_id
    uid = await EndBind.get_bound_uid(ruser_id(ev), ev.bot_id)
    if not uid:
        return await bot.send(f"未绑定终末地账号，请先使用「{PREFIX}登录」")

    return await bot.send(await draw_end_daily_img(ev, uid))
