import re

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_war import draw_war_img
from ..utils.tips import TIP_NOT_BOUND
from .draw_war_detail import draw_war_detail_img
from ..utils.database.models import EndBind

end_war_sv = SV("End战争回响", priority=5)
end_war_detail_sv = SV("End战争回响信息", priority=3)


@end_war_detail_sv.on_command(
    (
        "战争回响信息",
        "回响信息",
        "回响详情",
        "战争回响详情",
        "hxxx",
        "hxxq",
    ),
    block=True,
    to_ai="""查询战争回响轮换的关卡机制与敌方情报（不含玩家队伍记录）。

当用户问「回响信息 / 回响详情」时调用。默认当前轮换；一个数字选第 N
轮换，两个数字依次选择第 S 赛季、第 N 轮换。需绑定终末地 UID。
""",
)
async def send_war_detail(bot: Bot, ev: Event):
    from ..utils.at_help import ruser_id
    uid = await EndBind.get_bound_uid(ruser_id(ev), ev.bot_id)
    if not uid:
        return await bot.send(TIP_NOT_BOUND)

    nums = re.findall(r"\d+", ev.text or "")
    # 无数字=当前轮换；一个数字=第N轮换；两个数字=第S赛季第N轮换
    week_index = int(nums[-1]) if nums else 0
    season_index = int(nums[0]) if len(nums) >= 2 else 1

    return await bot.send(await draw_war_detail_img(ev, uid, week_index, season_index))


@end_war_sv.on_command(
    (
        "战争回响",
        "回响",
        "zzhx",
        "echo",
        "we",
        "hx",
    ),
    to_ai="""查询自己终末地账号的战争回响（赛季制常驻挑战）进度。

当用户问「战争回响 / 回响」时调用，末尾数字选赛季（1=最新）。
「回响信息 / 回响详情」用于查看各关最高难度的机制与敌方情报。
需绑定终末地 UID。

Args:
    text: 可选数字，第 N 新的赛季，默认 1（当前/最新赛季）。
""",
)
async def send_war_info(bot: Bot, ev: Event):
    from ..utils.at_help import ruser_id
    uid = await EndBind.get_bound_uid(ruser_id(ev), ev.bot_id)
    if not uid:
        return await bot.send(TIP_NOT_BOUND)

    from ..end_crisis._common import parse_trailing_number
    season_index = parse_trailing_number(ev.text or "") or 1

    return await bot.send(await draw_war_img(ev, uid, season_index))
