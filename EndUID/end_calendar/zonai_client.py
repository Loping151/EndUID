"""zonai.skland.com 直连客户端：拉取终末地 wiki landing 数据。

签名： MD5(HmacSHA256(path + body_or_query + ts + JSON({platform,timestamp,dId,vName}), token))
token 从 /web/v1/auth/refresh 拿（首次以空 token 签名 bootstrap）。
"""
import asyncio
import hashlib
import hmac
import json
import time
from typing import Dict, Optional

import httpx

from gsuid_core.logger import logger

HOST = "https://zonai.skland.com"
ENDPOINTS = ("char-pool", "activity", "banner", "weapon-pool")
TOKEN_PATH = "/web/v1/auth/refresh"

_token: str = ""
_token_gen: int = 0
_token_lock = asyncio.Lock()


def _make_headers(path: str, ts: str, token: str, did: str = "") -> Dict[str, str]:
    payload = {"platform": "3", "timestamp": ts, "dId": did, "vName": "1.0.0"}
    s = path + "" + ts + json.dumps(payload, separators=(",", ":"))
    mac = hmac.new(token.encode("utf-8"), s.encode("utf-8"), hashlib.sha256).hexdigest()
    sign = hashlib.md5(mac.encode("utf-8")).hexdigest()
    return {
        "platform": "3",
        "vname": "1.0.0",
        "did": did,
        "timestamp": ts,
        "sign": sign,
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://wiki.skland.com",
        "referer": "https://wiki.skland.com/",
        "user-agent": "Mozilla/5.0",
    }


async def _refresh_token(client: httpx.AsyncClient) -> str:
    ts = str(int(time.time()))
    resp = await client.get(HOST + TOKEN_PATH, headers=_make_headers(TOKEN_PATH, ts, token=""), timeout=10.0)
    j = resp.json()
    if j.get("code") == 10000 and "timestamp" in j:
        ts = str(j["timestamp"])
        resp = await client.get(HOST + TOKEN_PATH, headers=_make_headers(TOKEN_PATH, ts, token=""), timeout=10.0)
        j = resp.json()
    token = (j.get("data") or {}).get("token", "")
    if not token:
        raise RuntimeError(f"auth/refresh 失败: {j}")
    return token


async def _get_token(client: httpx.AsyncClient) -> tuple[str, int]:
    """初次获取 / 取已缓存 token。返回 (token, gen)。"""
    global _token, _token_gen
    async with _token_lock:
        if _token:
            return _token, _token_gen
        _token = await _refresh_token(client)
        _token_gen += 1
        return _token, _token_gen


async def _force_refresh_token(client: httpx.AsyncClient, observed_gen: int) -> tuple[str, int]:
    """gen 仍是调用方观察值则刷一次；否则用别人已刷好的。"""
    global _token, _token_gen
    async with _token_lock:
        if _token_gen != observed_gen:
            return _token, _token_gen
        _token = await _refresh_token(client)
        _token_gen += 1
        return _token, _token_gen


async def _fetch_one(
    client: httpx.AsyncClient, endpoint: str, token: str, gen: int, _retried: bool = False
) -> Optional[dict]:
    path = f"/web/v1/wiki/{endpoint}"
    ts = str(int(time.time()))
    resp = await client.get(HOST + path, headers=_make_headers(path, ts, token), timeout=10.0)
    j = resp.json()
    code = j.get("code")
    if code == 10000 and "timestamp" in j:
        ts2 = str(j["timestamp"])
        resp = await client.get(HOST + path, headers=_make_headers(path, ts2, token), timeout=10.0)
        j = resp.json()
        code = j.get("code")
    if code == 10003 and not _retried:
        new_token, new_gen = await _force_refresh_token(client, gen)
        return await _fetch_one(client, endpoint, new_token, new_gen, _retried=True)
    if code != 0:
        logger.warning(f"[ENDUID·日历] {endpoint} HTTP code={code}, msg={j.get('message')}")
        return None
    return j.get("data") or {}


async def fetch_landing() -> Optional[Dict[str, dict]]:
    """4 个 endpoint 并发拉。任一失败返回 None（让调用方 fallback）。"""
    try:
        async with httpx.AsyncClient() as client:
            token, gen = await _get_token(client)
            results = await asyncio.gather(
                *(_fetch_one(client, ep, token, gen) for ep in ENDPOINTS),
                return_exceptions=True,
            )
    except Exception as e:
        logger.warning(f"[ENDUID·日历] HTTP 拉取异常: {e}")
        return None

    out: Dict[str, dict] = {}
    for ep, r in zip(ENDPOINTS, results):
        if isinstance(r, dict):
            out[ep] = r
        elif isinstance(r, Exception):
            logger.warning(f"[ENDUID·日历] {ep} 异常: {r}")

    if len(out) < len(ENDPOINTS):
        logger.warning(f"[ENDUID·日历] HTTP 仅拿到 {list(out.keys())}, 缺 {set(ENDPOINTS) - set(out.keys())}")
        return None
    return out
