from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_calendar import draw_calendar

end_calendar_sv = SV("End日历")


@end_calendar_sv.on_fullmatch(
    (
        "日历",
        "活动日历",
        "rl",
    ),
    to_ai="""查询终末地（明日方舟：终末地）当前进行中的活动 / 卡池日历。

当用户问「终末地日历 / end 活动日历 / 终末地活动 / 终末地卡池」时调用。
不需要绑定 UID，结果是公开的活动期数表。

Args:
    text: 无需参数。
""",
)
async def send_calendar_info(bot: Bot, ev: Event):
    im = await draw_calendar(ev)
    await bot.send(im)
