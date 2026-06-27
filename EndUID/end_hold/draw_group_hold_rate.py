import io
import re
import time
from datetime import datetime
from typing import Optional, Union

from PIL import Image

from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.path import PLAYER_PATH, AVATAR_CACHE_PATH
from ..utils.player_store import resolve_player_path, read_player_json
from ..utils.render_utils import render_html, image_to_base64, get_image_b64_with_cache
from ..utils.api.model import CardDetailResponse
from ..utils.database.models import EndBind
from .draw_hold_rate import (
    end_templates,
    LOGO_PATH,
    RANK_RARITY,
    POT_MAX,
    FILTER_LABELS,
    _parse_filter,
    _passes_filter,
    _potentials,
)

# 仅统计近 N 天内更新过的本地存档
VALID_DAYS = 90


def _rarity_int(cd) -> int:
    if cd and cd.rarity and cd.rarity.value:
        m = re.search(r"(\d+)", str(cd.rarity.value))
        if m:
            return int(m.group(1))
    return 0


async def _avatar_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        return await get_image_b64_with_cache(url, AVATAR_CACHE_PATH)
    except Exception:
        return ""


def _group_uids(binds) -> dict:
    """uid -> 首个绑定者(同一 uid 去重)"""
    uid_user: dict = {}
    for b in binds:
        for u in (b.uid or "").split("_"):
            if u and u not in uid_user:
                uid_user[u] = b.user_id
    return uid_user


async def _read_valid_chars(uid: str, threshold: float) -> Optional[dict]:
    """近 VALID_DAYS 天内更新过则返回去重后的 {char_id: (name, rarity, potential, avatar)}，否则 None"""
    path = resolve_player_path(PLAYER_PATH / uid / "card_detail.json")
    if path is None:
        return None
    try:
        if path.stat().st_mtime < threshold:
            return None
    except OSError:
        return None

    data = await read_player_json(PLAYER_PATH / uid / "card_detail.json")
    if not data or data.get("code") != 0:
        return None
    try:
        detail = CardDetailResponse.model_validate(data).data.detail
    except Exception as e:
        logger.warning(f"[ENDUID·群持有率] 解析失败 {uid}: {e}")
        return None

    owned: dict = {}
    for char in detail.chars:
        cd = char.charData
        cid = cd.id if cd else ""
        if not cid or cid in owned:
            continue
        rarity = _rarity_int(cd)
        if rarity not in RANK_RARITY:
            continue
        avatar = cd.avatarRtUrl or cd.avatarSqUrl or ""
        owned[cid] = (cd.name or "", rarity, int(char.potentialLevel or 0), avatar)
    return owned


async def draw_group_hold_rate_img(ev: Event) -> Union[bytes, str]:
    group_id = ev.group_id
    if not group_id:
        return "❌ 群持有率仅支持群聊"

    binds = await EndBind.get_group_all_binds(group_id, bot_id=ev.bot_id)
    uid_user = _group_uids(binds)
    if not uid_user:
        return "❌ 本群暂无绑定用户"

    threshold = time.time() - VALID_DAYS * 86400

    # char_id -> {name, rarity, avatar, count, pots:{0..POT_MAX: count}}
    stats: dict = {}
    valid_n = 0
    for uid in uid_user:
        owned = await _read_valid_chars(uid, threshold)
        if owned is None:
            continue
        valid_n += 1
        for cid, (name, rarity, pot, avatar) in owned.items():
            s = stats.get(cid)
            if s is None:
                s = stats[cid] = {
                    "name": name,
                    "rarity": rarity,
                    "avatar": avatar,
                    "count": 0,
                    "pots": {i: 0 for i in range(POT_MAX + 1)},
                }
            s["count"] += 1
            if 0 <= pot <= POT_MAX:
                s["pots"][pot] += 1

    if valid_n == 0:
        return f"❌ 本群近 {VALID_DAYS} 天内无更新的角色数据，先用「卡片」刷新后即可统计"

    flt = _parse_filter(ev.text)

    entries = []
    for cid, s in stats.items():
        if not _passes_filter(flt, s["rarity"], s["name"]):
            continue
        hold_rate = round(s["count"] / valid_n * 100, 2)
        pot_rate = {p: c / valid_n * 100 for p, c in s["pots"].items()}
        entries.append({
            "char_id": cid,
            "name": s["name"],
            "cls": "r6" if s["rarity"] == 6 else "r5",
            "rate": hold_rate,
            "bar_width": min(100, hold_rate),
            "potentials": _potentials(pot_rate),
            "_avatar_url": s["avatar"],
        })

    if not entries:
        return f"❌ 当前筛选「{FILTER_LABELS.get(flt, flt)}」下暂无数据"

    entries.sort(key=lambda x: x["rate"], reverse=True)
    for e in entries:
        e["avatar"] = await _avatar_from_url(e.pop("_avatar_url"))

    logo_b64 = ""
    try:
        logo_b64 = image_to_base64(LOGO_PATH)
    except Exception:
        pass

    context = {
        "entries": entries,
        "title": f"{FILTER_LABELS.get(flt, flt)}群持有率",
        "subtitle": f"群 {group_id} · {valid_n} 人",
        "pot_cols": list(range(POT_MAX + 1)),
        "logo": logo_b64,
        "query_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    img_bytes = await render_html(end_templates, "end_hold_rate.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ HTML 渲染失败，请检查渲染环境"
