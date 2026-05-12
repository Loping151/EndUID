from PIL import Image

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.help.utils import register_help

from .get_help import ICON, get_help
from ..end_config import PREFIX

sv_end_help = SV("End帮助")


@sv_end_help.on_fullmatch(
    ("帮助", "help", "bz"),
    block=True,
    to_ai="""返回 EndUID（明日方舟：终末地）插件的命令帮助图。

当用户问「终末地怎么用 / end 帮助 / end help / 终末地有哪些指令」时调用。
不需要绑定 UID，按用户权限渲染。

Args:
    text: 无需参数。
""",
)
async def send_help_img(bot: Bot, ev: Event):
    await bot.send(await get_help(ev.user_pm))


register_help("EndUID", f"{PREFIX}帮助", Image.open(ICON))
