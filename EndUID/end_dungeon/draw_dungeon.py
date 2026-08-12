import io
from typing import List, Union
from pathlib import Path
from datetime import datetime

from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from ..utils.path import PLAYER_PATH, PILE_CACHE_PATH, AVATAR_CACHE_PATH
from ..utils.tips import TIP_NO_CRED
from ..utils.util import hide_uid
from ..utils.colors import RARITY_COLORS as _RARITY_COLORS
from ..utils.api.model import IndieHardGroup, IndieHardResponse
from ..utils.resources import res_b64, attr_icon_b64, potential_b64
from ..utils.api.requests import end_api
from ..utils.player_store import read_player_json, write_player_json
from ..utils.render_utils import (
    render_html,
    get_image_b64_with_cache,
)
from ..utils.database.models import EndUser

TEMPLATE_PATH = Path(__file__).parents[1] / "templates"
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

PAGE_GROUPS = 6  # 每页最多丰碑期次（大组）数

PROPERTY_ICON = {
    "char_property_physical": "物理",
    "char_property_fire":     "灼热",
    "char_property_pulse":    "电磁",
    "char_property_cryst":    "寒冷",
    "char_property_natural":  "自然",
}

RARITY_COLOR = {f"rarity_{k}": v for k, v in _RARITY_COLORS.items()}
RARITY_COLOR.setdefault("rarity_2", "#888888")
RARITY_COLOR.setdefault("rarity_1", "#666666")


def _fmt_date(ts: str) -> str:
    try:
        n = int(ts)
        if n <= 0:
            return ""
        return datetime.fromtimestamp(n).strftime("%Y.%m.%d")
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
    """passTs 是通关耗时秒数，转 mm:ss"""
    try:
        n = int(secs)
        if n <= 0:
            return ""
        m, s = divmod(n, 60)
        return f"{m:02d}:{s:02d}"
    except Exception:
        return ""


def _property_icon_b64(key: str) -> str:
    return attr_icon_b64(PROPERTY_ICON.get(key, ""))


async def _bake_chars(chars) -> List[dict]:
    out = []
    for c in chars or []:
        avatar_b64 = ""
        # 优先按角色 ID 取头像(与角色面板同一份 map.json)，缺失回退接口 avatarUrl
        from ..utils.alias_map import get_avatar_by_id
        avatar_url = get_avatar_by_id(c.charId) or c.avatarUrl
        if avatar_url:
            try:
                avatar_b64 = await get_image_b64_with_cache(avatar_url, AVATAR_CACHE_PATH)
            except Exception as e:
                logger.warning(f"[ENDUID·关卡] 阵容头像下载失败 {c.charId}: {e}")

        potential_icon = potential_b64(c.potentialLevel)

        out.append({
            "level": c.level,
            "potentialIcon": potential_icon,
            "avatar_b64": avatar_b64,
            "property_icon_b64": _property_icon_b64(c.property.key if c.property else ""),
            "rarity_color": RARITY_COLOR.get(c.rarity.key, "#888") if c.rarity else "#888",
        })
    return out


async def _build_group_ctx(group: IndieHardGroup, diff: str) -> dict:
    dungeons: List[dict] = []
    pass_count = 0
    total_count = 0
    for pair in group.dungeonGroups:
        d = pair.hardDungeon if diff == "hard" else pair.normalDungeon
        if not d.id:
            continue
        total_count += 1
        if d.isPass:
            pass_count += 1

        best_chars_ctx: List[dict] = []
        pass_duration = ""
        pass_date = ""
        if d.bestRecord and d.bestRecord.chars:
            best_chars_ctx = await _bake_chars(d.bestRecord.chars)
            pass_duration = _fmt_duration(d.bestRecord.passTs)
            pass_date = _fmt_datetime(d.bestRecord.ts)

        dungeons.append({
            "name": d.name,
            "isPass": d.isPass,
            "bestChars": best_chars_ctx,
            "passDuration": pass_duration,
            "passDate": pass_date,
        })

    achieve = group.achieve
    medal: dict = {}
    if achieve:
        data = achieve.achievementData
        icon_url = data.platedIcon if achieve.isPlated and data.platedIcon else data.initIcon
        icon_b64 = ""
        if icon_url:
            try:
                icon_b64 = await get_image_b64_with_cache(
                    icon_url, PILE_CACHE_PATH, quality=85, cover_size=(180, 180),
                )
            except Exception as e:
                logger.warning(f"[ENDUID·关卡] 勋章图标失败 {data.id}: {e}")
        medal = {
            "name": (data.name or "").strip(' "“”\''),
            "obtained": achieve.level > 0,
            "isPlated": achieve.isPlated,
            "icon_b64": icon_b64,
        }

    return {
        "id": group.id,
        "name": group.name,
        "pic": group.pic,
        "activityName": group.activityName,
        "isInActivity": group.isInActivity,
        "startDate": _fmt_date(group.activityStartTs),
        "endDate": _fmt_date(group.activityEndTs),
        "pass_count": pass_count,
        "total_count": total_count,
        "percent": (pass_count / total_count * 100) if total_count else 0,
        "dungeons": dungeons,
        "medal": medal,
    }


