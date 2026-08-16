"""终末地手机号网页登录。"""

from __future__ import annotations

import asyncio
import base64
import re
import secrets
import time
from io import BytesIO
from pathlib import Path

import httpx
from async_timeout import timeout
from gsuid_core.bot import Bot
from gsuid_core.config import core_config
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.utils.cookie_manager.qrlogin import get_qrcode_base64
from gsuid_core.web_app import app
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel
from starlette.responses import HTMLResponse

from ..end_config import EndConfig
from ..end_wiki.fetch import pick_random_background
from ..utils.api.requests import end_api
from ..utils.cache import TimedCache
from ..utils.image import pic_download_from_url
from ..utils.path import MAIN_PATH, TEMP_PATH, WIKI_IMG_CACHE

GAME_TITLE = "「终末地」"
LOGIN_FLOW = "end_phone"

cache = TimedCache(
    timeout=180,
    maxsize=20,
    persist_path=MAIN_PATH / "end_login_cache.db",
)

_templates = Environment(loader=FileSystemLoader(str(TEMP_PATH)), autoescape=True)


def get_token() -> str:
    return secrets.token_urlsafe(16)


async def build_login_bg() -> str:
    """选一张角色上线贺图/明信片, 下载后转成内联 base64 data URI; 失败返回空串。"""
    url = await pick_random_background()
    if not url:
        return ""
    try:
        img = await pic_download_from_url(WIKI_IMG_CACHE, url)
        img = img.convert("RGB")
        if img.width > 1280:
            img = img.resize((1280, round(img.height * 1280 / img.width)))
        buf = BytesIO()
        img.save(buf, format="WEBP", quality=70)
        return "data:image/webp;base64," + base64.b64encode(
            buf.getvalue()
        ).decode("utf-8")
    except Exception as e:
        logger.warning(f"[ENDUID·网页登录] 背景图处理失败: {e}")
        return ""


def evict_user_login(user_id: str) -> int:
    """撤销同一用户的所有未完成登录会话，让新发的链接成为唯一有效的"""
    return cache.delete_where(
        lambda v: isinstance(v, dict) and v.get("user_id") == user_id
    )


async def get_url() -> str:
    url = EndConfig.get_config("EndLoginUrl").data
    if url:
        if not url.startswith("http"):
            url = f"https://{url}"
        return url.rstrip("/")

    host = core_config.get_config("HOST")
    port = core_config.get_config("PORT")
    if host in ("0.0.0.0", "0.0.0.0:", "", None):
        host = "127.0.0.1"
    return f"http://{host}:{port}"


async def send_login(bot: Bot, ev: Event, url: str):
    at_sender = True if ev.group_id else False

    if EndConfig.get_config("EndQRLogin").data:
        path = Path(__file__).parent / f"{ev.user_id}.gif"
        im = [
            f"{GAME_TITLE} 您的id为【{ev.user_id}】\n请用浏览器扫描打开，完成手机号登录。\n⚠️ 请勿使用他人链接！",
            MessageSegment.image(await get_qrcode_base64(url, path, ev.bot_id)),
        ]
        if EndConfig.get_config("EndLoginForward").data and (
            ev.group_id or ev.bot_id != "onebot"
        ):
            await bot.send(MessageSegment.node(im))
        else:
            await bot.send(im, at_sender=at_sender)
        if path.exists():
            path.unlink()
    else:
        im = [
            f"{GAME_TITLE} 您的id为【{ev.user_id}】",
            url,
            "3分钟内有效，请勿使用他人链接！",
        ]
        if EndConfig.get_config("EndLoginForward").data and (
            ev.group_id or ev.bot_id != "onebot"
        ):
            await bot.send(MessageSegment.node(im))
        else:
            await bot.send("\n".join(im), at_sender=at_sender)


