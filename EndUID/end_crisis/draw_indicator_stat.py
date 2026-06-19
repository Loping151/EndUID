import io
from datetime import datetime
from typing import Union

from PIL import Image

from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from ..utils.api import endapi
from ..utils.render_utils import render_html, get_image_b64_with_cache
from ..utils.path import PILE_CACHE_PATH
from ..end_config import PREFIX
from . import _common as cm
from .draw_crisis import end_templates
from .draw_crisis_info import LEVEL_COLOR


async def draw_indicator_stat_img(ev: Event) -> Union[bytes, str]:
    pq = cm.get_crisis_period_query()
    if pq is None:
        return f"❌ 暂无当期危机合约周期，先用「{PREFIX}危机合约」查询后再试"
    contract_id, cycle_start_ts, act_name = pq

    data = await endapi.get_indicator_stat(contract_id, cycle_start_ts)
    items = (data or {}).get("list") or []
    if not items:
        return "❌ 暂无指标统计数据，多查询几次「危机合约」上传后即可统计"

    max_rate = max((it.get("rate", 0) for it in items), default=0) or 1

    # 按等级分组(同名不同级自然分列), 组内按占比降序
    groups = []
    for lv in (3, 2, 1):
        lv_items = sorted(
            [it for it in items if int(it.get("level") or 0) == lv],
            key=lambda x: x.get("rate", 0), reverse=True,
        )
        if not lv_items:
            continue
        inds = []
        for it in lv_items:
            icon_b64 = ""
            if it.get("icon"):
                try:
                    icon_b64 = await get_image_b64_with_cache(
                        it["icon"], PILE_CACHE_PATH, quality=80, cover_size=(80, 80),
                    )
                except Exception:
                    pass
            rate = round(float(it.get("rate") or 0), 2)
            inds.append({
                "name": it.get("name") or it.get("indicator_id") or "",
                "desc": it.get("desc") or "",
                "icon_b64": icon_b64,
                "rate": rate,
                "bar_width": round(rate / max_rate * 100, 2),
            })
        groups.append({"level": lv, "color": LEVEL_COLOR.get(lv, "#FF7A02"), "inds": inds})

    context = {
        "query_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "asset_grid_tile": cm.res_b64("grid_tile.png"),
        "asset_indicator": cm.crisis_b64("indicator.png"),
        "act_name": act_name,
        "groups": groups,
        "prefix": PREFIX,
    }

    img_bytes = await render_html(end_templates, "end_indicator_stat.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ HTML 渲染失败，请检查渲染环境"
