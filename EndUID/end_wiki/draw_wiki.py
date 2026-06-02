import io
import re
from pathlib import Path
from typing import Union

from PIL import Image
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from gsuid_core.utils.image.convert import convert_img

from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..utils.alias_map import resolve_alias_entry
from ..utils.path import (
    WIKI_IMG_CACHE, CHAR_CACHE_PATH, AVATAR_CACHE_PATH, SKILL_CACHE_PATH,
)
from .models import CharWiki, WeaponWiki, WikiListData

TEXTURE_PATH = Path(__file__).parent.parent / "end_char" / "texture2d"
TEMPLATE_PATH = Path(__file__).parent.parent / "templates"

end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))


def _highlight_numbers(text: str) -> str:
    """Wrap numbers (including decimals and %) in highlight spans."""
    return re.sub(
        r"(\d+\.?\d*%?)",
        r'<span class="hl-num">\1</span>',
        text,
    )


end_templates.filters["hl_num"] = lambda s: Markup(_highlight_numbers(s))


def _stat_value_only(text: str) -> str:
    """'智识+156' → '+156'。"""
    m = re.search(r"[+\-]?\d[\d.]*%?", text)
    return m.group(0) if m else text


end_templates.filters["stat_num"] = _stat_value_only


# 共用 end_char/texture2d/ 下的 icon（详见 end_wiki/constants.py ATTR_ID_MAP / PROF_ID_MAP）：
#   属性：灼热 / 电磁 / 寒冷 / 自然 / 物理
#   职业：近卫 / 术师 / 突击 / 先锋 / 重装 / 辅助
# 新属性/职业上线时补对应 {name}.png 即可，找不到静默返回 ""
def _get_texture_icon(name: str) -> str:
    if not name:
        return ""
    path = TEXTURE_PATH / f"{name}.png"
    return image_to_base64(path) if path.exists() else ""


# 角色按元素着色，未知元素回退 Endfield 黄
ELEMENT_COLORS = {
    "灼热": "#ff7a3c",
    "寒冷": "#4fb6ff",
    "电磁": "#e0c84a",
    "自然": "#6fd98a",
    "物理": "#cfd6e0",
}


async def draw_char_wiki(wiki: CharWiki) -> Union[bytes, str]:
    """Render character wiki detail as image."""
    bg = image_to_base64(TEXTURE_PATH / "bg.png", quality=75)
    end_logo = image_to_base64(TEXTURE_PATH / "end.png", quality=75)
    property_icon = _get_texture_icon(wiki.attribute)
    profession_icon = _get_texture_icon(wiki.profession)
    accent_color = ELEMENT_COLORS.get(wiki.attribute, "#ffe600")

    char_img = ""
    char_avatar = ""

    # 1) Try Skland wiki illustration (from extraInfo)
    if wiki.illustration_url:
        char_img = await get_image_b64_with_cache(
            wiki.illustration_url, CHAR_CACHE_PATH
        )

    # 2) Fallback: alias map (game API cache)
    if not char_img:
        resolved = resolve_alias_entry(wiki.name)
        if resolved:
            _, entry = resolved
            illust_url = entry.get("illustrationUrl") or entry.get(
                "avatarRtUrl"
            )
            if illust_url:
                char_img = await get_image_b64_with_cache(
                    illust_url, CHAR_CACHE_PATH
                )
            avatar_url = entry.get("avatarSqUrl")
            if avatar_url:
                char_avatar = await get_image_b64_with_cache(
                    avatar_url, AVATAR_CACHE_PATH
                )

    # Download and cache skill icons → base64
    for skill in wiki.skills:
        if skill.icon_url:
            b64 = await get_image_b64_with_cache(
                skill.icon_url, SKILL_CACHE_PATH
            )
            if b64:
                skill.icon_url = b64

    context = {
        "wiki": wiki,
        "bg": bg,
        "end_logo": end_logo,
        "property_icon": property_icon,
        "profession_icon": profession_icon,
        "char_img": char_img,
        "char_avatar": char_avatar,
        "accent_color": accent_color,
    }

    img_bytes = await render_html(
        end_templates, "end_wiki_char.html", context
    )
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "Wiki 渲染失败"


RARITY_COLORS = {
    6: "#ff9d3a",
    5: "#c084fc",
    4: "#4a9eff",
    3: "#4a9eff",
}


