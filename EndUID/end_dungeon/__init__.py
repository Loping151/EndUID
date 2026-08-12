import re

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.tips import TIP_NOT_BOUND
from .draw_dungeon import draw_dungeon_img
from ..end_crisis._common import parse_trailing_number
from ..utils.database.models import EndBind

end_dungeon_sv = SV("End影拓丰碑")


@end_dungeon_sv.on_command(
    (
        "影拓丰碑",
        "丰碑",
        "深渊",
        "fb",
        "st",
    ),
    to_ai="""查询自己终末地账号的影拓丰碑（boss 副本 / indieHard）通关进度。

当用户问「影拓丰碑 / 丰碑」时调用，可选难度参数，末尾数字翻页（每页6期）。
需绑定终末地 UID。

Args:
    text: 可选 "普通" 或 "苦难"，加可选页码。如「丰碑2」=第2页。留空默认苦难难度第1页。
""",
)
async def send_dungeon_info(bot: Bot, ev: Event):
    from ..utils.at_help import ruser_id
    uid = await EndBind.get_bound_uid(ruser_id(ev), ev.bot_id)
    if not uid:
        return await bot.send(TIP_NOT_BOUND)

    text = (ev.text or "").strip()
    page = parse_trailing_number(text) or 1
    diff_text = re.sub(r"\d+\s*$", "", text).strip()
    if diff_text in ("普通", "normal", "n"):
        diff = "normal"
    else:
        diff = "hard"

    return await bot.send(await draw_dungeon_img(ev, uid, diff, page))
