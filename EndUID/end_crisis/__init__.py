from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_crisis import draw_crisis_img
from .draw_crisis_info import draw_crisis_info_img
from .draw_crisis_detail import draw_crisis_detail_img
from .draw_crisis_rank import draw_crisis_rank_img
from .draw_crisis_total_rank import draw_crisis_total_rank_img
from .draw_indicator_stat import draw_indicator_stat_img
from ._common import parse_trailing_number
from ..end_config import PREFIX
from ..utils.tips import TIP_NOT_BOUND
from ..utils.database.models import EndBind

# 拆分为独立 SV, 用优先级(越小越优先)避免「危机合约/合约/危机」前缀抢匹配:
# 具体指令(总排行/指标/群排行/信息) 优先级 3, 主指令兜底 5, 两侧留空隙便于以后插入
sv_crisis_total = SV("End危机合约总排行", priority=3)
sv_crisis_indicator = SV("End合约指标使用率", priority=3)
sv_crisis_rank = SV("End危机合约群排行", priority=3)
sv_crisis_info = SV("End危机合约信息", priority=3)
sv_crisis = SV("End危机合约", priority=5)

_HISTORY_PREFIXES = ("历史记录", "历史", "记录")
_INFO_WORDS = ("信息", "指标信息", "指标", "环境", "buff", "关卡", "敌人", "环境信息", "buff信息", "关卡信息", "敌人信息")
_BEST_WORDS = ("最佳", "最佳记录", "best")


def _record_index(text: str):
    """解析记录序号：'最佳'/0 → 0(最佳记录)，末尾数字(可带 #)→ N，否则 None"""
    t = (text or "").strip().lstrip("#").strip()
    if t in _BEST_WORDS:
        return 0
    return parse_trailing_number(t)


async def _bound_uid(ev: Event):
    from ..utils.at_help import ruser_id
    return await EndBind.get_bound_uid(ruser_id(ev), ev.bot_id)


async def _need_login(bot: Bot):
    return await bot.send(TIP_NOT_BOUND)


@sv_crisis_total.on_command(
    ("危机合约总排行", "危机合约总排名", "危机总排行", "危机总排名", "合约总排行", "合约总排名",
     "wjhyzph", "wjzph", "hyzph"),
    block=True,
    to_ai="""查询终末地危机合约**总排行**(跨群, 来自上传数据)。

当用户问「危机合约总排行 / 危机总排行」时调用。
按指标数(多优先)、用时(少优先)排名, 带 Bot 别名列。text 末尾数字为翻页。
""",
)
async def crisis_total_rank_entry(bot: Bot, ev: Event):
    page = parse_trailing_number(ev.text or "") or 1
    return await bot.send(await draw_crisis_total_rank_img(ev, page))


@sv_crisis_indicator.on_command(
    ("合约指标使用率", "合约指标统计", "指标使用率", "指标统计", "zbsyl", "zbtj"),
    block=True,
    to_ai="""查询终末地危机合约**指标使用率**(服务器玩家选择各指标的占比)。

当用户问「指标使用率 / 指标统计 / 哪些指标最多人选 / 合约指标统计」时调用。
""",
)
async def indicator_stat_entry(bot: Bot, ev: Event):
    return await bot.send(await draw_indicator_stat_img(ev))


# 群排行: 「群」可有可无, 排行/排名通用 (正则); 末尾数字翻页
@sv_crisis_rank.on_regex(
    r"^(?:危机合约|合约|危机)群?排[行名]\d*$|^(?:wjhyph|wjph|hyph)\d*$",
    block=True,
)
async def crisis_rank_entry(bot: Bot, ev: Event):
    page = parse_trailing_number(ev.raw_text or "") or 1
    return await bot.send(await draw_crisis_rank_img(ev, page))


@sv_crisis_info.on_command(
    ("危机合约信息", "合约信息", "危机信息", "wjhyxx", "wjxx", "hyxx"),
    block=True,
)
async def crisis_info_entry(bot: Bot, ev: Event):
    uid = await _bound_uid(ev)
    if not uid:
        return await _need_login(bot)
    return await bot.send(await draw_crisis_info_img(ev, uid))


@sv_crisis.on_command(
    ("危机合约", "危机", "合约", "wjhy", "wj", "hy"),
    block=True,
    to_ai="""查询自己终末地账号的危机合约（crisis-contract）。

- 「危机合约」：当期最佳记录 + 历史记录概览
- 「危机合约历史」：尽可能多的历史记录
- 「危机合约历史N / 危机合约记录N」：第 N 条历史记录详情（武器/装备/指标）
- 「危机合约信息」：本期指标 buff、关卡与敌人信息
需绑定终末地 UID。
""",
)
async def crisis_entry(bot: Bot, ev: Event):
    uid = await _bound_uid(ev)
    if not uid:
        return await _need_login(bot)

    t = (ev.text or "").strip()

    if t in _INFO_WORDS:
        return await bot.send(await draw_crisis_info_img(ev, uid))

    for p in _HISTORY_PREFIXES:
        if t.startswith(p):
            idx = _record_index(t[len(p):])
            if idx is not None:
                return await bot.send(await draw_crisis_detail_img(ev, uid, idx))
            return await bot.send(await draw_crisis_img(ev, uid, mode="history"))

    idx = _record_index(t)
    if t and idx is not None:
        return await bot.send(await draw_crisis_detail_img(ev, uid, idx))

    return await bot.send(await draw_crisis_img(ev, uid, mode="main"))
