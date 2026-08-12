import io
from typing import List, Tuple, Union, Optional
from pathlib import Path
from datetime import datetime

from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from ..utils.path import PLAYER_PATH, PILE_CACHE_PATH
from ..utils.tips import TIP_NO_CRED
from ..utils.util import hide_uid
from ..utils.api.model import WarEchoStage, WarEchoSeason, WarEchoDungeon, WarEchoesResponse
from ..utils.api.requests import end_api
from ..utils.player_store import read_player_json, write_player_json
from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..utils.database.models import EndUser

TEXTURE_PATH = Path(__file__).parent / "texture2d"
TEMPLATE_PATH = Path(__file__).parents[1] / "templates"
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

# 难度展示（残酷红色样式，同 skland）
DIFF_META = {
    "normal": {"label": "普通", "cls": "normal"},
    "hard":   {"label": "困难", "cls": "hard"},
    "cruel":  {"label": "残酷", "cls": "cruel"},
}

# 赛季/轮换评级图片（同 skland xu 逻辑）
RATING_IMG = {
    "empty": "rate_empty.png",
    "d": "rate_d.png",
    "c": "rate_c.png",
    "b": "rate_b.png",
    "a": "rate_a.png",
    "s": "rate_s.png",
    "sPlus": "rate_splus.png",
}


def _rating_key(stars: int, all_plus: bool) -> str:
    n = max(0, min(round(stars), 9))
    if n == 9:
        return "sPlus" if all_plus else "s"
    if n >= 7:
        return "a"
    if n >= 5:
        return "b"
    if n >= 3:
        return "c"
    if n >= 1:
        return "d"
    return "empty"


def _fmt_date(ts: str) -> str:
    try:
        n = int(ts)
        if n <= 0:
            return ""
        return datetime.fromtimestamp(n).strftime("%Y/%m/%d")
    except Exception:
        return ""


def _fmt_datetime(ts: str) -> str:
    try:
        n = int(ts)
        if n <= 0:
            return ""
        return datetime.fromtimestamp(n).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _fmt_duration(secs: str) -> str:
    """passTs 是通关耗时秒数，转 X分XX秒（同 skland）"""
    try:
        n = int(secs)
        if n <= 0:
            return ""
        m, s = divmod(n, 60)
        return f"{m}分{s:02d}秒"
    except Exception:
        return ""


def compose_page_bg(height: int, width: int = 1280) -> str:
    """page_bg 固定贴顶，超高部分截灰色段上下镜像往下拼（底缘余烬只出现一次）"""
    import base64
    W = width
    base = Image.open(TEXTURE_PATH / "page_bg.png").convert("RGB")
    scale = W / base.width
    top = base.resize((W, round(base.height * scale)))
    # 灰色段（避开底部余烬与顶部暗角）
    gy0, gy1 = round(base.height * 0.30), round(base.height * 0.62)
    grey = base.crop((0, gy0, base.width, gy1)).resize((W, round((gy1 - gy0) * scale)))

    H = max(height, top.height + grey.height)
    out = Image.new("RGB", (W, H), (44, 45, 45))
    out.paste(top, (0, 0))

    overlap = 180
    y = top.height - overlap
    region_h = H - y
    region = Image.new("RGB", (W, region_h))
    flip = False
    ty = 0
    while ty < region_h:
        tile = grey.transpose(Image.FLIP_TOP_BOTTOM) if flip else grey
        region.paste(tile, (0, ty))
        ty += tile.height
        flip = not flip
    mask = Image.new("L", (W, region_h), 255)
    # 延伸灰底从透明渐变到不透明；此前反向渐变会在 top.height 处
    # 从 0 突然跳回 255，形成一条明显的横向分界线。
    ramp = Image.linear_gradient("L").resize((1, overlap))
    mask.paste(ramp.resize((W, overlap)), (0, 0))
    out.paste(region, (0, y), mask)

    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _pick_dungeon(stage: WarEchoStage) -> Tuple[str, Optional[WarEchoDungeon]]:
    """取打过的最高难度（同 skland）；都没打过取存在的最高难度用于展示"""
    for key in ("cruel", "hard", "normal"):
        d = getattr(stage, f"{key}Dungeon")
        if d.id and d.isPass:
            return key, d
    for key in ("cruel", "hard", "normal"):
        d = getattr(stage, f"{key}Dungeon")
        if d.id:
            return key, d
    return "", None


