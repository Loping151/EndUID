import json
from pathlib import Path
from typing import Dict

from PIL import Image

from gsuid_core.help.model import PluginHelp
from gsuid_core.help.draw_new_plugin_help import get_new_help

from ..end_config import PREFIX
from ..version import EndUID_version

ICON = Path(__file__).parent.parent.parent / "ICON.png"
HELP_DATA = Path(__file__).parent / "help.json"
ICON_PATH = Path(__file__).parent / "icon_path"
TEXT_PATH = Path(__file__).parent / "texture2d"


def get_help_data() -> Dict[str, PluginHelp]:
    with open(HELP_DATA, "r", encoding="utf-8") as file:
        help_content = json.load(file)
    return help_content


plugin_help = get_help_data()


async def get_help(pm: int):
    return await get_new_help(
        plugin_name="EndUID",
        plugin_info={f"v{EndUID_version}": ""},
        plugin_icon=Image.open(ICON).convert("RGBA"),
        plugin_help=plugin_help,
        plugin_prefix=PREFIX,
        help_mode="dark",
        banner_bg=Image.open(TEXT_PATH / "banner_bg.png").convert("RGBA"),
        banner_sub_text="管理员，欢迎回来",
        help_bg=Image.open(TEXT_PATH / "bg.png").convert("RGBA"),
        cag_bg=Image.open(TEXT_PATH / "cag_bg.png").convert("RGBA"),
        item_bg=Image.open(TEXT_PATH / "item.png").convert("RGBA"),
        icon_path=ICON_PATH,
        footer=Image.new("RGBA", (1, 1), (0, 0, 0, 0)),
        enable_cache=False,
        pm=pm,
    )
