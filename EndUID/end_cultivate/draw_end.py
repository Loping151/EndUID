import io
from pathlib import Path

from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from ..end_config import PREFIX
from ..end_crisis._common import load_player_base
from ..utils.alias_map import resolve_admin_gender, resolve_alias_entry
from ..utils.api.requests import end_api
from ..utils.database.models import EndBind, EndUser
from ..utils.path import CULTIVATE_CACHE_PATH
from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..utils.resources import attr_icon_b64
from ..utils.tips import TIP_NO_CRED
from .end_source import (
    build_end_result,
    find_char,
    get_char_rules,
    get_material_list,
    get_search_chars,
    get_user_game_data,
    parse_item_count,
)

TEMPLATE_PATH = Path(__file__).parents[1] / "templates"
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

TEXTURE_PATH = Path(__file__).parent / "texture2d"
ICON_CACHE = CULTIVATE_CACHE_PATH / "icon"
ICON_CACHE.mkdir(parents=True, exist_ok=True)


def _local_b64(filename: str) -> str:
    return image_to_base64(TEXTURE_PATH / filename)


def _resolve_name(raw_name: str):
    """角色名解析（同面板）：管理员性别别名 → alias_map → 原文"""
    admin = resolve_admin_gender(raw_name)
    if admin:
        return admin, None
    resolved = resolve_alias_entry(raw_name)
    if resolved:
        return resolved
    return raw_name.strip(), None


async def draw_end_cultivate_img(ev: Event, raw_name: str):
    from ..utils.at_help import ruser_id

    display_name, entry = _resolve_name(raw_name)
    alias_id = str(entry.get("id", "")) if entry else ""

    target_user_id = ruser_id(ev)
    uid = await EndBind.get_bound_uid(target_user_id, ev.bot_id)
    is_self, cred = await end_api.get_ck_result(uid or "", target_user_id, ev.bot_id)
    if not cred:
        return TIP_NO_CRED

    chars = await get_search_chars(cred)
    materials = await get_material_list(cred)
    if not chars or not materials:
        return "❌ 养成计算器数据获取失败，请稍后再试"

    char = find_char(display_name, chars, alias_id)
    if not char:
        return f"未找到干员「{raw_name}」"

    rules = await get_char_rules(cred, char["id"])
    if not rules:
        return f"❌ 获取「{char['name']}」养成规则失败，请稍后再试"

    # 练度与仓库仅用本人凭证同步
    user_char = None
    item_count = None
    if is_self and uid:
        game_data = await get_user_game_data(cred)
        if game_data:
            user_char = (game_data.get("userChars") or {}).get(char["id"])
            item_count = parse_item_count(game_data)

    result = build_end_result(
        char, materials, rules["char"], rules["level_rules"], user_char, item_count
    )
    if not result["summary"]:
        return f"「{char['name']}」已达成养成目标，无需材料"

    async def icon_b64(url: str) -> str:
        if not url:
            return ""
        try:
            return await get_image_b64_with_cache(url, ICON_CACHE)
        except Exception:
            return ""

    icon_cache = {}
    for row in result["summary"]:
        icon_cache[row["id"]] = await icon_b64(row.get("icon_url", ""))
        row["icon"] = icon_cache[row["id"]]
    for section in result["sections"]:
        for row in section["items"]:
            row["icon"] = icon_cache.get(row["id"], "")

    # 通用玩家信息头
    user_record = await EndUser.select_end_user(uid or "", target_user_id, ev.bot_id)
    user_pref = (
        user_record.hide_uid_self_value
        if user_record and user_record.hide_uid_self_value
        else ""
    )
    header = await load_player_base(ev, uid or "", user_pref)
    if not header.get("user_name"):
        header["user_name"] = "未绑定账号"

    if result["synced"] and result["owned"]:
        sync_text = "已读取游戏内练度与材料仓库，计算剩余所需"
    elif result["synced"]:
        sync_text = "未持有该干员，按初始练度计算全部所需；仓库数据已读取"
    elif uid:
        sync_text = f"凭证不可用，按初始练度计算，「{PREFIX}登录」后可同步练度与仓库"
    else:
        sync_text = f"未绑定账号，按初始练度计算，可使用「{PREFIX}登录」绑定"

    context = {
        "name": char["name"],
        "char_avatar": await icon_b64(char.get("avatarSqUrl", "")),
        "prof_icon": attr_icon_b64(result["profession"]),
        "attr_icon": attr_icon_b64(result["property"]),
        "main_bg": _local_b64("main_bg.png"),
        "operator_bg": _local_b64("operator_bg.png"),
        "bottom_bg": _local_b64("bottom_bg.png"),
        "sync_text": sync_text,
        **header,
        **result,
    }

    img_bytes = await render_html(end_templates, "end_cultivate_card.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))

    return "❌ HTML 渲染失败，请检查渲染环境"
