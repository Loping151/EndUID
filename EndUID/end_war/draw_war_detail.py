import io
import re
import time
from typing import List, Union
from pathlib import Path

from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from .draw_war import (
    DIFF_META,
    _fmt_date,
    compose_page_bg,
    fetch_war_season,
)
from ..utils.path import PILE_CACHE_PATH
from ..utils.render_utils import (
    render_html,
    get_image_b64_with_cache,
)

TEMPLATE_PATH = Path(__file__).parents[1] / "templates"
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))


def _fmt_feature(text: str) -> List[str]:
    """feature 富文本转纯文本条目：去 <@..> 标签、{k:v} 取 v、按行拆条、去 - 前缀"""
    if not text:
        return []
    t = re.sub(r"<@[^>]+>", "", text).replace("</>", "")
    t = re.sub(r"\{[^{}:]+:([^{}]*)\}", r"\1", t)
    items = []
    for line in re.split(r"\n+", t):
        line = re.sub(r"^\s*[-–—•]\s*", "", line).strip()
        if line:
            items.append(line)
    return items


async def _build_stage_detail_ctx(stage) -> dict:
    """单关信息：只取存在的最高难度，不重复展示玩家通关记录。"""
    diff_key = "normal"
    info_d = stage.normalDungeon
    for key in ("cruel", "hard", "normal"):
        dungeon = getattr(stage, f"{key}Dungeon")
        if dungeon.id:
            diff_key = key
            info_d = dungeon
            break
    meta = DIFF_META.get(diff_key, DIFF_META["normal"])

    enemies_ctx: List[dict] = []
    for e in info_d.enemies or []:
        icon_b64 = ""
        if e.imageUrl:
            try:
                icon_b64 = await get_image_b64_with_cache(
                    e.imageUrl, PILE_CACHE_PATH, quality=85, cover_size=(160, 160),
                )
            except Exception as ex:
                logger.warning(f"[ENDUID·回响信息] 敌人图标失败 {e.id}: {ex}")
        enemies_ctx.append({
            "name": e.name,
            "level": e.level,
            "desc": e.desc,
            "ability": e.ability,
            "icon_b64": icon_b64,
        })

    return {
        "name": stage.name or info_d.name,
        "diff_label": meta["label"],
        "diff_cls": meta["cls"],
        "recommendLevel": info_d.recommendLevel,
        "challengeTarget": info_d.additionalChallengeTarget or "",
        "features": _fmt_feature(info_d.feature),
        "desc": info_d.desc or "",
        "enemies": enemies_ctx,
    }


def _pick_week(season, week_index: int):
    """week_index=0 取当前进行中的轮换（无则最近一期），否则取第 N 期"""
    weeks = season.weeks or []
    if not weeks:
        return None, 0
    if week_index >= 1:
        idx = min(week_index, len(weeks))
        return weeks[idx - 1], idx
    now = int(time.time())
    for i, w in enumerate(weeks):
        try:
            if int(w.startTs or 0) <= now <= int(w.endTs or 0):
                return w, i + 1
        except Exception:
            continue
    return weeks[-1], len(weeks)


async def draw_war_detail_img(
    ev: Event, uid: str, week_index: int = 0, season_index: int = 1,
) -> Union[bytes, str]:
    season, war, _ = await fetch_war_season(ev, uid, season_index)
    if season is None:
        return war  # 此时 war 是错误文案

    week, week_no = _pick_week(season, week_index)
    if week is None:
        return "❌ 本赛季暂无轮换数据"

    stages_ctx = [await _build_stage_detail_ctx(st) for st in week.dungeonGroups]

    # 估算高度：页头 + 每关最高难度的机制与敌方情报
    est_h = 180
    for s in stages_ctx:
        est_h += 190 + max(len(s["features"]), 1) * 38
        if s["enemies"]:
            est_h += 80 + ((len(s["enemies"]) + 1) // 2) * 150
    est_h += 120

    context = {
        "asset_page_bg": compose_page_bg(est_h),

        "season_name": season.name,
        "week_name": week.name,
        "week_no": week_no,
        "week_total": len(season.weeks),
        "week_start": _fmt_date(week.startTs),
        "week_end": _fmt_date(week.endTs),
        "stages": stages_ctx,
    }

    img_bytes = await render_html(end_templates, "end_war_detail.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ HTML 渲染失败，请检查渲染环境"