async def phone_web_login_entry(bot: Bot, ev: Event):
    at_sender = True if ev.group_id else False
    evict_user_login(ev.user_id)
    user_token = get_token()

    bg = await build_login_bg()

    cache.set(
        user_token,
        {
            "flow": LOGIN_FLOW,
            "phase": "init",
            "user_id": ev.user_id,
            "bot_id": ev.bot_id,
            "bot_self_id": ev.bot_self_id,
            "group_id": ev.group_id,
            "bg": bg,
        },
    )

    url = await get_url()
    await send_login(bot, ev, f"{url}/end/i/{user_token}")

    try:
        async with timeout(180):
            while True:
                state = cache.get(user_token)
                if state is None:
                    return
                if not isinstance(state, dict) or state.get("flow") != LOGIN_FLOW:
                    return

                phase = state.get("phase")
                if phase == "done":
                    cache.delete(user_token)
                    return

                if phase == "failed":
                    err = state.get("error_msg") or "登录失败"
                    cache.delete(user_token)
                    return await bot.send(
                        (" " if at_sender else "") + f"{GAME_TITLE} {err}",
                        at_sender=at_sender,
                    )

                await asyncio.sleep(1)
    except asyncio.TimeoutError:
        return
    except Exception as e:
        logger.exception(f"[ENDUID·网页登录] 异常: {e}")


