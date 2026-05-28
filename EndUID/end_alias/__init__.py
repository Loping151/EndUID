import re
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger

from ..utils.alias_map import (
    resolve_alias_entry,
    load_alias_map,
    save_alias_map,
    get_alias_list,
    set_alias_list,
)
from ..utils.render_utils import render_html, get_image_b64_with_cache, image_to_base64
from ..end_config import PREFIX
from ..utils import CHAR_NAME_PATTERN
from ..utils.path import AVATAR_CACHE_PATH


sv_add_alias = SV("End角色别名", pm=0)
sv_list_alias = SV("End角色别名列表")

TEMPLATE_PATH = Path(__file__).parents[1] / "templates"
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))
TEXTURE_PATH = Path(__file__).parent / "texture2d"


def _local_b64(filename: str, quality: int = 75) -> str:
    return image_to_base64(TEXTURE_PATH / filename, quality=quality)


def _format_alias_list(key: str, entry: dict) -> list[str]:
    display_name = str(entry.get("name", "")).strip() or key
    entry_id = str(entry.get("id", "")).strip()
    aliases = get_alias_list(entry)
    filtered = []
    for alias in aliases:
        if not alias:
            continue
        if alias in {display_name, key, entry_id}:
            continue
        filtered.append(alias)
    return [display_name] + filtered if filtered else [display_name]


async def _render_alias_card(key: str, entry: dict, alias_list: list[str]) -> Optional[bytes]:
    avatar_url_raw = entry.get("avatarSqUrl") or entry.get("avatarRtUrl") or entry.get("illustrationUrl")
    avatar_url = ""
    try:
        if avatar_url_raw:
            avatar_url = await get_image_b64_with_cache(avatar_url_raw, AVATAR_CACHE_PATH)
    except Exception as e:
        logger.warning(f"[ENDUID·别名] 别名卡片图片获取失败: {e}")

    context = {
        "char_name": key,
        "alias_list": alias_list,
        "avatar_url": avatar_url,
        "bg_url": _local_b64("bg.png"),
        "logo_url": _local_b64("logo.png"),
    }

    return await render_html(end_templates, "end_alias_card.html", context)


@sv_add_alias.on_regex(rf"^(?P<action>添加|删除)(?P<name>{CHAR_NAME_PATTERN})别名(?P<aliases>.+)$", block=True)
async def handle_add_alias(bot: Bot, ev: Event):
    action = ev.regex_dict.get("action")
    char_name = ev.regex_dict.get("name")
    raw = ev.regex_dict.get("aliases", "").strip()

    if not char_name or not raw:
        return await bot.send("❌ 参数不足")

    alias_list = [a.strip() for a in re.split(r'[,，\s]+', raw) if a.strip()]
    if not alias_list:
        return await bot.send("❌ 别名不能为空")

    resolved = resolve_alias_entry(char_name)
    if not resolved:
        return await bot.send(f"❌ 未找到角色，请先「{PREFIX}刷新」数据")

    key, _ = resolved
    data = load_alias_map()
    entry = data.get(key)
    if not isinstance(entry, dict):
        return await bot.send(f"❌ 角色数据异常，请先「{PREFIX}刷新」数据")

    display_name = str(entry.get("name", "")).strip() or key
    entry_id = str(entry.get("id", "")).strip()

    msgs = []
    changed = False
    for new_alias in alias_list:
        if action == "添加":
            existing = resolve_alias_entry(new_alias)
            if existing and existing[0] != key:
                msgs.append(f"❌ 别名【{new_alias}】已被角色【{existing[0]}】占用")
                continue
            aliases = get_alias_list(entry)
            if new_alias in aliases or new_alias in {display_name, key, entry_id}:
                msgs.append(f"❌ 别名【{new_alias}】已存在")
                continue
            aliases.append(new_alias)
            set_alias_list(entry, aliases)
            msgs.append(f"✅ 成功为角色【{display_name}】添加别名【{new_alias}】")
            changed = True
        elif action == "删除":
            aliases = get_alias_list(entry)
            if new_alias in {display_name, key, entry_id}:
                msgs.append(f"❌ 别名【{new_alias}】不可删除")
                continue
            if new_alias not in aliases:
                msgs.append(f"❌ 别名【{new_alias}】不存在，无法删除")
                continue
            aliases.remove(new_alias)
            set_alias_list(entry, aliases)
            msgs.append(f"✅ 成功为角色【{display_name}】删除别名【{new_alias}】")
            changed = True

    if changed:
        save_alias_map(data)
    return await bot.send("\n".join(msgs))


@sv_list_alias.on_regex(rf"^(?P<name>{CHAR_NAME_PATTERN})别名(列表)?$", block=True)
async def handle_list_alias(bot: Bot, ev: Event):
    char_name = ev.regex_dict.get("name")
    if not char_name:
        return await bot.send("❌ 参数不足")

    resolved = resolve_alias_entry(char_name)
    if not resolved:
        return await bot.send("❌ 未找到角色")

    key, entry = resolved
    if not isinstance(entry, dict):
        return await bot.send("❌ 角色数据异常")

    alias_list = _format_alias_list(key, entry)
    img_bytes = await _render_alias_card(key, entry, alias_list)
    if img_bytes:
        return await bot.send(img_bytes)

    return await bot.send(f"角色{entry.get('name') or key}别名列表：" + " ".join(alias_list))


@sv_list_alias.on_fullmatch("别名", block=True)
async def handle_all_alias(bot: Bot, ev: Event):
    """Render all character aliases as a single image."""
    from PIL import Image
    import io
    from gsuid_core.utils.image.convert import convert_img

    data = load_alias_map()
    if not data:
        return await bot.send("暂无别名数据")

    chars = []
    for key, entry in sorted(data.items()):
        if not isinstance(entry, dict):
            continue
        aliases = _format_alias_list(key, entry)
        other_aliases = aliases[1:] if len(aliases) > 1 else aliases

        avatar = ""
        avatar_url_raw = (
            entry.get("avatarSqUrl")
            or entry.get("avatarRtUrl")
            or entry.get("illustrationUrl")
        )
        if avatar_url_raw:
            try:
                avatar = await get_image_b64_with_cache(
                    avatar_url_raw, AVATAR_CACHE_PATH
                )
            except Exception:
                pass

        chars.append({
            "name": key,
            "aliases": other_aliases,
            "avatar": avatar,
        })

    bg = _local_b64("bg.png")
    end_logo = _local_b64("end.png")

    context = {
        "chars": chars,
        "total": len(chars),
        "bg": bg,
        "end_logo": end_logo,
    }

    img_bytes = await render_html(
        end_templates, "end_alias_all.html", context
    )
    if img_bytes:
        return await bot.send(
            await convert_img(Image.open(io.BytesIO(img_bytes)))
        )
    return await bot.send("别名表渲染失败")