async def draw_dungeon_img(
    ev: Event, uid: str, diff: str = "hard", page: int = 1,
) -> Union[bytes, str]:
    from ..utils.at_help import ruser_id, get_query_avatar_b64
    target_user_id = ruser_id(ev)

    _, cred = await end_api.get_ck_result(uid, target_user_id, ev.bot_id)
    if not cred:
        return TIP_NO_CRED

    user_record = await EndUser.select_end_user(uid, target_user_id, ev.bot_id)
    user_pref = (
        user_record.hide_uid_self_value
        if user_record and user_record.hide_uid_self_value
        else ""
    )
    server_id = user_record.server_id if user_record and user_record.server_id else "1"
    skland_user_id = (
        user_record.skland_user_id
        if user_record and user_record.skland_user_id
        else None
    )

    res = await end_api.get_indie_hard(
        cred, uid, server_id=server_id, user_id=skland_user_id,
        qq_user_id=target_user_id, bot_id=ev.bot_id,
    )
    if not res:
        return "获取影拓丰碑详情失败"
    if res.get("code") != 0:
        return f"获取影拓丰碑详情失败: {res.get('message', '未知错误')}"

    try:
        from ..utils.util import scrub_urls
        await write_player_json(PLAYER_PATH / uid / "indie_hard.json", scrub_urls(res))
    except Exception as e:
        logger.warning(f"[ENDUID·关卡] 丰碑详情写入失败: {e}")

    from ..utils.util import record_group_and_profile
    await record_group_and_profile(ev, uid)

    try:
        parsed = IndieHardResponse.model_validate(res).data.indieHard
    except Exception as e:
        logger.error(f"[ENDUID·关卡] 丰碑详情解析失败: {e}")
        return "❌ 解析丰碑详情失败"

    groups = parsed.indieHardGroups
    if not groups:
        return "❌ 暂无影拓丰碑数据"

    def _sort_key(g: IndieHardGroup) -> int:
        try:
            return -int(g.activityStartTs or 0)
        except Exception:
            return 0
    groups_sorted = sorted(groups, key=_sort_key)

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
        logger.warning(f"[ENDUID·关卡] 基础信息读取失败: {e}")

    # 头像: 优先平台头像(被查询者), 回退游戏卡片头像
    avatar_b64 = await get_query_avatar_b64(ev, base_avatar_url)

    # 全量汇总只读原始数据；图片和角色资源仅烘焙当前页，避免历史期数增多后
    # 翻一页仍下载、处理全部封面/勋章/队伍。
    total_pass = 0
    total_all = 0
    medals_total = 0
    medals_obtained = 0
    medals_plated = 0
    for g in groups_sorted:
        for pair in g.dungeonGroups:
            d = pair.hardDungeon if diff == "hard" else pair.normalDungeon
            if not d.id:
                continue
            total_all += 1
            if d.isPass:
                total_pass += 1
        if g.achieve:
            medals_total += 1
            if g.achieve.level > 0:
                medals_obtained += 1
            if g.achieve.isPlated:
                medals_plated += 1

    total_pages = max(1, (len(groups_sorted) + PAGE_GROUPS - 1) // PAGE_GROUPS)
    page = min(max(page, 1), total_pages)
    page_source = groups_sorted[(page - 1) * PAGE_GROUPS: page * PAGE_GROUPS]

    page_groups: List[dict] = []
    for g in page_source:
        gctx = await _build_group_ctx(g, diff)
        if g.pic:
            try:
                gctx["pic_b64"] = await get_image_b64_with_cache(
                    g.pic, PILE_CACHE_PATH, quality=85, cover_size=(560, 760),
                )
            except Exception as e:
                logger.warning(f"[ENDUID·关卡] 丰碑封面下载失败 {g.id}: {e}")
                gctx["pic_b64"] = ""
        else:
            gctx["pic_b64"] = ""
        page_groups.append(gctx)

    context = {
        "asset_grid_tile": res_b64("grid_tile.png"),

        "diff": diff,
        "diff_label": "苦难" if diff == "hard" else "普通",
        "diff_label_en": "HARD" if diff == "hard" else "NORMAL",

        "avatar_url": avatar_b64,
        "user_name": base_name or hide_uid(uid, user_pref=user_pref),
        "uid": hide_uid(base_role_id or uid, user_pref=user_pref),
        "user_level": base_level,
        "world_level": base_world_level,
        "create_time": base_create_time,
        "groups": page_groups,
        "page": page,
        "total_pages": total_pages,
        "summary": {
            "total_groups": len(groups_sorted),
            "total_pass": total_pass,
            "total_all": total_all,
            "percent": (total_pass / total_all * 100) if total_all else 0,
            "medals_obtained": medals_obtained,
            "medals_plated": medals_plated,
            "medals_total": medals_total,
        },
    }

    img_bytes = await render_html(end_templates, "end_dungeon_card.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ HTML 渲染失败，请检查渲染环境"
