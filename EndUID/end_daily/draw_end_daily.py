import io
import time
import random
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import aiofiles
from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.api.requests import end_api
from ..utils.api.model import CardDetailResponse
from ..utils.database.models import EndUser
from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..utils.alias_map import get_alias_url, update_alias_map_from_chars
from ..end_config import PREFIX
from ..utils.path import AVATAR_CACHE_PATH, PILE_CACHE_PATH, PLAYER_PATH

TEMPLATE_PATH = Path(__file__).parents[1] / "templates"
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

TEXTURE_PATH = Path(__file__).parent / "texture2d"

URGENT_COLOR = "#ff4d4f"
COLOR_YELLOW = "#FFCB3B"
COLOR_GREEN = "#52C41A"
COLOR_BLUE = "#4D9CFF"


def _safe_int(value: Optional[str], default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _local_b64(filename: str) -> str:
    return image_to_base64(TEXTURE_PATH / filename)


def _format_recovery_time(
    max_ts: int,
    current_ts: int,
    stamina_cur: int,
    stamina_total: int,
) -> Tuple[str, bool]:
    if stamina_total and stamina_cur >= stamina_total:
        return "已回满", True

    if max_ts <= 0:
        return "未在恢复", False

    now_ts = current_ts if current_ts > 0 else int(time.time())
    delta = max_ts - now_ts
    if delta <= 0:
        return "已回满", True

    urgent = delta < 4 * 3600
    target_time = datetime.fromtimestamp(max_ts)
    now_date = datetime.fromtimestamp(now_ts).date()
    tomorrow = now_date + timedelta(days=1)

    if target_time.date() == now_date:
        text = "今天 " + target_time.strftime("%H:%M")
    elif target_time.date() == tomorrow:
        text = "明天 " + target_time.strftime("%H:%M")
    else:
        text = target_time.strftime("%m.%d %H:%M")

    return text, urgent


async def draw_end_daily_img(ev: Event, uid: str):
    _, cred = await end_api.get_ck_result(uid, ev.user_id, ev.bot_id)
    if not cred:
        return f"❌ 未找到可用凭证，请使用「{PREFIX}登录」重新绑定"

    user_record = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
    server_id = user_record.server_id if user_record and user_record.server_id else "1"
    skland_user_id = user_record.skland_user_id if user_record and user_record.skland_user_id else None
    res = await end_api.get_card_detail(
        cred,
        uid,
        server_id=server_id,
        user_id=skland_user_id,
        qq_user_id=ev.user_id,
        bot_id=ev.bot_id,
    )
    if not res:
        return "获取卡片详情失败"

    if res.get("code") != 0:
        message = res.get("message", "未知错误")
        return f"获取卡片详情失败: {message}"

    try:
        player_dir = PLAYER_PATH / uid
        player_dir.mkdir(parents=True, exist_ok=True)
        save_path = player_dir / "card_detail.json"
        async with aiofiles.open(save_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"[EndUID] 卡片详情写入失败: {e}")

    try:
        detail = CardDetailResponse.model_validate(res).data.detail
    except Exception as e:
        logger.error(f"[EndUID] 卡片详情解析失败: {e}")
        return "❌ 解析卡片详情失败"

    if detail.chars:
        update_alias_map_from_chars(detail.chars)


    base = detail.base
    dungeon = detail.dungeon
    bp_system = detail.bpSystem
    daily_mission = detail.dailyMission

    # 头像
    avatar_url = ""
    if base.avatarUrl:
        avatar_url = await get_image_b64_with_cache(base.avatarUrl, AVATAR_CACHE_PATH)

    # 角色立绘
    pile_url = ""
    if user_record and user_record.stamina_bg_value:
        alias_url = get_alias_url(user_record.stamina_bg_value)
        if alias_url:
            try:
                pile_url = await get_image_b64_with_cache(alias_url, PILE_CACHE_PATH)
            except Exception as e:
                logger.warning(f"[EndUID] 体力背景读取失败: {e}")
                pile_url = ""

    if not pile_url and detail.chars:
        char = random.choice(detail.chars).charData
        if char and char.avatarRtUrl:
            pile_url = await get_image_b64_with_cache(char.avatarRtUrl, PILE_CACHE_PATH)

    bg_url = _local_b64("bg.png")
    logo_url = _local_b64("logo.png")

    if not pile_url:
        pile_url = bg_url
        has_bg = True
    else:
        has_bg = False

    if not avatar_url:
        avatar_url = pile_url

    stamina_cur = _safe_int(dungeon.curStamina)
    stamina_total = _safe_int(dungeon.maxStamina)
    stamina_percent = min(100, (stamina_cur / stamina_total * 100)) if stamina_total else 0
    stamina_color = URGENT_COLOR if stamina_percent > 80 else COLOR_YELLOW

    bp_cur = _safe_int(bp_system.curLevel)
    bp_total = _safe_int(bp_system.maxLevel)
    bp_percent = min(100, (bp_cur / bp_total * 100)) if bp_total else 0

    live_cur = _safe_int(daily_mission.dailyActivation)
    live_total = _safe_int(daily_mission.maxDailyActivation)
    live_percent = min(100, (live_cur / live_total * 100)) if live_total else 0

    current_ts = _safe_int(detail.currentTs)
    max_ts = _safe_int(dungeon.maxTs)
    recovery_text, is_urgent = _format_recovery_time(max_ts, current_ts, stamina_cur, stamina_total)

    context = {
        "has_bg": has_bg,
        "pile_url": pile_url,
        "bg_url": bg_url,
        "logo_url": logo_url,
        "avatar_url": avatar_url,
        "user_name": base.name or uid,
        "uid": base.roleId or uid,
        "user_level": base.level or 0,
        "world_level": base.worldLevel or 0,
        "stamina_icon_url": _local_b64("理智.png"),
        "bp_icon_url": _local_b64("通行证.png"),
        "liveness_icon_url": _local_b64("活跃度.png"),
        "stamina": {
            "cur": stamina_cur,
            "total": stamina_total,
            "percent": stamina_percent,
            "color": stamina_color,
            "recovery_text": recovery_text,
            "urgent": is_urgent,
        },
        "battle_pass": {
            "cur": bp_cur,
            "total": bp_total,
            "percent": bp_percent,
            "color": COLOR_BLUE,
        },
        "liveness": {
            "cur": live_cur,
            "total": live_total,
            "percent": live_percent,
            "color": COLOR_GREEN,
        },
    }

    img_bytes = await render_html(end_templates, "end_daily_card.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))

    return "❌ HTML 渲染失败，请检查渲染环境"
