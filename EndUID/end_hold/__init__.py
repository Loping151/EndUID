from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_hold_rate import draw_hold_rate_img

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
    return await bot.send("样本量不足，请等待更新！")
    await bot.send(await draw_hold_rate_img(ev))
