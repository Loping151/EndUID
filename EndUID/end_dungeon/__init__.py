from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_dungeon import draw_dungeon_img
from ..end_config import PREFIX
from ..utils.database.models import EndBind

end_dungeon_sv = SV("End影拓丰碑")


@end_dungeon_sv.on_command(
    (
        "影拓丰碑",
        "丰碑",
        "深渊",
        "fb",
    ),
    to_ai="""查询自己终末地账号的影拓丰碑（boss 副本 / indieHard）通关进度。

当用户问「影拓丰碑 / 丰碑」时调用，可选难度参数。
需绑定终末地 UID。

Args:
    text: 可选 "普通" 或 "苦难"。留空默认显示苦难难度。
""",
)
async def send_dungeon_info(bot: Bot, ev: Event):
    from ..utils.at_help import ruser_id
    uid = await EndBind.get_bound_uid(ruser_id(ev), ev.bot_id)
    if not uid:
        return await bot.send(f"未绑定终末地账号，请先使用「{PREFIX}登录」")

    text = (ev.text or "").strip()
    if text in ("普通", "normal", "n"):
        diff = "normal"
    else:
        diff = "hard"

    return await bot.send(await draw_dungeon_img(ev, uid, diff))
