import io
import json
from pathlib import Path
from typing import List, Union
from datetime import datetime

import aiofiles
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
from . import _common as cm

TEMPLATE_PATH = Path(__file__).parents[1] / "templates"
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

MAIN_HISTORY_LIMIT = 6
HISTORY_LIMIT = 50

LOGIN_TIP = TIP_NO_CRED


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
    """返回 (crisisContract, cred, user_record) 或 (None, 错误文案, None)"""
    cred, user_record = await cm.resolve_cred(ev, uid)
    if not cred:
        return None, LOGIN_TIP, None

    server_id = user_record.server_id if user_record and user_record.server_id else "1"
    skland_user_id = user_record.skland_user_id if user_record and user_record.skland_user_id else None

    res = await end_api.get_crisis_contract(
        cred, uid, server_id=server_id, user_id=skland_user_id, bot_id=ev.bot_id,
    )
    if not res:
        return None, "获取危机合约详情失败", None
    if res.get("code") != 0:
        return None, f"获取危机合约详情失败: {res.get('message', '未知错误')}", None

    try:
        player_dir = PLAYER_PATH / uid
        player_dir.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(player_dir / "crisis_contract.json", "w", encoding="utf-8") as f:
            await f.write(json.dumps(cm.scrub_urls(res), ensure_ascii=False))
    except Exception as e:
        logger.warning(f"[ENDUID·危机合约] 详情写入失败: {e}")

    try:
        cc = CrisisContractResponse.model_validate(res).data.crisisContract
    except Exception as e:
        logger.error(f"[ENDUID·危机合约] 详情解析失败: {e}")
        return None, "❌ 解析危机合约详情失败", None

    cm.update_crisis_period(cc.status)
    await cm.record_group_and_profile(ev, uid)
    return cc, cred, user_record


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


async def draw_crisis_img(ev: Event, uid: str, mode: str = "main") -> Union[bytes, str]:
    cc, err, user_record = await fetch_crisis_contract(ev, uid)
    if cc is None:
        return err

    status = cc.status
    if not status.id:
        return "❌ 暂无危机合约数据"

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
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    return "❌ HTML 渲染失败，请检查渲染环境"
