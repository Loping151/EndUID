from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_crisis import draw_crisis_img
from .draw_crisis_info import draw_crisis_info_img
from .draw_crisis_detail import draw_crisis_detail_img
from .draw_crisis_rank import draw_crisis_rank_img
from ._common import parse_trailing_number
from ..end_config import PREFIX
from ..utils.tips import TIP_NOT_BOUND
from ..utils.database.models import EndBind

end_crisis_sv = SV("End危机合约")

_HISTORY_PREFIXES = ("历史记录", "历史", "记录")
_INFO_WORDS = ("信息", "指标信息", "指标")
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


# 排行/信息指令需排在主指令之前，避免「危机合约」前缀抢匹配
@end_crisis_sv.on_command(
    ("危机合约排行", "合约排行", "危机排行", "wjhyph", "hyph"),
    block=True,
)
async def crisis_rank_entry(bot: Bot, ev: Event):
    page = parse_trailing_number(ev.text or "") or 1
    return await bot.send(await draw_crisis_rank_img(ev, page))


@end_crisis_sv.on_command(
    ("危机合约信息", "合约信息", "危机信息", "wjhyxx", "hyxx"),
    block=True,
)
async def crisis_info_entry(bot: Bot, ev: Event):
    uid = await _bound_uid(ev)
    if not uid:
        return await _need_login(bot)
    return await bot.send(await draw_crisis_info_img(ev, uid))


@end_crisis_sv.on_command(
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