async def phone_web_login_external_entry(bot: Bot, ev: Event):
    """使用外置服务完成手机号验证，凭据验证与入库仍由 EndUID 负责。"""
    at_sender = True if ev.group_id else False
    url = await get_url()
    auth = {"bot_id": ev.bot_id, "user_id": ev.user_id}
    shared_secret = str(
        EndConfig.get_config("EndLoginSharedSecret").data or ""
    ).strip()
    if len(shared_secret) < 32:
        return await bot.send(
            (" " if at_sender else "")
            + f"{GAME_TITLE} 请配置至少 32 位的终末地外置登录共享密钥",
            at_sender=at_sender,
        )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{url}/end/token",
                json=auth,
                headers={"X-EndUID-Secret": shared_secret},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("外置服务返回了无效响应")
            user_token = str(payload.get("token") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", user_token):
                raise ValueError("外置服务返回了无效会话")
            poll_token = str(payload.get("poll_token") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", poll_token):
                raise ValueError("外置服务返回了无效轮询凭据")

            await send_login(bot, ev, f"{url}/end/i/{user_token}")

            failures = 0
            hg_token = ""
            try:
                async with timeout(180):
                    while True:
                        try:
                            result = await client.post(
                                f"{url}/end/get",
                                json={
                                    "token": user_token,
                                    "poll_token": poll_token,
                                },
                            )
                            result.raise_for_status()
                            data = result.json()
                            if not isinstance(data, dict):
                                raise TypeError("外置服务返回了无效响应")
                            failures = 0
                        except (httpx.HTTPError, TypeError, ValueError) as exc:
                            failures += 1
                            logger.warning(
                                f"[ENDUID·外置登录] 轮询失败 ({failures}/3): {exc}"
                            )
                            if failures >= 3:
                                return await bot.send(
                                    (" " if at_sender else "")
                                    + f"{GAME_TITLE} 外置登录服务请求失败，请稍后重试",
                                    at_sender=at_sender,
                                )
                            await asyncio.sleep(3)
                            continue

                        if not data.get("done"):
                            await asyncio.sleep(1)
                            continue
                        if not data.get("success"):
                            return await bot.send(
                                (" " if at_sender else "")
                                + f"{GAME_TITLE} {data.get('msg') or '登录失败'}",
                                at_sender=at_sender,
                            )
                        if (
                            str(data.get("user_id") or "") != str(ev.user_id)
                            or str(data.get("bot_id") or "") != str(ev.bot_id)
                        ):
                            logger.error("[ENDUID·外置登录] 会话身份不匹配，拒绝入库")
                            return await bot.send(
                                (" " if at_sender else "")
                                + f"{GAME_TITLE} 登录会话身份校验失败",
                                at_sender=at_sender,
                            )
                        hg_token = str(data.get("hg_token") or "")
                        if not hg_token or len(hg_token) > 4096:
                            return await bot.send(
                                (" " if at_sender else "")
                                + f"{GAME_TITLE} 外置服务未返回有效 Token",
                                at_sender=at_sender,
                            )
                        break
            except asyncio.TimeoutError:
                return await bot.send(
                    (" " if at_sender else "") + f"{GAME_TITLE} 登录超时!",
                    at_sender=at_sender,
                )
            from . import check_token

            return await check_token(bot, ev, hg_token)
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        logger.error(f"[ENDUID·外置登录] 创建会话失败: {exc}")
        return await bot.send(
            (" " if at_sender else "") + f"{GAME_TITLE} 外置登录服务请求失败，请稍后重试",
            at_sender=at_sender,
        )


async def _push_text(state: dict, text: str):
    from gsuid_core.gss import gss

    user_id = state.get("user_id")
    bot_id = state.get("bot_id")
    group_id = state.get("group_id")
    bot_self_id = state.get("bot_self_id") or ""
    for active_id in list(gss.active_bot):
        try:
            if group_id:
                await gss.active_bot[active_id].target_send(
                    text, "group", group_id, bot_id, bot_self_id, ""
                )
            else:
                await gss.active_bot[active_id].target_send(
                    text, "direct", user_id, bot_id, bot_self_id, ""
                )
            return
        except Exception as e:
            logger.warning(f"[ENDUID·网页登录] 结果推送失败: {e}")


async def _proactive_notify(state: dict, result: dict):
    from . import do_login_notify

    async def _send(text):
        return await _push_text(state, text)

    await do_login_notify(
        _send, state.get("user_id"), state.get("bot_id"), result
    )


def _is_valid_phone(phone: str) -> bool:
    return bool(phone) and len(phone) == 11 and phone.isdigit() and phone[0] == "1"


class SendCodeRequest(BaseModel):
    auth: str
    phone: str


class LoginRequest(BaseModel):
    auth: str
    phone: str
    code: str


@app.get("/end/i/{auth}")
async def end_login_index(auth: str):
    state = cache.get(auth)
    url = await get_url()
    if not isinstance(state, dict) or state.get("flow") != LOGIN_FLOW:
        template = _templates.get_template("end_login.html")
        return HTMLResponse(
            template.render(
                server_url=url, auth="", userId="", expired=True, bg_url=""
            )
        )

    template = _templates.get_template("end_login.html")
    return HTMLResponse(
        template.render(
            server_url=url,
            auth=auth,
            userId=state.get("user_id", ""),
            expired=False,
            bg_url=state.get("bg", ""),
        )
    )


@app.post("/end/sendCode")
async def end_login_send_code(data: SendCodeRequest):
    state = cache.get(data.auth)
    if not isinstance(state, dict) or state.get("flow") != LOGIN_FLOW:
        return {"success": False, "msg": "登录会话已超时，请重新发起命令"}
    if not _is_valid_phone(data.phone):
        return {"success": False, "msg": "手机号格式错误"}

    now = time.time()
    wait = 60 - int(now - state.get("last_send_ts", 0))
    if wait > 0:
        return {"success": False, "msg": f"请 {wait} 秒后再获取验证码"}
    if state.get("send_count", 0) >= 5:
        return {"success": False, "msg": "获取验证码次数过多，请重新发起登录"}

    ok, msg = await end_api.send_phone_code(data.phone)
    if not ok:
        return {"success": False, "msg": msg or "验证码发送失败"}

    state["last_send_ts"] = now
    state["send_count"] = state.get("send_count", 0) + 1
    cache.set(data.auth, state)
    return {"success": True}


@app.post("/end/login")
async def end_login_submit(data: LoginRequest):
    state = cache.get(data.auth)
    if not isinstance(state, dict) or state.get("flow") != LOGIN_FLOW:
        return {"success": False, "msg": "登录会话已超时，请重新发起命令"}
    if not _is_valid_phone(data.phone) or not data.code.strip().isdigit():
        return {"success": False, "msg": "手机号或验证码格式错误"}

    def _fail(err: str):
        state["phase"] = "failed"
        state["error_msg"] = err
        cache.set(data.auth, state)
        return {"success": False, "msg": err}

    token, token_msg = await end_api.get_token_by_phone_code(
        data.phone, data.code.strip()
    )
    if not token:
        return {"success": False, "msg": token_msg or "验证码错误或已过期"}

    gacha_grant_token = await end_api.get_gacha_grant_token(token)
    cred_info = await end_api.get_cred_info_by_token(token)
    if cred_info == "405":
        return _fail("当前服务无法使用该方式登录，请改用扫码登录")
    if not cred_info or not cred_info.get("cred"):
        return _fail("获取 cred 失败，请重试")

    from . import _persist_login_cred

    result, err = await _persist_login_cred(
        state.get("user_id"),
        state.get("bot_id"),
        state.get("group_id"),
        cred_info["cred"],
        used_token=token,
        skland_user_id=cred_info.get("skland_user_id"),
        gacha_grant_token=gacha_grant_token,
    )
    if err:
        return _fail(err)

    asyncio.create_task(_proactive_notify(state, result))

    state.update({"phase": "done"})
    cache.set(data.auth, state)
    return {"success": True}
