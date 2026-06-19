from typing import Any, Dict, List, Optional

import httpx

from gsuid_core.logger import logger

from ...end_config.config_default import EndConfig

MAIN_URL = "https://end.loping151.site"

UPLOAD_HOLD_URL = f"{MAIN_URL}/top/end/hold/upload"
UPLOAD_CRISIS_URL = f"{MAIN_URL}/top/end/crisis/upload"
GET_CRISIS_RANK_URL = f"{MAIN_URL}/top/end/crisis/rank"
GET_INDICATOR_STAT_URL = f"{MAIN_URL}/top/end/indicator/stat"
GET_HOLD_RATE_URL = f"{MAIN_URL}/api/end/hold/rates"

TIMEOUT = httpx.Timeout(15)


def _get_token() -> str:
    return EndConfig.get_config("EndToken").data or ""


def _auth_headers() -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_get_token()}",
    }


async def _post(url: str, payload: dict, need_auth: bool = True) -> Optional[dict]:
    headers = _auth_headers() if need_auth else {"Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=payload, headers=headers, timeout=TIMEOUT)
            if res.status_code == 200:
                return res.json()
            logger.warning(f"[终末·全排行] 请求失败 {url} status={res.status_code} body={res.text[:200]}")
    except Exception as e:
        logger.warning(f"[终末·全排行] 请求异常 {url}: {e}")
    return None


async def _get(url: str, need_auth: bool = False) -> Optional[dict]:
    headers = _auth_headers() if need_auth else {}
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, headers=headers, timeout=TIMEOUT)
            if res.status_code == 200:
                return res.json()
    except Exception as e:
        logger.warning(f"[终末·全排行] 请求异常 {url}: {e}")
    return None


async def upload_hold(
    end_id: str,
    name: str,
    avatar: str,
    hide_uid: bool,
    user_id: str,
    chars: List[Dict[str, Any]],
) -> bool:
    """上传持有角色列表(角色id/名称/星级/潜能)。"""
    if not _get_token():
        logger.info("[终末·全排行] 未配置 EndToken, 跳过持有上传")
        return False
    if not chars:
        return False
    payload = {
        "end_id": end_id,
        "name": name,
        "avatar": avatar,
        "hide_uid": hide_uid,
        "user_id": user_id,
        "chars": chars,
    }
    res = await _post(UPLOAD_HOLD_URL, payload)
    return bool(res and res.get("code") == 200)


async def upload_crisis(
    end_id: str,
    name: str,
    avatar: str,
    hide_uid: bool,
    user_id: str,
    contract_id: str,
    start_ts: int,
    pass_ts: int,
    indicator_count: int,
    team: List[Dict[str, Any]],
    indicators: List[Dict[str, Any]],
) -> bool:
    """上传危机合约最佳纪录(队伍/用时/指标)。"""
    if not _get_token():
        logger.info("[终末·全排行] 未配置 EndToken, 跳过危机合约上传")
        return False
    if not contract_id:
        return False
    payload = {
        "end_id": end_id,
        "name": name,
        "avatar": avatar,
        "hide_uid": hide_uid,
        "user_id": user_id,
        "contract_id": contract_id,
        "start_ts": start_ts,
        "pass_ts": pass_ts,
        "indicator_count": indicator_count,
        "team": team,
        "indicators": indicators,
    }
    res = await _post(UPLOAD_CRISIS_URL, payload)
    return bool(res and res.get("code") == 200)


async def get_hold_rate() -> Dict[str, Any]:
    """获取服务器角色持有率统计。"""
    res = await _get(GET_HOLD_RATE_URL)
    if res and res.get("code") == 200:
        return res.get("data") or {}
    return {}


async def get_crisis_rank(
    contract_id: str,
    cycle_start_ts: int,
    page: int = 1,
    page_num: int = 20,
    self_end_id: str = "",
) -> Dict[str, Any]:
    """获取危机合约总排行(按周期开始时间过滤)。"""
    payload = {
        "contract_id": contract_id,
        "cycle_start_ts": cycle_start_ts,
        "page": page,
        "page_num": page_num,
        "self_end_id": self_end_id,
    }
    res = await _post(GET_CRISIS_RANK_URL, payload)
    if res and res.get("code") == 200:
        return res.get("data") or {}
    return {}


async def get_indicator_stat(contract_id: str, cycle_start_ts: int) -> Dict[str, Any]:
    """获取指标选择分布统计。"""
    payload = {"contract_id": contract_id, "cycle_start_ts": cycle_start_ts}
    res = await _post(GET_INDICATOR_STAT_URL, payload)
    if res and res.get("code") == 200:
        return res.get("data") or {}
    return {}
