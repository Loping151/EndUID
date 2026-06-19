import io
from typing import List, Optional, Union

from PIL import Image

from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.api.requests import end_api
from ..utils.api.model import CrisisRecordResponse, CrisisDetailChar
from ..utils.render_utils import render_html, get_image_b64_with_cache
from ..end_config import PREFIX
from ..utils.path import PILE_CACHE_PATH
from . import _common as cm
from .draw_crisis import fetch_crisis_contract, end_templates

_EQUIP_ORDER = ("bodyEquip", "firstAccessory", "armEquip", "secondAccessory")


async def _bake_equip(equip) -> dict:
    if not equip or not equip.icon:
        return {"icon_b64": "", "rarity_color": "#444", "enhance_icon": ""}
    icon_b64 = ""
    try:
        icon_b64 = await get_image_b64_with_cache(
            equip.icon, PILE_CACHE_PATH, quality=82, cover_size=(96, 96),
        )
    except Exception as e:
        logger.warning(f"[ENDUID·危机合约] 装备图标失败: {e}")
    return {
        "icon_b64": icon_b64,
        "rarity_color": cm.rarity_color(equip.rarity.key if equip.rarity else ""),
        "enhance_icon": cm.enhance_b64(equip.enhanceStatus),
    }


async def _bake_detail_char(c: CrisisDetailChar) -> dict:
    potential_icon = cm.potential_b64(c.potentialLevel)

    weapon = None
    if c.weapon and c.weapon.icon:
        w_icon = ""
        try:
            w_icon = await get_image_b64_with_cache(
                c.weapon.icon, PILE_CACHE_PATH, quality=82, cover_size=(120, 120),
            )
        except Exception as e:
            logger.warning(f"[ENDUID·危机合约] 武器图标失败: {e}")
        weapon = {
            "icon_b64": w_icon,
            "level": c.weapon.level,
            "refineLevel": c.weapon.refineLevel,
            "refine_icon": cm.potential_b64(c.weapon.refineLevel),
            "terms": c.weapon.weaponTerms[:3],
            "rarity_color": cm.rarity_color(c.weapon.rarity.key if c.weapon.rarity else ""),
        }

    equips = [await _bake_equip(getattr(c.equips, slot, None)) for slot in _EQUIP_ORDER]

    return {
        "level": c.level,
        "potentialIcon": potential_icon,
        "avatar_b64": await cm.bake_avatar_by_id(c.charId, c.avatarUrl),
        "rarity_color": cm.rarity_color(c.rarity.key if c.rarity else ""),
        "weapon": weapon,
        "equips": equips,
    }


async def draw_crisis_detail_img(ev: Event, uid: str, index: int) -> Union[bytes, str]:
    # fetch_crisis_contract 成功时返回 (cc, cred, user_record)
    cc, cred, user_record = await fetch_crisis_contract(ev, uid)
    if cc is None:
        return cred

    records = cc.history.records or []
    if index == 0:
        target = cc.history.bestRecord
        if not target or not target.id:
            return "❌ 暂无最佳记录"
        record_label = "最佳记录"
    else:
        if not records:
            return "❌ 暂无历史记录"
        if index < 1 or index > len(records):
            return f"❌ 记录序号超出范围（共 {len(records)} 条，可用 0(最佳)/1~{len(records)}）"
        target = records[index - 1]
        record_label = f"#{index}"

    server_id = user_record.server_id if user_record and user_record.server_id else "1"
    skland_user_id = user_record.skland_user_id if user_record and user_record.skland_user_id else None

    res = await end_api.get_crisis_record(
        cred, uid, cc.status.id, target.id,
        server_id=server_id, user_id=skland_user_id, bot_id=ev.bot_id,
    )
    if not res:
        return "获取记录详情失败"
    if res.get("code") != 0:
        return f"获取记录详情失败: {res.get('message', '未知错误')}"

    try:
        rd = CrisisRecordResponse.model_validate(res).data.recordDetail
    except Exception as e:
        logger.error(f"[ENDUID·危机合约] 记录详情解析失败: {e}")
        return "❌ 解析记录详情失败"

    user_pref = user_record.hide_uid_self_value if user_record and user_record.hide_uid_self_value else ""
    base_ctx = await cm.load_player_base(ev, uid, user_pref)

    chars_ctx = [await _bake_detail_char(c) for c in rd.chars]

    # 已选指标（按 indicatorIds 过滤），buff 文案与合约信息页一致
    from .draw_crisis_info import _format_desc, LEVEL_COLOR
    params_by_id = {ind.id: ind.descParams for ind in rd.indicators}
    sel_ids = set(rd.indicatorIds or [])
    selected = [ind for ind in rd.indicators if ind.id in sel_ids] if sel_ids else []
    selected.sort(key=lambda x: (x.score, x.type))
    indicators_ctx = []
    for ind in selected:
        ic = ""
        try:
            ic = await get_image_b64_with_cache(ind.icon, PILE_CACHE_PATH, quality=80, cover_size=(80, 80))
        except Exception:
            pass
        indicators_ctx.append({
            "name": ind.name,
            "score": ind.score,
            "color": LEVEL_COLOR.get(ind.score, "#FF7A02"),
            "icon_b64": ic,
            "desc": _format_desc(ind.desc, ind.descParams, params_by_id),
        })

    context = {
        "asset_grid_tile": cm.res_b64("grid_tile.png"),
        "asset_score_success": cm.crisis_b64("score_success.png"),
        "asset_score_fail": cm.crisis_b64("score_fail.png"),
        "asset_indicator": cm.crisis_b64("indicator.png"),
        "asset_clock": cm.crisis_b64("clock.png"),
        "act_name": cc.status.name,
        "record_label": record_label,
        "record_total": len(records),
        "prefix": PREFIX,
        "isPass": rd.isPass,
        "isBest": rd.isBest,
        "indicatorCount": rd.indicatorCount,
        "passDuration": cm.fmt_duration(rd.passTs),
        "passDate": cm.fmt_datetime(rd.ts),
        "passWave": rd.passWave,
        "waves": [cm.wave_b64(w, w <= rd.passWave) for w in range(1, 5)],
        "chars": chars_ctx,
        "indicators": indicators_ctx,
        **base_ctx,
    }

    img_bytes = await render_html(end_templates, "end_crisis_detail.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ HTML 渲染失败，请检查渲染环境"
