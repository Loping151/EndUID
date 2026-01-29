import io
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Union

import aiofiles
from PIL import Image

from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.api.model import CardDetailResponse
from ..utils.database.models import EndBind
from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..utils.path import AVATAR_CACHE_PATH, PLAYER_PATH
from .draw_char_card import end_templates

# 资源路径
TEXTURE_PATH = Path(__file__).parent / "texture2d"


def _get_property_icon(property_name: str) -> str:
    if not property_name:
        return ""

    icon_map = {
        "物理": TEXTURE_PATH / "物理.png",
        "自然": TEXTURE_PATH / "自然.png",
        "电磁": TEXTURE_PATH / "电磁.png",
        "寒冷": TEXTURE_PATH / "寒冷.png",
        "灼热": TEXTURE_PATH / "灼热.png",
    }

    icon_path = icon_map.get(property_name)
    if not icon_path or not icon_path.exists():
        return ""

    return image_to_base64(icon_path)


def _get_profession_icon(profession_name: str) -> str:
    if not profession_name:
        return ""

    icon_map = {
        "先锋": TEXTURE_PATH / "先锋.png",
        "突击": TEXTURE_PATH / "突击.png",
        "近卫": TEXTURE_PATH / "近卫.png",
        "重装": TEXTURE_PATH / "重装.png",
        "辅助": TEXTURE_PATH / "辅助.png",
        "术师": TEXTURE_PATH / "术师.png",
    }

    icon_path = icon_map.get(profession_name)
    if not icon_path or not icon_path.exists():
        return ""

    return image_to_base64(icon_path)


def _format_awaken_time(ts: str) -> str:
    if not ts:
        return ""
    try:
        ts_int = int(ts)
    except Exception:
        return ""
    if ts_int <= 0:
        return ""
    if ts_int > 10_000_000_000:
        ts_int = ts_int // 1000
    try:
        return datetime.fromtimestamp(ts_int).strftime("%Y-%m-%d")
    except Exception:
        return ""


async def draw_card(ev: Event) -> Union[bytes, str]:
    """绘制终末地卡片（本地数据）"""
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return "❌ 未绑定终末地账号，请先绑定"

    save_path = PLAYER_PATH / uid / "card_detail.json"
    if not save_path.exists():
        # 自动刷新一次
        logger.info(f"[EndUID] 未找到本地数据，自动刷新中...")
        from . import refresh_card_data
        success, error_msg = await refresh_card_data(ev.user_id, ev.bot_id)
        if not success:
            return error_msg

    try:
        async with aiofiles.open(save_path, "r", encoding="utf-8") as f:
            raw = await f.read()
        data_res = json.loads(raw)
    except Exception as e:
        logger.warning(f"[EndUID] 本地卡片数据读取失败: {e}")
        return "❌ 本地卡片数据读取失败，请先发送“刷新/更新”"

    if data_res.get("code") != 0:
        msg = data_res.get("message", "未知错误")
        return f"❌ 查询失败: {msg}"

    try:
        detail = CardDetailResponse.model_validate(data_res).data.detail
    except Exception as e:
        logger.error(f"[EndUID] 卡片详情解析失败: {e}")
        return "❌ 角色数据解析失败"

    base = detail.base

    base_avatar_b64 = ""
    if base and base.avatarUrl:
        base_avatar_b64 = await get_image_b64_with_cache(
            base.avatarUrl, AVATAR_CACHE_PATH
        )

    chars: List[Dict] = []
    for char in detail.chars:
        c_data = char.charData
        if not c_data:
            continue

        avatar_b64 = ""
        if c_data.avatarSqUrl:
            avatar_b64 = await get_image_b64_with_cache(
                c_data.avatarSqUrl, AVATAR_CACHE_PATH
            )

        property_value = c_data.property.value if c_data.property else ""
        profession_value = c_data.profession.value if c_data.profession else ""

        chars.append(
            {
                "name": c_data.name,
                "avatar": avatar_b64,
                "rarity": c_data.rarity.value if c_data.rarity else "",
                "level": char.level,
                "potentialLevel": char.potentialLevel if hasattr(char, "potentialLevel") else 0,
                "property": property_value,
                "profession": profession_value,
                "property_icon": _get_property_icon(property_value),
                "profession_icon": _get_profession_icon(profession_value),
            }
        )

    context = {
        "roleId": base.roleId if base else uid,
        "name": base.name if base and base.name else uid,
        "createTime": _format_awaken_time(base.createTime) if base else "",
        "avatarUrl": base.avatarUrl if base else "",
        "avatar": base_avatar_b64,
        "mainMission": {
            "id": base.mainMission.id if base else "",
            "description": base.mainMission.description if base else "",
        },
        "charNum": base.charNum if base else 0,
        "weaponNum": base.weaponNum if base else 0,
        "docNum": base.docNum if base else 0,
        "level": base.level if base else 0,
        "worldLevel": base.worldLevel if base else 0,
        "chars": chars,
        "bg": image_to_base64(TEXTURE_PATH / "bg.png"),
        "end_logo": image_to_base64(TEXTURE_PATH / "end.png"),
    }

    img_bytes = await render_html(end_templates, "end_card.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))

    return "❌ HTML 渲染失败"
