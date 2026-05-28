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
from ..utils.util import get_hide_uid_pref, hide_uid
from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..end_config import PREFIX
from ..utils.path import AVATAR_CACHE_PATH, PLAYER_PATH
from .draw_char_card import end_templates

# 资源路径
TEXTURE_PATH = Path(__file__).parent / "texture2d"


# texture2d/ 中已有的 icon（来源 end_wiki/constants.py ATTR_ID_MAP / PROF_ID_MAP）：
#   属性：灼热 / 电磁 / 寒冷 / 自然 / 物理
#   职业：近卫 / 术师 / 突击 / 先锋 / 重装 / 辅助
# 新属性/职业上线时补对应 {name}.png 即可，找不到静默返回 ""
def _get_texture_icon(name: str) -> str:
    if not name:
        return ""
    path = TEXTURE_PATH / f"{name}.png"
    return image_to_base64(path) if path.exists() else ""


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
    from ..utils.at_help import ruser_id, get_at_avatar_b64
    target_user_id = ruser_id(ev)

    uid = await EndBind.get_bound_uid(target_user_id, ev.bot_id)
    if not uid:
        return f"未绑定终末地账号，请先使用「{PREFIX}登录」"
    user_pref = await get_hide_uid_pref(uid, target_user_id, ev.bot_id)

    from . import refresh_card_data
    success, error_msg = await refresh_card_data(target_user_id, ev.bot_id)
    if not success:
        return error_msg

    save_path = PLAYER_PATH / uid / "card_detail.json"
    try:
        async with aiofiles.open(save_path, "r", encoding="utf-8") as f:
            raw = await f.read()
        data_res = json.loads(raw)
    except Exception as e:
        logger.warning(f"[ENDUID·角色卡片] 本地卡片数据读取失败: {e}")
        return f"❌ 本地卡片数据读取失败，请先发送「{PREFIX}刷新」"

    if data_res.get("code") != 0:
        msg = data_res.get("message", "未知错误")
        return f"❌ 查询失败: {msg}"

    try:
        detail = CardDetailResponse.model_validate(data_res).data.detail
    except Exception as e:
        logger.error(f"[ENDUID·角色卡片] 卡片详情解析失败: {e}")
        return "❌ 角色数据解析失败"

    base = detail.base

    achieve_count = detail.achieve.count if detail.achieve else 0

    ether_total = 0
    trchest_total = 0
    piece_total = 0
    domain_level = 0
    for d in detail.domain:
        if d.level > domain_level:
            domain_level = d.level
        for c in d.collections:
            ether_total += c.puzzleCount
            trchest_total += c.trchestCount
            piece_total += c.pieceCount

    base_avatar_b64 = ""
    if base and base.avatarUrl:
        base_avatar_b64 = await get_image_b64_with_cache(
            base.avatarUrl, AVATAR_CACHE_PATH
        )

    at_avatar = await get_at_avatar_b64(ev)
    if at_avatar:
        base_avatar_b64 = at_avatar

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
                "property_icon": _get_texture_icon(property_value),
                "profession_icon": _get_texture_icon(profession_value),
            }
        )

    context = {
        "roleId": hide_uid(
            base.roleId if base else uid,
            user_pref=user_pref,
        ),
        "name": base.name if base and base.name else hide_uid(
            uid,
            user_pref=user_pref,
        ),
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
        "achieveCount": achieve_count,
        "etherTotal": ether_total,
        "trchestTotal": trchest_total,
        "pieceTotal": piece_total,
        "domainLevel": domain_level,
        "chars": chars,
        "bg": image_to_base64(TEXTURE_PATH / "bg.png", quality=75),
        "end_logo": image_to_base64(TEXTURE_PATH / "end.png", quality=75),
    }

    img_bytes = await render_html(end_templates, "end_card.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))

    return "❌ HTML 渲染失败"