async def _build_stage_ctx(stage: WarEchoStage) -> dict:
    from ..end_dungeon.draw_dungeon import _bake_chars
    diff_key, d = _pick_dungeon(stage)
    meta = DIFF_META.get(diff_key, DIFF_META["normal"])

    best_chars_ctx: List[dict] = []
    pass_duration = ""
    pass_date = ""
    is_pass = bool(d and d.isPass)
    if is_pass and d and d.bestRecord and d.bestRecord.chars:
        best_chars_ctx = await _bake_chars(d.bestRecord.chars)
        pass_duration = _fmt_duration(d.bestRecord.passTs)
        pass_date = _fmt_datetime(d.bestRecord.ts)

    star = max(0, min(stage.star, 3))
    star_img = "star_3_plus.png" if (star == 3 and stage.plusTask) else f"star_{star}.png"

    return {
        "name": stage.name or (d.name if d else ""),
        "star": star,
        "plusTask": stage.plusTask,
        "star_img": image_to_base64(TEXTURE_PATH / star_img),
        "isPass": is_pass,
        "diff_label": meta["label"],
        "diff_cls": meta["cls"],
        "bestChars": best_chars_ctx,
        "passDuration": pass_duration,
        "passDate": pass_date,
    }


async def _build_season_ctx(season: WarEchoSeason) -> dict:
    import time
    now = int(time.time())
    try:
        is_active = int(season.startTs or 0) <= now <= int(season.endTs or 0)
    except Exception:
        is_active = False
    weeks: List[dict] = []
    total_stages = 0
    pass_stages = 0
    for wi, w in enumerate(season.weeks):
        stages: List[dict] = []
        for st in w.dungeonGroups:
            sctx = await _build_stage_ctx(st)
            total_stages += 1
            if sctx["isPass"]:
                pass_stages += 1
            stages.append(sctx)
        weeks.append({
            "id": w.id,
            "name": w.name,
            "no": f"{wi + 1:02d}",
            "startDate": _fmt_date(w.startTs),
            "endDate": _fmt_date(w.endTs),
            "stars": w.stars,
            "allPlusTasks": w.allPlusTasks,
            "rating_img": image_to_base64(TEXTURE_PATH / RATING_IMG[_rating_key(w.stars, w.allPlusTasks)]),
            "stages": stages,
        })
    return {
        "id": season.id,
        "name": season.name,
        "startDate": _fmt_date(season.startTs),
        "endDate": _fmt_date(season.endTs),
        "is_active": is_active,
        "stars": season.stars,
        "allPlusTasks": season.allPlusTasks,
        "rating_img": image_to_base64(TEXTURE_PATH / RATING_IMG[_rating_key(season.stars, season.allPlusTasks)]),
        "weeks": weeks,
        "total_stages": total_stages,
        "pass_stages": pass_stages,
    }


async def fetch_war_season(ev: Event, uid: str, season_index: int = 1):
    """获取战争回响数据并选定赛季。成功返回 (season, war, user_record)，失败返回 (None, 错误文案, None)"""
    from ..utils.at_help import ruser_id
    target_user_id = ruser_id(ev)

    _, cred = await end_api.get_ck_result(uid, target_user_id, ev.bot_id)
    if not cred:
        return None, TIP_NO_CRED, None

    user_record = await EndUser.select_end_user(uid, target_user_id, ev.bot_id)
    server_id = user_record.server_id if user_record and user_record.server_id else "1"
    skland_user_id = (
        user_record.skland_user_id
        if user_record and user_record.skland_user_id
        else None
    )

    res = await end_api.get_war_echoes(
        cred, uid, server_id=server_id, user_id=skland_user_id,
        qq_user_id=target_user_id, bot_id=ev.bot_id,
    )
    if not res:
        return None, "获取战争回响详情失败", None
    if res.get("code") != 0:
        return None, f"获取战争回响详情失败: {res.get('message', '未知错误')}", None

    try:
        from ..utils.util import scrub_urls
        await write_player_json(PLAYER_PATH / uid / "war_echoes.json", scrub_urls(res))
    except Exception as e:
        logger.warning(f"[ENDUID·回响] 回响详情写入失败: {e}")

    from ..utils.util import record_group_and_profile
    await record_group_and_profile(ev, uid)

    try:
        war = WarEchoesResponse.model_validate(res).data.warEchoes
    except Exception as e:
        logger.error(f"[ENDUID·回响] 回响详情解析失败: {e}")
        return None, "❌ 解析战争回响详情失败", None

    if not war.seasons:
        return None, "❌ 暂无战争回响数据", None

    selected_index = min(max(season_index, 1), len(war.seasons)) - 1
    season = war.seasons[selected_index]

    # 往期赛季的荣勋也随 seasonId 返回；即使初始响应偶尔带了明细，
    # 仍需按 seasonId 重拉，避免误用当前赛季荣勋。
    needs_season_fetch = (
        selected_index > 0
        or not any(w.dungeonGroups for w in season.weeks)
    )
    if needs_season_fetch and season.id:
        res2 = await end_api.get_war_echoes(
            cred, uid, server_id=server_id, user_id=skland_user_id,
            season_id=season.id, qq_user_id=target_user_id, bot_id=ev.bot_id,
        )
        if not res2:
            return None, "❌ 获取所选赛季的战争回响详情失败", None
        if res2.get("code") != 0:
            return None, (
                "❌ 获取所选赛季的战争回响详情失败: "
                f"{res2.get('message', '未知错误')}"
            ), None
        try:
            war2 = WarEchoesResponse.model_validate(res2).data.warEchoes
            full = next((s for s in war2.seasons if s.id == season.id), None)
            if not full or not any(w.dungeonGroups for w in full.weeks):
                return None, "❌ 所选赛季暂无可用的轮换详情", None
            season = full
            # 保留初次响应的赛季列表用于翻页，只替换所选赛季荣勋。
            war.achieves = war2.achieves
        except Exception as e:
            logger.warning(f"[ENDUID·回响] 赛季 {season.id} 明细解析失败: {e}")
            return None, "❌ 解析所选赛季的战争回响详情失败", None

    return season, war, user_record


