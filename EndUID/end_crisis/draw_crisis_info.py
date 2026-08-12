import io
import re
from typing import Optional, Tuple, Union

from PIL import Image

from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.api.requests import end_api
from ..utils.api.model import CrisisContractResponse, CrisisIndicator
from ..utils.render_utils import render_html, get_image_b64_with_cache
from ..utils.tips import TIP_NO_CRED
from ..utils.path import PLAYER_PATH, PILE_CACHE_PATH
from ..utils.player_store import write_player_json
from . import _common as cm
from .draw_crisis import end_templates, load_cached_crisis_contract

LOGIN_TIP = TIP_NO_CRED

LEVEL_COLOR = {1: "#FF7A02", 2: "#FF5404", 3: "#FF1F05"}

# ===================== buff 文本格式化 =====================

def _fmt_value(raw: float, fmt: str) -> str:
    if fmt.endswith("%"):
        v = raw * 100
        return f"{v:.0f}%" if abs(v - round(v)) < 1e-6 else f"{v:g}%"
    return f"{raw:.0f}" if abs(raw - round(raw)) < 1e-6 else f"{raw:g}"


def _eval_expr(expr: str, params: dict) -> Optional[float]:
    """计算如 1-attr / -dmg_scale / hp_up-1 的简单表达式"""
    tokens = re.findall(r"[+-]?[^+-]+", expr.strip())
    total = 0.0
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        sign = 1.0
        if tok[0] in "+-":
            sign = -1.0 if tok[0] == "-" else 1.0
            tok = tok[1:].strip()
        if tok == "":
            continue
        if tok in params:
            try:
                total += sign * float(params[tok])
            except Exception:
                return None
        else:
            try:
                total += sign * float(tok)
            except Exception:
                return None
    return total


def _format_desc(desc: str, params: dict, params_by_id: dict) -> str:
    """把 <color> 标签转 span，{expr:fmt} / {@id@expr:fmt} 占位符替换为数值"""
    if not desc:
        return ""

    def repl(m: re.Match) -> str:
        body = m.group(1)
        ref_id = None
        rm = re.match(r"@([0-9a-f]+)@(.*)", body)
        if rm:
            ref_id = rm.group(1)
            body = rm.group(2)
        if ":" in body:
            expr, fmt = body.rsplit(":", 1)
        else:
            expr, fmt = body, "0"
        use_params = params_by_id.get(ref_id, params) if ref_id else params
        val = _eval_expr(expr, use_params)
        if val is None:
            return m.group(0)
        return _fmt_value(val, fmt)

    out = re.sub(r"\{([^{}]+)\}", repl, desc)
    out = re.sub(r'<color=(#[0-9a-fA-F]{6})>', r'<span style="color:\1">', out)
    out = out.replace("</color>", "</span>")
    return out


# ===================== 数据获取（落盘缓存） =====================

async def _fetch_fresh(ev: Event, uid: str) -> Optional[dict]:
    """请求当前用户自己的有效合约数据。"""
    cred, user_record = await cm.resolve_cred(ev, uid)
    if not cred:
        return None
    server_id = user_record.server_id if user_record and user_record.server_id else "1"
    skland_user_id = user_record.skland_user_id if user_record and user_record.skland_user_id else None
    res = await end_api.get_crisis_contract(
        cred, uid, server_id=server_id, user_id=skland_user_id, bot_id=ev.bot_id,
    )
    if res and res.get("code") == 0:
        try:
            cc = CrisisContractResponse.model_validate(res).data.crisisContract
        except Exception as e:
            logger.error(f"[ENDUID·危机合约] 信息解析失败: {e}")
            return None
        if cc.status.id:
            try:
                await write_player_json(
                    PLAYER_PATH / uid / "crisis_contract.json",
                    cm.scrub_urls(res),
                )
            except Exception as e:
                logger.warning(f"[ENDUID·危机合约] 信息缓存写入失败: {e}")
            await cm.record_group_and_profile(ev, uid)
            return res
    return None


