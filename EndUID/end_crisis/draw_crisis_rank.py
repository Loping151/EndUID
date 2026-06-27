import io
import math
from datetime import datetime
from typing import List, Optional, Union

from PIL import Image

from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.render_utils import render_html, get_image_b64_with_cache
from ..utils.path import AVATAR_CACHE_PATH, PLAYER_PATH
from ..utils.player_store import read_player_json_sync, remove_player_json
from ..utils.api.model import CrisisContractResponse
from ..utils.database.models import EndBind, EndUser
from ..end_config import PREFIX
from . import _common as cm
from .draw_crisis import end_templates

PAGE_SIZE = 20


def _read_game_name(uid: str) -> str:
    """从本地 card_detail.json 取游戏角色名"""
    data = read_player_json_sync(PLAYER_PATH / uid / "card_detail.json")
    if data is None:
        return ""
    try:
        return (data.get("data", {}).get("detail", {}).get("base", {}) or {}).get("name", "") or ""
    except Exception:
        return ""


def _read_local_crisis(uid: str):
    """读本地 players/<uid>/crisis_contract.json，返回 crisisContract 或 None"""
    data = read_player_json_sync(PLAYER_PATH / uid / "crisis_contract.json")
    if data is None:
        return None
    try:
        return CrisisContractResponse.model_validate(data).data.crisisContract
    except Exception as e:
        logger.warning(f"[ENDUID·危机合约排行] 读取本地数据失败 {uid}: {e}")
        return None


async def _bake_char_squares(chars) -> List[str]:
    from ..utils.alias_map import get_avatar_by_id
    out = []
    for c in chars or []:
        url = get_avatar_by_id(c.charId, prefer="sq") or c.avatarUrl
        b64 = ""
        if url:
            try:
                b64 = await get_image_b64_with_cache(url, AVATAR_CACHE_PATH)
            except Exception:
                pass
        out.append(b64)
    return out


async def draw_crisis_rank_img(ev: Event, page: int = 1) -> Union[bytes, str]:
    group_id = ev.group_id
    if not group_id:
        return "❌ 危机合约排行仅支持群聊"

    binds = await EndBind.get_group_all_binds(group_id, bot_id=ev.bot_id)
    # uid -> user_id（同一 uid 取首个绑定者）
    uid_user: dict = {}
    for b in binds:
        for u in (b.uid or "").split("_"):
            if u and u not in uid_user:
                uid_user[u] = b.user_id

    # 当期合约以本地周期文件为准（查询时维护）
    period = cm.get_crisis_period()
    cur_contract = period.get("contract_id") if period else None

    # 收集本地最佳记录；旧周期的记录 json 顺手删除
    entries = []
    for u, user_id in uid_user.items():
        cc = _read_local_crisis(u)
        if not cc or not cc.status.id:
            continue
        if cur_contract and cc.status.id != cur_contract:
            try:
                remove_player_json(PLAYER_PATH / u / "crisis_contract.json")
            except Exception:
                pass
            continue
        best = cc.history.bestRecord
        if not best or not best.id:
            continue
        entries.append({
            "uid": u, "user_id": user_id,
            "contract": cc.status.id, "act_name": cc.status.name,
            "count": best.indicatorCount,
            "passTs": int(best.passTs) if str(best.passTs).isdigit() else 0,
            "chars": best.chars,
        })

    if not entries:
        return f"❌ 本群暂无危机合约数据，先用「{PREFIX}危机合约」查询后即可上榜"

    # 无周期文件时回退到出现最多的 contractId
    if not cur_contract:
        from collections import Counter
        cur_contract = Counter(e["contract"] for e in entries).most_common(1)[0][0]
        entries = [e for e in entries if e["contract"] == cur_contract]

    act_name = (period.get("name") if period else "") \
        or next((e["act_name"] for e in entries), "")

    # 排序：指标总计↓，并列用时↑（用时为 0 视为最大）
    entries.sort(key=lambda e: (-e["count"], e["passTs"] if e["passTs"] > 0 else 10**9))

    total = len(entries)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    page_entries = entries[start:start + PAGE_SIZE]

    self_user = ev.user_id
    self_idx = next((i for i, e in enumerate(entries) if e["user_id"] == self_user), None)

    async def _make_row(e: dict, rank: int, is_self: bool) -> dict:
        user_rec = await EndUser.select_end_user(e["uid"], e["user_id"], ev.bot_id)
        # 头像优先按绑定者 user_id 取 QQ 头像（每人准确，避免共享账号资料串台），再回退库内存档
        avatar_url = ""
        if ev.bot_id == "onebot" and str(e["user_id"]).isdigit():
            avatar_url = f"http://q1.qlogo.cn/g?b=qq&nk={e['user_id']}&s=640"
        if not avatar_url and user_rec and user_rec.platform_avatar:
            avatar_url = user_rec.platform_avatar
        avatar_b64 = ""
        if avatar_url:
            try:
                avatar_b64 = await get_image_b64_with_cache(avatar_url, AVATAR_CACHE_PATH)
            except Exception:
                pass
        # 展示用游戏角色名，平台昵称仅作后备
        nickname = _read_game_name(e["uid"]) \
            or (user_rec.nickname if user_rec and user_rec.nickname else "") \
            or (user_rec.platform_nickname if user_rec and user_rec.platform_nickname else "") \
            or "管理员"
        # UID 按各自的隐藏配置决定是否打码
        pref = user_rec.hide_uid_self_value if user_rec and user_rec.hide_uid_self_value else ""
        return {
            "rank": rank,
            "is_self": is_self,
            "avatar_b64": avatar_b64,
            "nickname": nickname,
            "uid": cm.hide_uid(e["uid"], user_pref=pref),
            "count": e["count"],
            "duration": cm.fmt_duration(str(e["passTs"])) or "--:--",
            "chars": await _bake_char_squares(e["chars"]),
        }

    rows = [
        await _make_row(e, start + i + 1, e["user_id"] == self_user)
        for i, e in enumerate(page_entries)
    ]
    # 自己不在当前页则把自己补到末尾（类似总排行的处理）
    self_row = None
    if self_idx is not None and not (start <= self_idx < start + len(page_entries)):
        self_row = await _make_row(entries[self_idx], self_idx + 1, True)

    context = {
        "group_id": group_id,
        "query_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "self_row": self_row,
        "asset_grid_tile": cm.res_b64("grid_tile.png"),
        "asset_indicator": cm.crisis_b64("indicator.png"),
        "asset_clock": cm.crisis_b64("clock.png"),
        "asset_score_success": cm.crisis_b64("score_success.png"),
        "asset_score_fail": cm.crisis_b64("score_fail.png"),
        "act_name": act_name,
        "rows": rows,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "prefix": PREFIX,
    }

    img_bytes = await render_html(end_templates, "end_crisis_rank.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ HTML 渲染失败，请检查渲染环境"