async def draw_war_img(
    ev: Event, uid: str, season_index: int = 1,
) -> Union[bytes, str]:
    from ..utils.at_help import get_query_avatar_b64

    season, war, user_record = await fetch_war_season(ev, uid, season_index)
    if season is None:
        return war  # 此时 war 是错误文案

    user_pref = (
        user_record.hide_uid_self_value
        if user_record and user_record.hide_uid_self_value
        else ""
    )
    total_seasons = len(war.seasons)

    base_name = ""
    base_role_id = ""
    base_level = 0
    base_world_level = 0
    base_create_time = ""
    base_avatar_url = ""
    try:
        from ..end_char.draw_card import _format_awaken_time
    except Exception:
        def _format_awaken_time(ts: str) -> str:
            try:
                n = int(ts)
                if n <= 0:
                    return ""
                return datetime.fromtimestamp(n).strftime("%Y-%m-%d")
            except Exception:
                return ""
    try:
        cached = await read_player_json(PLAYER_PATH / uid / "card_detail.json")
        if cached:
            base = cached.get("data", {}).get("detail", {}).get("base", {}) or {}
            base_name = base.get("name", "") or ""
            base_role_id = base.get("roleId", "") or ""
            base_level = base.get("level", 0) or 0
            base_world_level = base.get("worldLevel", 0) or 0
            base_create_time = _format_awaken_time(base.get("createTime", "")) or ""
            base_avatar_url = base.get("avatarUrl", "") or ""
    except Exception as e:
        logger.warning(f"[ENDUID·回响] 基础信息读取失败: {e}")

    avatar_b64 = await get_query_avatar_b64(ev, base_avatar_url)

    season_ctx = await _build_season_ctx(season)
    kv_b64 = ""
    if season.kvImage:
        try:
            kv_b64 = await get_image_b64_with_cache(
                season.kvImage, PILE_CACHE_PATH,
            )
        except Exception as e:
            logger.warning(f"[ENDUID·回响] 赛季KV下载失败 {season.id}: {e}")
    season_ctx["kv_b64"] = kv_b64

    honor_counts = {
        "gold": sum(1 for a in war.achieves if a.star >= 3),
        "silver": sum(1 for a in war.achieves if a.star >= 2),
        "bronze": sum(1 for a in war.achieves if a.star >= 1),
    }
    honors = [
        {
            "count": honor_counts["gold"],
            "icon": image_to_base64(TEXTURE_PATH / "badge_gold.png"),
        },
        {
            "count": honor_counts["silver"],
            "icon": image_to_base64(TEXTURE_PATH / "badge_silver.png"),
        },
        {
            "count": honor_counts["bronze"],
            "icon": image_to_base64(TEXTURE_PATH / "badge_bronze.png"),
        },
    ]

    # 估算卡片高度，背景固定贴顶、灰色段镜像下拼
    est_h = 880 + 300
    for w in season.weeks:
        est_h += 240 + max(len(w.dungeonGroups), 1) * 348
    est_h += 180

    context = {
        "asset_page_bg": compose_page_bg(est_h, width=1170),
        "asset_stage_bg": image_to_base64(TEXTURE_PATH / "stage_bg.png", quality=80),
        "asset_stage_bg_empty": image_to_base64(TEXTURE_PATH / "stage_bg_empty.png", quality=80),
        "asset_cruel_bg": image_to_base64(TEXTURE_PATH / "cruel_bg.png", quality=80),

        "avatar_url": avatar_b64,
        "user_name": base_name or hide_uid(uid, user_pref=user_pref),
        "uid": hide_uid(base_role_id or uid, user_pref=user_pref),
        "user_level": base_level,
        "world_level": base_world_level,
        "create_time": base_create_time,
        "season": season_ctx,
        "honors": honors,
        "season_index": season_index,
        "total_seasons": total_seasons,
    }

    img_bytes = await render_html(end_templates, "end_war_card.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ HTML 渲染失败，请检查渲染环境"