async def draw_crisis_info_img(
    ev: Event, uid: str,
) -> Union[bytes, str, Tuple[str, bytes]]:
    # 优先请求请求方本人数据；命中即为本人数据，挑战奖励状态仅对本人展示
    res = await _fetch_fresh(ev, uid)
    is_own = res is not None
    used_cache = False
    cc = None
    if res is None:
        cred, _ = await cm.resolve_cred(ev, uid)
        if not cred:
            return LOGIN_TIP
        cc = await load_cached_crisis_contract(uid)
        if cc is None:
            return cm.CRISIS_UNAVAILABLE_TIP
        is_own = True
        used_cache = True

    if cc is None:
        try:
            cc = CrisisContractResponse.model_validate(res).data.crisisContract
        except Exception as e:
            logger.error(f"[ENDUID·危机合约] 信息解析失败: {e}")
            return cm.CRISIS_UNAVAILABLE_TIP

    if not cc.status.id:
        return cm.CRISIS_UNAVAILABLE_TIP

    if is_own and not used_cache:
        cm.update_crisis_period(cc.status)

    indicators = cc.indicators or []
    params_by_id = {ind.id: ind.descParams for ind in indicators}
    id_to_name = {ind.id: ind.name for ind in indicators}
    # 真正的密钥 = 被其他指标 depends 引用的那些
    key_ids = set()
    for ind in indicators:
        key_ids.update(ind.depends or [])

    def _ind_ctx(ind: CrisisIndicator) -> dict:
        dep_names = []
        seen = set()
        for d in ind.depends or []:
            nm = id_to_name.get(d)
            if nm and nm not in seen:
                seen.add(nm)
                dep_names.append(nm)
        return {
            "name": ind.name,
            "score": ind.score,
            "type": ind.type,
            "hasAward": ind.hasAward,
            "isUnlock": ind.isUnlock,
            "isKey": ind.id in key_ids,
            "depends_names": dep_names,
            "desc": _format_desc(ind.desc, ind.descParams, params_by_id),
        }

    groups = []
    for lv in (1, 2, 3):
        items = [ind for ind in indicators if ind.score == lv]
        if not items:
            continue
        baked = []
        for ind in items:
            ic = ""
            try:
                ic = await get_image_b64_with_cache(ind.icon, PILE_CACHE_PATH, quality=80, cover_size=(80, 80))
            except Exception:
                pass
            d = _ind_ctx(ind)
            d["icon_b64"] = ic
            baked.append(d)
        groups.append({"level": lv, "color": LEVEL_COLOR.get(lv, "#FF7A02"), "stars": lv, "inds": baked})

    enemies_ctx = []
    for en in cc.dungeon.enemies:
        img_b64 = ""
        try:
            img_b64 = await get_image_b64_with_cache(en.imageUrl, PILE_CACHE_PATH, quality=82, cover_size=(200, 200))
        except Exception:
            pass
        enemies_ctx.append({
            "name": en.name, "level": en.level,
            "ability": en.ability, "desc": en.desc, "img_b64": img_b64,
        })

    context = {
        "asset_grid_tile": cm.res_b64("grid_tile.png"),
        "asset_indicator": cm.crisis_b64("indicator.png"),
        "is_own": is_own,
        "act_name": cc.status.name,
        "groups": groups,
        "dungeon_name": cc.dungeon.name,
        "dungeon_desc": cc.dungeon.desc,
        "dungeon_feature": cc.dungeon.feature,
        "enemies": enemies_ctx,
    }

    img_bytes = await render_html(end_templates, "end_crisis_info.html", context)
    if img_bytes:
        image = await convert_img(Image.open(io.BytesIO(img_bytes)))
        if used_cache:
            return cm.CRISIS_CACHE_TIP, image
        return image
    return "❌ HTML 渲染失败，请检查渲染环境"
