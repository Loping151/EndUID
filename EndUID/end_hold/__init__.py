from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_hold_rate import draw_hold_rate_img
from .draw_group_hold_rate import draw_group_hold_rate_img

sv_hold_rate = SV("End持有率")


@sv_hold_rate.on_command(
    ("持有率", "角色持有率", "持有率统计"),
    block=True,
    to_ai="""查询终末地服务器角色持有率统计图(仅统计五星六星)。

当用户问「持有率 / 哪些角色冷门 / 谁持有率最高 / UP 池谁多」时调用。
text 可附 "up"(非常驻六星, 默认) / "全部" / "六" / "五" 进一步筛选。
""",
)
async def handle_hold_rate(bot: Bot, ev: Event):
    await bot.send(await draw_hold_rate_img(ev))


@sv_hold_rate.on_command(
    ("群持有率", "群角色持有率", "群持有率统计"),
    block=True,
    to_ai="""查询本群角色持有率统计图(仅统计五星六星)。

按群绑定统计, 读本地存档, 仅计入近 90 天内更新过的用户。
当用户问「群持有率 / 本群谁多 / 群里谁练得齐」时调用。
text 可附 "up"(非常驻六星, 默认) / "全部" / "六" / "五" 进一步筛选。
""",
)
async def handle_group_hold_rate(bot: Bot, ev: Event):
    await bot.send(await draw_group_hold_rate_img(ev))
