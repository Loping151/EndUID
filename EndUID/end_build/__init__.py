from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_build import draw_build

end_build_sv = SV("End基建")


@end_build_sv.on_fullmatch((
    "基建",
    "建设",
    "地区建设",
    "jj",
))
async def send_build_info(bot: Bot, ev: Event):
    im = await draw_build(ev)
    await bot.send(im)
