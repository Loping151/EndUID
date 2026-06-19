import io
from pathlib import Path
from datetime import datetime
from typing import Union

from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from ..utils.api import endapi
from ..utils.render_utils import render_html, get_image_b64_with_cache, image_to_base64
from ..utils.alias_map import get_avatar_by_id
from ..utils.path import AVATAR_CACHE_PATH
from ..end_gacha.draw_gachalogs import STANDARD_CHAR_NAMES

TEMPLATE_PATH = Path(__file__).parents[1] / "templates"
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

LOGO_PATH = Path(__file__).parents[1] / "end_daily" / "texture2d" / "logo.png"

# 仅统计五星六星
RANK_RARITY = (5, 6)
# 潜能等级 0~6
POT_MAX = 6

# 筛选页签 (顺序即展示顺序)
TABS = [("UP", "UP"), ("6", "六星"), ("5", "五星"), ("ALL", "全部")]
FILTER_LABELS = {k: v for k, v in TABS}


def _parse_filter(text: str) -> str:
    t = (text or "").strip().lower()
    if "全" in t or "all" in t:
        return "ALL"
    if "六" in t or "6" in t:
        return "6"
    if "五" in t or "5" in t:
        return "5"
    return "UP"  # 默认: UP(非常驻六星)


def _is_admin(name: str) -> bool:
    return "管理员" in (name or "")


def _passes_filter(flt: str, rarity: int, name: str) -> bool:
    if flt == "UP":
        return rarity == 6 and name not in STANDARD_CHAR_NAMES
    if flt == "6":
        return rarity == 6
    if flt == "5":
        return rarity == 5
    return rarity in RANK_RARITY  # ALL


async def _build_avatar(char_id: str) -> str:
    url = get_avatar_by_id(char_id)
    if not url:
        return ""
    try:
        return await get_image_b64_with_cache(url, AVATAR_CACHE_PATH)
    except Exception:
        return ""


def _potentials(potential_rate: dict) -> list:
    rates = {}
    for k, v in (potential_rate or {}).items():
        try:
            rates[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return [{"seq": i, "rate": round(rates.get(i, 0), 1)} for i in range(POT_MAX + 1)]


async def draw_hold_rate_img(ev: Event) -> Union[bytes, str]:
    data = await endapi.get_hold_rate()
    rows = (data or {}).get("char_hold_rate") or []
    if not rows:
        return "❌ 暂无持有率数据，可能尚无足够样本"

    flt = _parse_filter(ev.text)

    entries = []
    for r in rows:
        rarity = int(r.get("rarity") or 0)
        if rarity not in RANK_RARITY:
            continue
        name = r.get("name") or ""
        if _is_admin(name):
            continue
        if not _passes_filter(flt, rarity, name):
            continue

        hold_rate = round(float(r.get("hold_rate") or 0), 2)
        entries.append({
            "char_id": str(r.get("char_id") or ""),
            "name": name,
            "cls": "r6" if rarity == 6 else "r5",
            "rate": hold_rate,
            "bar_width": min(100, hold_rate),
            "potentials": _potentials(r.get("potential_hold_rate")),
        })

    if not entries:
        return f"❌ 当前筛选「{FILTER_LABELS.get(flt, flt)}」下暂无数据"

    entries.sort(key=lambda x: x["rate"], reverse=True)
    for e in entries:
        e["avatar"] = await _build_avatar(e["char_id"])

    logo_b64 = ""
    try:
        logo_b64 = image_to_base64(LOGO_PATH)
    except Exception:
        pass

    context = {
        "entries": entries,
        "tabs": [{"k": k, "label": label, "on": k == flt} for k, label in TABS],
        "pot_cols": list(range(POT_MAX + 1)),
        "logo": logo_b64,
        "query_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    img_bytes = await render_html(end_templates, "end_hold_rate.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ HTML 渲染失败，请检查渲染环境"
