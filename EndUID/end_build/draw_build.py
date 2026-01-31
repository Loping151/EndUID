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

end_build_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))


async def draw_build(ev: Event) -> Union[bytes, str]:
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return f"❌ 未绑定终末地账号，请先使用「{PREFIX}绑定」"

    save_path = PLAYER_PATH / uid / "card_detail.json"
    if not save_path.exists():
        from ..end_char import refresh_card_data
        success, error_msg = await refresh_card_data(ev.user_id, ev.bot_id)
        if not success:
            return error_msg

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

    char_name_map: Dict[str, str] = {}
    char_avatar_url_map: Dict[str, str] = {}
    for char in detail.chars:
        if char.charData and char.id:
            char_name_map[char.id] = char.charData.name
            if char.charData.avatarSqUrl:
                char_avatar_url_map[char.id] = char.charData.avatarSqUrl

    needed_char_ids: set = set()
    for d in detail.domain:
        for s in d.settlements:
            if s.officerCharIds:
                for cid in s.officerCharIds.split(","):
                    cid = cid.strip()
                    if cid and cid in char_avatar_url_map:
                        needed_char_ids.add(cid)
    for room in detail.spaceShip.rooms:
        for c in room.chars:
            cid = c.get("charId", "") if isinstance(c, dict) else ""
            if cid and cid in char_avatar_url_map:
                needed_char_ids.add(cid)

    char_avatar_b64: Dict[str, str] = {}
    for cid in needed_char_ids:
        url = char_avatar_url_map[cid]
        b64 = await get_image_b64_with_cache(url, AVATAR_CACHE_PATH)
        if b64:
            char_avatar_b64[cid] = b64

    base_avatar_b64 = ""
    if base and base.avatarUrl:
        base_avatar_b64 = await get_image_b64_with_cache(
            base.avatarUrl, AVATAR_CACHE_PATH
        )

    domains: List[Dict] = []
    for d in detail.domain:
        total_puzzle = 0
        total_trchest = 0
        total_piece = 0
        total_blackbox = 0

        collections = []
        for c in d.collections:
            total_puzzle += c.puzzleCount
            total_trchest += c.trchestCount
            total_piece += c.pieceCount
            total_blackbox += c.blackboxCount
            collections.append({
                "levelId": c.levelId,
                "puzzleCount": c.puzzleCount,
                "trchestCount": c.trchestCount,
                "pieceCount": c.pieceCount,
                "blackboxCount": c.blackboxCount,
            })

        settlements = []
        for s in d.settlements:
            officers = []
            if s.officerCharIds:
                for cid in s.officerCharIds.split(","):
                    cid = cid.strip()
                    if cid:
                        officers.append({
                            "charId": cid,
                            "name": char_name_map.get(cid, cid[:8]),
                            "avatar": char_avatar_b64.get(cid, ""),
                        })
            settlements.append({
                "id": s.id,
                "name": s.name,
                "level": s.level,
                "remainMoney": s.remainMoney,
                "officers": officers,
            })

        domains.append({
            "domainId": d.domainId,
            "name": d.name,
            "level": d.level,
            "settlements": settlements,
            "collections": collections,
            "totalPuzzle": total_puzzle,
            "totalTrchest": total_trchest,
            "totalPiece": total_piece,
            "totalBlackbox": total_blackbox,
        })

    domains.sort(key=lambda x: x.get("domainId", ""))

    rooms: List[Dict] = []
    for room in detail.spaceShip.rooms:
        room_chars = []
        for c in room.chars:
            char_id = c.get("charId", "") if isinstance(c, dict) else ""
            phys = c.get("physicalStrength", 0) if isinstance(c, dict) else 0
            fav = c.get("favorability", 0) if isinstance(c, dict) else 0
            room_chars.append({
                "charId": char_id,
                "charName": char_name_map.get(char_id, char_id[:8] if char_id else ""),
                "avatar": char_avatar_b64.get(char_id, ""),
                "physicalStrength": round(phys, 1),
                "favorability": fav,
            })

        rooms.append({
            "id": room.id,
            "type": room.type,
            "level": room.level,
            "chars": room_chars,
        })

    context = {
        "roleId": base.roleId if base else uid,
        "name": base.name if base and base.name else uid,
        "createTime": _format_awaken_time(base.createTime) if base else "",
        "avatar": base_avatar_b64,
        "charNum": base.charNum if base else 0,
        "weaponNum": base.weaponNum if base else 0,
        "docNum": base.docNum if base else 0,
        "level": base.level if base else 0,
        "worldLevel": base.worldLevel if base else 0,
        "domains": domains,
        "spaceShip": {
            "rooms": rooms,
        },
        "bg": image_to_base64(TEXTURE_PATH / "bg.png"),
        "end_logo": image_to_base64(TEXTURE_PATH / "end.png"),
    }

    img_bytes = await render_html(
        end_build_templates, "end_build.html", context
    )
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))

    return "❌ HTML 渲染失败"