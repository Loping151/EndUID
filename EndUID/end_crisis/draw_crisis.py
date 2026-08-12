import io
import asyncio
from pathlib import Path
from typing import List, Tuple, Union
from datetime import datetime

from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.api.requests import end_api
from ..utils.api.model import CrisisContractResponse, CrisisRecord
from ..utils.render_utils import render_html, get_image_b64_with_cache
from ..end_config import PREFIX
from ..utils.tips import TIP_NO_CRED
from ..utils.path import PILE_CACHE_PATH, PLAYER_PATH
from ..utils.player_store import read_player_json, write_player_json
from . import _common as cm

TEMPLATE_PATH = Path(__file__).parents[1] / "templates"
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

MAIN_HISTORY_LIMIT = 6
HISTORY_LIMIT = 50

LOGIN_TIP = TIP_NO_CRED

# 持有引用避免后台上传任务被 GC
_BG_TASKS: set = set()


async def _bake_chars(chars) -> List[dict]:
    out = []
    for c in chars or []:
        potential_icon = cm.potential_b64(c.potentialLevel)
        out.append({
            "level": c.level,
            "potentialIcon": potential_icon,
            "avatar_b64": await cm.bake_avatar_by_id(c.charId, c.avatarUrl),
        })
    return out


async def _build_record_ctx(rec: CrisisRecord, index: int) -> dict:
    return {
        "index": index,
        "isPass": rec.isPass,
        "isBest": rec.isBest,
        "indicatorCount": rec.indicatorCount,
        "passDuration": cm.fmt_duration(rec.passTs),
        "passDate": cm.fmt_datetime(rec.ts),
        "passWave": rec.passWave,
        "waves": [cm.wave_b64(w, w <= rec.passWave) for w in range(1, 5)],
        "chars": await _bake_chars(rec.chars),
    }


async def fetch_crisis_contract(ev: Event, uid: str):
    """返回 (crisisContract, cred, user_record) 或 (None, 提示文案, user_record)。"""
    cred, user_record = await cm.resolve_cred(ev, uid)
    if not cred:
        return None, LOGIN_TIP, None

    server_id = user_record.server_id if user_record and user_record.server_id else "1"
    skland_user_id = user_record.skland_user_id if user_record and user_record.skland_user_id else None

    res = await end_api.get_crisis_contract(
        cred, uid, server_id=server_id, user_id=skland_user_id, bot_id=ev.bot_id,
    )
    if not res:
        return None, cm.CRISIS_UNAVAILABLE_TIP, user_record
    if res.get("code") != 0:
        logger.info(
            "[ENDUID·危机合约] 暂无当期数据: "
            f"{res.get('message', '未知原因')}"
        )
        return None, cm.CRISIS_UNAVAILABLE_TIP, user_record

    try:
        cc = CrisisContractResponse.model_validate(res).data.crisisContract
    except Exception as e:
        logger.error(f"[ENDUID·危机合约] 详情解析失败: {e}")
        return None, cm.CRISIS_UNAVAILABLE_TIP, user_record

    if not cc.status.id:
        return None, cm.CRISIS_UNAVAILABLE_TIP, user_record

    try:
        await write_player_json(
            PLAYER_PATH / uid / "crisis_contract.json", cm.scrub_urls(res)
        )
    except Exception as e:
        logger.warning(f"[ENDUID·危机合约] 详情写入失败: {e}")

    cm.update_crisis_period(cc.status)
    await cm.record_group_and_profile(ev, uid)

    # 仅查询自己时上传最佳纪录用于危机合约总排行统计
    from ..utils.at_help import ruser_id
    if ruser_id(ev) == ev.user_id:
        task = asyncio.create_task(_upload_crisis(ev, uid, cred, user_record, cc))
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)

    return cc, cred, user_record


async def load_cached_crisis_contract(uid: str):
    """读取该角色最近一次有效合约数据；缓存损坏或为空时返回 None。"""
    cached = await read_player_json(PLAYER_PATH / uid / "crisis_contract.json")
    if (
        not isinstance(cached, dict)
        or cached.get("code") != 0
    ):
        return None
    try:
        cc = CrisisContractResponse.model_validate(cached).data.crisisContract
    except Exception as e:
        logger.warning(f"[ENDUID·危机合约] 缓存解析失败: {e}")
        return None
    return cc if cc.status.id else None


