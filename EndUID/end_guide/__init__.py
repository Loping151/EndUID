from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger

from ..utils import CHAR_NAME_PATTERN
from ..utils.alias_map import resolve_alias_entry
from .guide import get_guide

sv_guide = SV("End攻略")


@sv_guide.on_regex(
    rf"^(?P<name>{CHAR_NAME_PATTERN})(?:攻略|gl)$",
    block=True,
)
async def guide_handler(bot: Bot, ev: Event):
    name = (ev.regex_dict or {}).get("name", "").strip()
    if not name:
        return

    logger.info(f"[EndGuide] 查询攻略: {name}")

    # Resolve alias
    resolved = resolve_alias_entry(name)
    if resolved:
        real_name = resolved[0]
        logger.info(f"[EndGuide] 别名解析: {name} -> {real_name}")
    else:
        real_name = name

    await get_guide(bot, ev, real_name, original_name=name)
