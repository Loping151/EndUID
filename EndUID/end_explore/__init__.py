from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_explore import draw_explore

end_explore_sv = SV("End探索")


@end_explore_sv.on_fullmatch(
    (
        "探索",
        "探索度",
        "ts",
        "tsd",
        "区域探索",
        "地图探索",
    ),
    to_ai="""查询自己终末地账号在各区域的地图探索进度。

当用户问「终末地探索 / 地图探索度 / end 探索 / 我的终末地探索进度」时调用。
需绑定终末地 UID。

Args:
    text: 无需参数。
""",
)
async def send_explore_info(bot: Bot, ev: Event):
    im = await draw_explore(ev)
    await bot.send(im)
