import io
from pathlib import Path
from typing import Union

from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.utils.image.convert import convert_img
from gsuid_core.logger import logger

from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..utils.alias_map import resolve_alias_entry
from ..utils.path import WIKI_IMG_CACHE, CHAR_CACHE_PATH, AVATAR_CACHE_PATH
from .models import CharWiki, WeaponWiki, WikiListData

TEXTURE_PATH = Path(__file__).parent.parent / "end_char" / "texture2d"
TEMPLATE_PATH = Path(__file__).parent.parent / "templates"

end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))


def _get_property_icon(name: str) -> str:
    if not name:
        return ""
    path = TEXTURE_PATH / f"{name}.png"
    return image_to_base64(path) if path.exists() else ""


def _get_profession_icon(name: str) -> str:
    if not name:
        return ""
    path = TEXTURE_PATH / f"{name}.png"
    return image_to_base64(path) if path.exists() else ""


async def draw_char_wiki(wiki: CharWiki) -> Union[bytes, str]:
    """Render character wiki detail as image."""
    bg = image_to_base64(TEXTURE_PATH / "bg.png")
    end_logo = image_to_base64(TEXTURE_PATH / "end.png")
    property_icon = _get_property_icon(wiki.attribute)
    profession_icon = _get_profession_icon(wiki.profession)

    # Look up character images from alias map (game API cache)
    char_img = ""
    char_avatar = ""
    resolved = resolve_alias_entry(wiki.name)
    if resolved:
        _, entry = resolved
        # Illustration (large portrait)
        illust_url = entry.get("illustrationUrl") or entry.get("avatarRtUrl")
        if illust_url:
            char_img = await get_image_b64_with_cache(
                illust_url, CHAR_CACHE_PATH
            )
        # Avatar (square icon)
        avatar_url = entry.get("avatarSqUrl")
        if avatar_url:
            char_avatar = await get_image_b64_with_cache(
                avatar_url, AVATAR_CACHE_PATH
            )

    context = {
        "wiki": wiki,
        "bg": bg,
        "end_logo": end_logo,
        "property_icon": property_icon,
        "profession_icon": profession_icon,
        "char_img": char_img,
        "char_avatar": char_avatar,
    }

    img_bytes = await render_html(
        end_templates, "end_wiki_char.html", context
    )
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ Wiki 渲染失败"


async def draw_weapon_wiki(wiki: WeaponWiki) -> Union[bytes, str]:
    """Render weapon wiki detail as image."""
    from .fetch import ensure_list_data, get_weapon_entry

    bg = image_to_base64(TEXTURE_PATH / "bg.png")
    end_logo = image_to_base64(TEXTURE_PATH / "end.png")

    # Look up weapon icon from homepage list data
    weapon_img = ""
    list_data = await ensure_list_data()
    if list_data:
        weapon_entry = get_weapon_entry(list_data, wiki.name)
        if weapon_entry and weapon_entry.icon_url:
            weapon_img = await get_image_b64_with_cache(
                weapon_entry.icon_url, WIKI_IMG_CACHE
            )

    context = {
        "wiki": wiki,
        "bg": bg,
        "end_logo": end_logo,
        "weapon_img": weapon_img,
    }

    img_bytes = await render_html(
        end_templates, "end_wiki_weapon.html", context
    )
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ Wiki 渲染失败"


async def draw_char_list(data: WikiListData) -> Union[bytes, str]:
    """Render character list as image."""
    bg = image_to_base64(TEXTURE_PATH / "bg.png")
    end_logo = image_to_base64(TEXTURE_PATH / "end.png")

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
                "property_icon": _get_property_icon(entry.attribute),
                "profession_icon": _get_profession_icon(entry.profession),
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
    return "❌ Wiki 渲染失败"


async def draw_weapon_list(data: WikiListData) -> Union[bytes, str]:
    """Render weapon list as image."""
    bg = image_to_base64(TEXTURE_PATH / "bg.png")
    end_logo = image_to_base64(TEXTURE_PATH / "end.png")

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
    return "❌ Wiki 渲染失败"


async def draw_gacha(data: WikiListData) -> Union[bytes, str]:
    """Render gacha/banner info as image."""
    bg = image_to_base64(TEXTURE_PATH / "bg.png")
    end_logo = image_to_base64(TEXTURE_PATH / "end.png")

    banners = []
    for banner in data.gacha:
        icon_b64 = ""
        if banner.target_icon_url:
            icon_b64 = await get_image_b64_with_cache(
                banner.target_icon_url, WIKI_IMG_CACHE
            )
        banners.append({
            "banner_name": banner.banner_name,
            "banner_type": banner.banner_type,
            "events": banner.events,
            "target_name": banner.target_name,
            "target_icon": icon_b64,
        })

    context = {
        "banners": banners,
        "bg": bg,
        "end_logo": end_logo,
    }

    img_bytes = await render_html(
        end_templates, "end_wiki_gacha.html", context
    )
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ Wiki 渲染失败"
