from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_build import draw_build

end_build_sv = SV("End基建")


@end_build_sv.on_fullmatch(
    (
        "基建",
        "建设",
        "地区建设",
        "击剑",
        "jj",
    ),
    to_ai="""查询自己终末地账号的地区建设（基建）进度。

当用户问「终末地基建 / end 击剑 / 地区建设 / 我的终末地建设」时调用。
需绑定终末地 UID。

Args:
    text: 无需参数。
""",
)
async def send_build_info(bot: Bot, ev: Event):
    im = await draw_build(ev)
    await bot.send(im)
