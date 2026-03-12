from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_calendar import draw_calendar

end_calendar_sv = SV("End日历")


@end_calendar_sv.on_fullmatch((
    "日历",
    "活动日历",
    "rl",
))
async def send_calendar_info(bot: Bot, ev: Event):
    im = await draw_calendar(ev)
    await bot.send(im)
