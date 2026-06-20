import os
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from gsuid_core.models import Event
from gsuid_core.logger import logger

from ..utils.api.requests import end_api
from ..utils.database.models import EndUser
from ..utils.render_utils import image_to_base64, get_image_b64_with_cache
from ..utils.util import hide_uid
from ..utils.colors import RARITY_COLORS
from ..utils.path import AVATAR_CACHE_PATH, PLAYER_PATH, MAIN_PATH
from ..utils.resources import res_b64, potential_b64  # noqa: F401  re-export

TEXTURE_PATH = Path(__file__).parent / "texture2d"

# 当期危机合约周期（服务器共用，落盘 data 内、重启有效）
CRISIS_PERIOD_FILE = MAIN_PATH / "crisis_period.json"


def get_crisis_period() -> Optional[dict]:
    try:
        if CRISIS_PERIOD_FILE.exists():
            return json.loads(CRISIS_PERIOD_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[ENDUID·危机合约] 周期文件读取失败: {e}")
    return None


def get_crisis_period_query() -> Optional[Tuple[str, int, str]]:
    """当期排行/统计查询参数: (contract_id, cycle_start_ts, act_name); 无周期返回 None"""
    period = get_crisis_period()
    if not period or not period.get("contract_id"):
        return None
    try:
        start = int(period.get("startAtTs") or 0)
    except (TypeError, ValueError):
        start = 0
    return period["contract_id"], start, period.get("name") or ""


def update_crisis_period(status) -> None:
    """查询时若合约期次/持续时间与本地不一致则写入"""
    try:
        cur = get_crisis_period() or {}
        same = (
            cur.get("contract_id") == status.id
            and str(cur.get("startAtTs")) == str(status.startAtTs)
            and str(cur.get("endAtTs")) == str(status.endAtTs)
        )
        if same:
            return
        MAIN_PATH.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "contract_id": status.id,
            "name": status.name,
            "startAtTs": status.startAtTs,
            "endAtTs": status.endAtTs,
            "gameplayEndAtTs": status.gameplayEndAtTs,
        }, ensure_ascii=False)
        # 原子替换，避免并发读到半写文件
        tmp = CRISIS_PERIOD_FILE.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, CRISIS_PERIOD_FILE)
    except Exception as e:
        logger.warning(f"[ENDUID·危机合约] 周期文件写入失败: {e}")


def local_b64(filename: str, quality: int = 0) -> str:
    return image_to_base64(TEXTURE_PATH / filename, quality=quality)


def crisis_b64(name: str, quality: int = 0) -> str:
    """危机合约共用素材（resources/crisis/）"""
    return res_b64(f"crisis/{name}", quality=quality)


def wave_b64(index: int, on: bool) -> str:
    """波次徽章合成图（底图+罗马数字），index 1-4"""
    if not (1 <= index <= 4):
        return ""
    return res_b64(f"crisis/wave/{'on' if on else 'off'}_{index}.png")


def enhance_b64(status: int) -> str:
    """装备强化状态图标（enhanceStatus 1-3）"""
    if status and 1 <= status <= 3:
        return res_b64(f"crisis/enhance_{status}.png")
    return ""


def fmt_date(ts: str) -> str:
    try:
        n = int(ts)
        return datetime.fromtimestamp(n).strftime("%Y.%m.%d") if n > 0 else ""
    except Exception:
        return ""


def fmt_datetime(ts: str) -> str:
    try:
        n = int(ts)
        return datetime.fromtimestamp(n).strftime("%Y-%m-%d %H:%M") if n > 0 else ""
    except Exception:
        return ""


def fmt_duration(secs: str) -> str:
    try:
        n = int(secs)
        if n <= 0:
            return ""
        m, s = divmod(n, 60)
        return f"{m:02d}:{s:02d}"
    except Exception:
        return ""


def rarity_color(key: str) -> str:
    m = re.search(r"(\d+)$", key or "")
    if not m:
        return "#888888"
    return RARITY_COLORS.get(int(m.group(1)), "#888888")


def parse_trailing_number(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*$", text or "")
    return int(m.group(1)) if m else None


async def resolve_cred(ev: Event, uid: str) -> Tuple[Optional[str], Optional[object]]:
    """返回 (cred, user_record)；cred 为空表示需要登录"""
    from ..utils.at_help import ruser_id
    target_user_id = ruser_id(ev)
    _, cred = await end_api.get_ck_result(uid, target_user_id, ev.bot_id)
    user_record = await EndUser.select_end_user(uid, target_user_id, ev.bot_id)
    return cred, user_record


async def load_player_base(ev: Event, uid: str, user_pref: str) -> dict:
    """读取本地 card_detail.json 的基础信息 + @头像，组装 header 用 context"""
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
                return datetime.fromtimestamp(n).strftime("%Y-%m-%d") if n > 0 else ""
            except Exception:
                return ""
    try:
        cache_path = PLAYER_PATH / uid / "card_detail.json"
        if cache_path.exists():
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            base = cached.get("data", {}).get("detail", {}).get("base", {}) or {}
            base_name = base.get("name", "") or ""
            base_role_id = base.get("roleId", "") or ""
            base_level = base.get("level", 0) or 0
            base_world_level = base.get("worldLevel", 0) or 0
            base_create_time = _format_awaken_time(base.get("createTime", "")) or ""
            base_avatar_url = base.get("avatarUrl", "") or ""
    except Exception as e:
        logger.warning(f"[ENDUID·危机合约] 基础信息读取失败: {e}")

    # 头像: 优先平台头像(被查询者), 回退游戏卡片头像
    from ..utils.at_help import get_query_avatar_b64
    avatar_b64 = await get_query_avatar_b64(ev, base_avatar_url)

    return {
        "avatar_url": avatar_b64,
        "user_name": base_name or hide_uid(uid, user_pref=user_pref),
        "uid": hide_uid(base_role_id or uid, user_pref=user_pref),
        "user_level": base_level,
        "world_level": base_world_level,
        "create_time": base_create_time,
    }


async def bake_avatar(url: str) -> str:
    if not url:
        return ""
    try:
        return await get_image_b64_with_cache(url, AVATAR_CACHE_PATH)
    except Exception as e:
        logger.warning(f"[ENDUID·危机合约] 头像下载失败: {e}")
        return ""


async def bake_avatar_by_id(char_id: str, fallback_url: str = "") -> str:
    """优先按角色 ID 取头像(同角色面板的 map.json)，缺失时回退接口 avatarUrl"""
    from ..utils.alias_map import get_avatar_by_id
    return await bake_avatar(get_avatar_by_id(char_id) or fallback_url)


# 落盘瘦身 + 入群榜/资料记录助手（实现见 utils.util，跨功能共用）
from ..utils.util import scrub_urls, record_group_and_profile  # noqa: E402,F401
