import io
import json
from pathlib import Path
from typing import Dict, List, Union

import aiofiles
from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.api.model import CardDetailResponse
from ..utils.database.models import EndBind
from ..utils.util import hide_uid
from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..end_config import PREFIX
from ..utils.path import AVATAR_CACHE_PATH, PLAYER_PATH
from ..end_char.draw_card import _format_awaken_time

TEXTURE_PATH = Path(__file__).parent.parent / "end_char" / "texture2d"
TEMPLATE_PATH = Path(__file__).parent.parent / "templates"

end_explore_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))


async def draw_explore(ev: Event) -> Union[bytes, str]:
    from ..utils.at_help import ruser_id, get_at_avatar_b64
    target_user_id = ruser_id(ev)

    uid = await EndBind.get_bound_uid(target_user_id, ev.bot_id)
    if not uid:
        return f"未绑定终末地账号，请先使用「{PREFIX}登录」"

    from ..end_char import refresh_card_data
    success, error_msg = await refresh_card_data(target_user_id, ev.bot_id)
    if not success:
        return error_msg

    save_path = PLAYER_PATH / uid / "card_detail.json"
    try:
        async with aiofiles.open(save_path, "r", encoding="utf-8") as f:
            raw = await f.read()
        data_res = json.loads(raw)
    except Exception as e:
        logger.warning(f"[EndUID] 本地卡片数据读取失败: {e}")
        return f"❌ 本地卡片数据读取失败，请先发送「{PREFIX}刷新」"

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

    at_avatar = await get_at_avatar_b64(ev)
    if at_avatar:
        base_avatar_b64 = at_avatar

    domains: List[Dict] = []
    for d in detail.domain:
        levels: List[Dict] = []
        for lv in d.levels:
            levels.append({
                "levelId": lv.levelId,
                "name": lv.name,
                "trchest": {"count": lv.trchestCount.count, "total": lv.trchestCount.total},
                "puzzle": {"count": lv.puzzleCount.count, "total": lv.puzzleCount.total},
                "blackbox": {"count": lv.blackboxCount.count, "total": lv.blackboxCount.total},
                "equipTrchest": {"count": lv.equipTrchestCount.count, "total": lv.equipTrchestCount.total},
                "piece": {"count": lv.pieceCount.count, "total": lv.pieceCount.total},
            })

        if levels:
            domains.append({
                "domainId": d.domainId,
                "name": d.name,
                "level": d.level,
                "levels": levels,
            })

    domains.sort(key=lambda x: x.get("domainId", ""))

    context = {
        "roleId": hide_uid(base.roleId if base else uid),
        "name": base.name if base and base.name else hide_uid(uid),
        "createTime": _format_awaken_time(base.createTime) if base else "",
        "avatar": base_avatar_b64,
        "level": base.level if base else 0,
        "worldLevel": base.worldLevel if base else 0,
        "domains": domains,
        "bg": image_to_base64(TEXTURE_PATH / "bg.png", quality=75),
        "end_logo": image_to_base64(TEXTURE_PATH / "end.png", quality=75),
    }

    img_bytes = await render_html(
        end_explore_templates, "end_explore.html", context
    )
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))

    return "❌ HTML 渲染失败"