async def _upload_crisis(ev: Event, uid: str, cred, user_record, cc) -> None:
    """后台上传当期最佳纪录(队伍/用时/指标)。"""
    try:
        from ..utils.api import endapi
        from ..utils.api.model import CrisisRecordResponse
        from ..utils.util import get_hide_uid_pref
        from ..utils.at_help import ruser_id
        from ..end_config.config_default import EndConfig

        best = cc.history.bestRecord
        if not best or not best.id or not best.isPass:
            return
        contract_id = cc.status.id
        if not contract_id:
            return

        server_id = user_record.server_id if user_record and user_record.server_id else "1"
        skland_user_id = user_record.skland_user_id if user_record and user_record.skland_user_id else None
        res = await end_api.get_crisis_record(
            cred, uid, contract_id, best.id,
            server_id=server_id, user_id=skland_user_id, bot_id=ev.bot_id,
        )
        if not res or res.get("code") != 0:
            return
        rd = CrisisRecordResponse.model_validate(res).data.recordDetail

        team = [{"char_id": c.charId, "potential": c.potentialLevel} for c in rd.chars]
        # 仅上传该纪录已选指标; ids 缺失时上传空列表, 避免把全部可选指标算成"已使用"污染统计
        # desc 经 _format_desc 处理(替换占位符/颜色标签), 避免存到后端是带 {占位符} 的乱码
        from .draw_crisis_info import _format_desc
        params_by_id = {i.id: i.descParams for i in rd.indicators}
        sel_ids = set(rd.indicatorIds or [])
        src = [ind for ind in rd.indicators if ind.id in sel_ids]
        indicators = [{
            "indicator_id": ind.id,
            "name": ind.name,
            "desc": _format_desc(ind.desc, ind.descParams, params_by_id),
            "icon": ind.icon,
            "score": ind.score,
        } for ind in src]

        try:
            start_ts = int(best.ts)
        except (TypeError, ValueError):
            start_ts = 0
        try:
            pass_ts = int(rd.passTs)
        except (TypeError, ValueError):
            pass_ts = 0

        # 昵称取游戏内名称(本地缓存); 头像用发送者平台头像(ev), 用于总排行展示
        from ..utils.util import get_sender_avatar
        name = ""
        try:
            base = await read_player_json(PLAYER_PATH / uid / "card_detail.json") or {}
            name = (base.get("data", {}).get("detail", {}).get("base", {}) or {}).get("name", "") or ""
        except Exception:
            pass
        avatar = get_sender_avatar(ev)

        user_id = ruser_id(ev)
        pref = await get_hide_uid_pref(uid, user_id, ev.bot_id)
        if pref == "on":
            hide_uid_flag = True
        elif pref == "off":
            hide_uid_flag = False
        else:
            hide_uid_flag = bool(EndConfig.get_config("HideUid").data)

        ok = await endapi.upload_crisis(
            uid, name, avatar, hide_uid_flag, user_id,
            contract_id, start_ts, pass_ts, rd.indicatorCount, team, indicators,
        )
        logger.info(
            f"[ENDUID·危机合约] 上传{'成功' if ok else '未执行(检查EndToken/网络)'}: "
            f"指标{rd.indicatorCount} 用时{pass_ts}s uid={uid}"
        )
    except Exception as e:
        logger.warning(f"[ENDUID·危机合约] 上传异常 uid={uid}: {e}")


