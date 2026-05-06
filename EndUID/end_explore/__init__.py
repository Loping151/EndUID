from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_explore import draw_explore

end_explore_sv = SV("End探索")


@end_explore_sv.on_fullmatch((
    "探索",
    "探索度",
    "ts",
    "tsd",
    "区域探索",
    "地图探索",
))
async def send_explore_info(bot: Bot, ev: Event):
    im = await draw_explore(ev)
    await bot.send(im)
