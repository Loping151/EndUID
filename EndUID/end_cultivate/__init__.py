from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger

from ..end_config import PREFIX
from ..utils import CHAR_NAME_PATTERN
from .draw_end import draw_end_cultivate_img

end_cultivate = SV("End养成计算")


@end_cultivate.on_regex(
    f"^养成\\s*({CHAR_NAME_PATTERN})$|^({CHAR_NAME_PATTERN})养成$",
    block=True,
    to_ai="""计算终末地干员的养成材料消耗（精英化、技能升级、天赋全部材料），
已有本地面板数据时按当前练度扣除。

Args:
    raw_text: 形如 "养成洛茜" / "洛茜养成"。
""",
)
async def send_cultivate_img(bot: Bot, ev: Event):
    text = (ev.raw_text or "").strip()
    if text.startswith("养成"):
        name = text[2:]
    elif text.endswith("养成"):
        name = text[:-2]
    else:
        return

    name = name.strip()
    if not name:
        return await bot.send(f"请带上干员名，例如「{PREFIX}养成 洛茜」")

    logger.info(f"[ENDUID·养成] 收到养成查询: {name}")
    return await bot.send(await draw_end_cultivate_img(ev, name))