async def build_status_ctx(status) -> dict:
    """hero + 指标网格 + 期次勋章 的公共 context"""
    kv_b64 = ""
    if status.kvImage:
        try:
            kv_b64 = await get_image_b64_with_cache(
                status.kvImage, PILE_CACHE_PATH, quality=85, cover_size=(1420, 480),
            )
        except Exception as e:
            logger.warning(f"[ENDUID·危机合约] KV 下载失败: {e}")

    medal: dict = {}
    if status.achieve:
        data = status.achieve.achievementData
        icon_url = data.platedIcon if status.achieve.isPlated and data.platedIcon else data.initIcon
        icon_b64 = ""
        if icon_url:
            try:
                icon_b64 = await get_image_b64_with_cache(
                    icon_url, PILE_CACHE_PATH, quality=85, cover_size=(180, 180),
                )
            except Exception as e:
                logger.warning(f"[ENDUID·危机合约] 勋章图标失败: {e}")
        medal = {
            "name": (data.name or "").strip(' "“”\''),
            "obtained": status.achieve.level > 0,
            "isPlated": status.achieve.isPlated,
            "icon_b64": icon_b64,
        }

    now = int(datetime.now().timestamp())
    start = int(status.startAtTs or 0)
    end = int(status.endAtTs or 0)
    gameplay_end = int(status.gameplayEndAtTs or 0)
    # 玩法是否进行中以 gameplayEndAtTs 为准；玩法结束后展示奖励兑换截止
    is_in_activity = start < now < (gameplay_end or end)
    if gameplay_end and now >= gameplay_end:
        date_text = f"奖励兑换截止 {cm.fmt_datetime(status.endAtTs)}"
    else:
        date_text = f"{cm.fmt_date(status.startAtTs)} ~ {cm.fmt_date(status.endAtTs)}"

    return {
        "kv_b64": kv_b64,
        "asset_mission_bg": cm.crisis_b64("mission_bg.png"),
        "icon_challenge": cm.crisis_b64("mi_challenge.png"),
        "icon_weekly": cm.crisis_b64("mi_weekly.png"),
        "icon_indicator": cm.crisis_b64("mi_indicator.png"),
        "icon_stage": cm.crisis_b64("mi_stage.png"),
        "asset_indicator": cm.crisis_b64("indicator.png"),
        "act_name": status.name,
        "highest": status.highest,
        "challenge_count": status.challengeCount,
        "date_text": date_text,
        "is_in_activity": is_in_activity,
        "weekly": {"count": status.weeklyMission.count, "total": status.weeklyMission.total},
        "indicator_mission": {"count": status.indicatorMission.count, "total": status.indicatorMission.total},
        "stage": {"count": status.stageMission.count, "total": status.stageMission.total},
        "medal": medal,
    }


async def draw_crisis_img(
    ev: Event, uid: str, mode: str = "main",
) -> Union[bytes, str, Tuple[str, bytes]]:
    cc, err, user_record = await fetch_crisis_contract(ev, uid)
    used_cache = False
    if cc is None:
        if err != cm.CRISIS_UNAVAILABLE_TIP:
            return err
        cc = await load_cached_crisis_contract(uid)
        if cc is None:
            return err
        used_cache = True

    status = cc.status
    if not status.id:
        return cm.CRISIS_UNAVAILABLE_TIP

    user_pref = user_record.hide_uid_self_value if user_record and user_record.hide_uid_self_value else ""
    base_ctx = await cm.load_player_base(ev, uid, user_pref)
    status_ctx = await build_status_ctx(status)

    records = cc.history.records or []
    best = cc.history.bestRecord

    best_ctx = None
    if mode == "main" and best:
        best_ctx = await _build_record_ctx(best, 0)

    limit = MAIN_HISTORY_LIMIT if mode == "main" else HISTORY_LIMIT
    best_id = best.id if best else None
    pin_best = mode == "history" and best
    # 最佳记录 pin 到 #0，列表内去重；编号保持与「记录N」一致
    history_ctx = [
        await _build_record_ctx(r, i + 1)
        for i, r in enumerate(records[:limit])
        if not (pin_best and r.id == best_id)
    ]
    if pin_best:
        history_ctx = [await _build_record_ctx(best, 0)] + history_ctx
    history_ctx = history_ctx[:HISTORY_LIMIT]

    context = {
        "asset_grid_tile": cm.res_b64("grid_tile.png"),
        "asset_card_success": cm.local_b64("card_success.png", quality=70),
        "asset_card_fail": cm.local_b64("card_fail.png", quality=70),
        "asset_clock": cm.crisis_b64("clock.png"),
        "asset_score_success": cm.crisis_b64("score_success.png"),
        "asset_score_fail": cm.crisis_b64("score_fail.png"),
        "mode": mode,
        "prefix": PREFIX,
        "best": best_ctx,
        "history": history_ctx,
        "history_total": len(records),
        **base_ctx,
        **status_ctx,
    }

    img_bytes = await render_html(end_templates, "end_crisis_card.html", context)
    if img_bytes:
        image = await convert_img(Image.open(io.BytesIO(img_bytes)))
        if used_cache:
            return cm.CRISIS_CACHE_TIP, image
        return image
    return "❌ HTML 渲染失败，请检查渲染环境"
