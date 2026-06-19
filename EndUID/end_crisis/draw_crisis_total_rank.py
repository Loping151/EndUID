import io
from datetime import datetime
from typing import List, Union

from PIL import Image

from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from ..utils.api import endapi
from ..utils.render_utils import render_html, get_image_b64_with_cache
from ..utils.alias_map import get_avatar_by_id
from ..utils.database.models import EndBind
from ..utils.path import AVATAR_CACHE_PATH
from ..end_config import PREFIX
from . import _common as cm
from .draw_crisis import end_templates

PAGE_SIZE = 20
MAX_PAGE = 50


async def _bake_team(team) -> List[str]:
    out = []
    for c in team or []:
        url = get_avatar_by_id(c.get("char_id", ""), prefer="sq")
        b64 = ""
        if url:
            try:
                b64 = await get_image_b64_with_cache(url, AVATAR_CACHE_PATH)
            except Exception:
                pass
        out.append(b64)
    return out


async def draw_crisis_total_rank_img(ev: Event, page: int = 1) -> Union[bytes, str]:
    pq = cm.get_crisis_period_query()
    if pq is None:
        return f"❌ 暂无当期危机合约周期，先用「{PREFIX}危机合约」查询后再试"
    contract_id, cycle_start_ts, act_name = pq

    self_end_id = await EndBind.get_bound_uid(ev.user_id, ev.bot_id) or ""

    page = max(1, min(page, MAX_PAGE))
    data = await endapi.get_crisis_rank(contract_id, cycle_start_ts, page, PAGE_SIZE, self_end_id)
    items = (data or {}).get("list") or []
    if not items:
        if page > 1:
            return "❌ 该页无数据"
        return "❌ 暂无危机合约总排行数据，查询「危机合约」后即可上榜"

    async def _make_row(it: dict) -> dict:
        avatar_b64 = ""
        if it.get("avatar"):
            try:
                avatar_b64 = await get_image_b64_with_cache(it["avatar"], AVATAR_CACHE_PATH)
            except Exception:
                pass
        return {
            "rank": it.get("rank", 0),
            "avatar_b64": avatar_b64,
            "nickname": it.get("name") or "管理员",
            "alias": it.get("alias_name") or "",
            "uid": it.get("end_id") or "",
            "count": it.get("indicator_count", 0),
            "duration": cm.fmt_duration(str(it.get("pass_ts", 0))) or "--:--",
            "chars": await _bake_team(it.get("team")),
            "is_self": bool(it.get("is_self")),
        }

    rows = [await _make_row(it) for it in items]

    # 自身不在当前页时, 末尾补上自己的排名(与群排行一致)
    self_row = None
    self_data = (data or {}).get("self")
    if self_data and not any(r["is_self"] for r in rows):
        self_row = await _make_row(self_data)
        self_row["is_self"] = True

    context = {
        "query_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "asset_grid_tile": cm.res_b64("grid_tile.png"),
        "asset_clock": cm.crisis_b64("clock.png"),
        "asset_score_success": cm.crisis_b64("score_success.png"),
        "act_name": act_name,
        "rows": rows,
        "self_row": self_row,
        "page": page,
        "prefix": PREFIX,
    }

    img_bytes = await render_html(end_templates, "end_crisis_total_rank.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ HTML 渲染失败，请检查渲染环境"
