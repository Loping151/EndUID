"""抽卡记录网页查看：FastAPI 路由 + 链接生成。"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import httpx
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.web_app import app
from starlette.responses import FileResponse, HTMLResponse, JSONResponse

from ..end_bind.web_login import get_url
from ..end_config import PREFIX
from ..end_config.config_default import EndConfig
from ..utils.cache import TimedCache
from ..utils.path import MAIN_PATH, PLAYER_PATH
from ..utils.player_store import player_json_exists
from ..utils.util import hide_uid
from .draw_gachalogs import build_gacha_pools

GACHA_WEB_TTL = 600  # 10 分钟

_token_cache = TimedCache(
    timeout=GACHA_WEB_TTL,
    maxsize=2000,
    persist_path=MAIN_PATH / "end_gacha_url_cache.db",
)

_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "end_gacha_page.html"


def _is_feature_enabled() -> bool:
    return bool(EndConfig.get_config("EndGachaWebPage").data)


def feature_disabled_msg() -> str:
    return "该功能未开启，请联系主人在配置中开启「抽卡记录网页开关」"


async def make_gacha_web_url(
    uid: str, ev: Event, user_pref: str = ""
) -> Tuple[Optional[str], str]:
    """生成 10 分钟内有效的查看链接。返回 (url, message)。"""
    if not _is_feature_enabled():
        return None, feature_disabled_msg()

    if not player_json_exists(PLAYER_PATH / uid / "gacha_logs.json"):
        return None, f"还没有抽卡记录噢！请先使用「{PREFIX}导入抽卡记录」导入"

    payload, err = await build_gacha_pools(uid, ev, user_pref, web=True)
    if err:
        return None, err

    web_payload = {
        "base": {
            "name": payload["name"],
            "uid": hide_uid(uid, user_pref=user_pref),
            "level": payload["level"],
            "avatar": payload["avatar"],
            "data_time": payload.get("data_time", ""),
        },
        "pools": payload["pools"],
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    base = (await get_url()).rstrip("/")
    token = secrets.token_urlsafe(16)
    configured_url = str(EndConfig.get_config("EndLoginUrl").data or "").strip()
    if EndConfig.get_config("EndLoginUrlSelf").data or not configured_url:
        _token_cache.set(token, web_payload)
    else:
        ok = await _push_gacha_to_external(base, token, web_payload)
        if not ok:
            return None, "外置抽卡页面上传失败，请稍后重试"
    return f"{base}/end/gacha/{token}", "ok"


async def _push_gacha_to_external(base: str, token: str, payload: dict) -> bool:
    """上传受限 JSON 摘要；外置服务不接收可执行 HTML。"""
    shared_secret = str(
        EndConfig.get_config("EndLoginSharedSecret").data or ""
    ).strip()
    if len(shared_secret) < 32:
        logger.warning("[ENDUID·抽卡网页] 外置登录共享密钥未配置或不足 32 位")
        return False
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base}/end/gacha/data/{token}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-EndUID-Secret": shared_secret,
                },
            )
        if response.status_code != 200:
            logger.warning(
                f"[ENDUID·抽卡网页] 外置上传失败: "
                f"HTTP {response.status_code} {response.text[:160]}"
            )
            return False
        result = response.json()
        if not isinstance(result, dict):
            raise TypeError("外置服务返回了无效响应")
        if not result.get("success"):
            logger.warning(f"[ENDUID·抽卡网页] 外置上传被拒绝: {result}")
            return False
        logger.info(
            f"[ENDUID·抽卡网页] 已上传外置摘要 token={token} size={len(body)}"
        )
        return True
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        logger.warning(f"[ENDUID·抽卡网页] 外置上传异常: {exc}")
        return False


_NOT_FOUND_HTML = """<!DOCTYPE html><html lang=zh-CN><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>页面已过期</title>
<style>html,body{height:100%;margin:0;background:#0f1014;color:#dfe4ee;
font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;display:flex;
align-items:center;justify-content:center;}
.box{padding:32px 28px;border:1px solid #20232b;border-radius:14px;background:#15171c;
max-width:340px;text-align:center;}
h1{font-size:18px;margin:0 0 8px;color:#ffe600}
p{font-size:13px;color:#8b8b8b;line-height:1.7;margin:6px 0}</style>
<div class=box><h1>页面已过期或不存在</h1>
<p>抽卡记录网页仅在 10 分钟内有效。</p>
<p>请重新发送「抽卡页面」获取新链接。</p></div></html>"""


@app.get("/end/gacha/{token}")
async def end_gacha_index(token: str):
    if not _is_feature_enabled() or not isinstance(_token_cache.get(token), dict):
        return HTMLResponse(_NOT_FOUND_HTML)
    if not _TEMPLATE_PATH.exists():
        return HTMLResponse("<h1>page template missing</h1>", status_code=500)
    return FileResponse(
        _TEMPLATE_PATH,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/end/gacha/{token}/data")
async def end_gacha_data(token: str):
    if not _is_feature_enabled():
        return JSONResponse({"error": "disabled"}, status_code=404)
    payload = _token_cache.get(token)
    if not isinstance(payload, dict):
        return JSONResponse({"error": "expired"}, status_code=404)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})