async def draw_weapon_wiki(wiki: WeaponWiki) -> Union[bytes, str]:
    """Render weapon wiki detail as image."""
    bg = image_to_base64(TEXTURE_PATH / "bg.png", quality=75)
    end_logo = image_to_base64(TEXTURE_PATH / "end.png", quality=75)

    # Weapon image from catalog cover
    weapon_img = ""
    if wiki.cover_url:
        weapon_img = await get_image_b64_with_cache(
            wiki.cover_url, WIKI_IMG_CACHE
        )

    rarity_color = RARITY_COLORS.get(wiki.rarity, "#888")

    # Collect all entry IDs that need catalog resolution
    entry_ids: set[str] = set()
    for sr in wiki.skill_ranks:
        if sr.recommended_gem_id:
            entry_ids.add(sr.recommended_gem_id)
    for bt in wiki.breakthroughs:
        for mat in bt.materials:
            entry_ids.add(mat.item_id)

    # Resolve names/covers from catalog (single cached call)
    entry_lookup: dict[str, dict] = {}
    if entry_ids:
        from .skland_wiki import wiki_client

        # Fetch ALL catalog items at once (cached by wiki_client)
        all_catalog = await wiki_client.get_catalog_items()
        for entries in all_catalog.values():
            for e in entries:
                eid = str(e.get("itemId", ""))
                if eid in entry_ids:
                    entry_lookup[eid] = e

    # Build gems list (deduplicated)
    gem_ids = set()
    gems: list[dict] = []
    for sr in wiki.skill_ranks:
        gid = sr.recommended_gem_id
        if gid and gid not in gem_ids:
            gem_ids.add(gid)
            entry = entry_lookup.get(gid)
            if entry:
                gem_cover = ""
                cover_url = entry.get("brief", {}).get("cover", "")
                if cover_url:
                    gem_cover = await get_image_b64_with_cache(
                        cover_url, WIKI_IMG_CACHE
                    )
                gems.append({
                    "name": entry.get("name", "").strip(),
                    "cover": gem_cover,
                })

    # Resolve breakthrough material names/covers
    for bt in wiki.breakthroughs:
        for mat in bt.materials:
            entry = entry_lookup.get(mat.item_id)
            if entry:
                mat.name = entry.get("name", "").strip()
                cover_url = entry.get("brief", {}).get("cover", "")
                if cover_url:
                    mat.cover_url = await get_image_b64_with_cache(
                        cover_url, WIKI_IMG_CACHE
                    )

    context = {
        "wiki": wiki,
        "bg": bg,
        "end_logo": end_logo,
        "weapon_img": weapon_img,
        "rarity_color": rarity_color,
        "gems": gems,
    }

    img_bytes = await render_html(
        end_templates, "end_wiki_weapon.html", context
    )
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "Wiki 渲染失败"


async def draw_char_list(data: WikiListData) -> Union[bytes, str]:
    """Render character list as image."""
    bg = image_to_base64(TEXTURE_PATH / "bg.png", quality=75)
    end_logo = image_to_base64(TEXTURE_PATH / "end.png", quality=75)

    groups = {}
    for attr, entries in data.characters.items():
        chars = []
        for entry in entries:
            avatar_b64 = ""
            if entry.avatar_url:
                avatar_b64 = await get_image_b64_with_cache(
                    entry.avatar_url, WIKI_IMG_CACHE
                )
            chars.append({
                "name": entry.name,
                "rarity": entry.rarity,
                "avatar": avatar_b64,
                "property_icon": _get_texture_icon(entry.attribute),
                "profession_icon": _get_texture_icon(entry.profession),
            })
        groups[attr] = chars

    context = {
        "groups": groups,
        "bg": bg,
        "end_logo": end_logo,
        "title": "角色列表",
        "total": sum(len(v) for v in data.characters.values()),
        "list_type": "char",
    }

    img_bytes = await render_html(
        end_templates, "end_wiki_list.html", context
    )
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "Wiki 渲染失败"


async def draw_weapon_list(data: WikiListData) -> Union[bytes, str]:
    """Render weapon list as image."""
    bg = image_to_base64(TEXTURE_PATH / "bg.png", quality=75)
    end_logo = image_to_base64(TEXTURE_PATH / "end.png", quality=75)

    groups = {}
    for wtype, entries in data.weapons.items():
        weapons = []
        for entry in entries:
            icon_b64 = ""
            if entry.icon_url:
                icon_b64 = await get_image_b64_with_cache(
                    entry.icon_url, WIKI_IMG_CACHE
                )
            weapons.append({
                "name": entry.name,
                "rarity": entry.rarity,
                "icon": icon_b64,
            })
        groups[wtype] = weapons

    context = {
        "groups": groups,
        "bg": bg,
        "end_logo": end_logo,
        "title": "武器列表",
        "total": sum(len(v) for v in data.weapons.values()),
        "list_type": "weapon",
    }

    img_bytes = await render_html(
        end_templates, "end_wiki_list.html", context
    )
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "Wiki 渲染失败"


async def draw_gacha(data: WikiListData) -> Union[bytes, str]:
    """Gacha rendering — currently disabled (no longer from bilibili)."""
    return "卡池信息功能维护中"
