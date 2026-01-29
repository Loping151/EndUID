"""EndUID API 请求引擎"""
import json
import time
import asyncio
from typing import Dict, Optional
from urllib.parse import urlparse

import aiohttp
from gsuid_core.logger import logger

from .api import *
from .ds import generate_sign
from .request_util import (
    get_base_header,
    get_refresh_header,
    get_oauth_header,
    get_cred_header,
    get_device_id,
    get_endfield_web_headers,
    get_skland_app_headers,
    get_skland_app_security_headers,
    ANDROID_USER_AGENT,
    SKLAND_APP_USER_AGENT,
    SKLAND_APP_VNAME,
    SKLAND_APP_PLATFORM,
    SIGN_VNAME,
    RespCode,
)
from ..database.models import EndUser


class EndApi:
    """终末地 API 请求引擎"""

    ssl_verify = True
    _sessions: Dict[str, aiohttp.ClientSession] = {}
    _session_lock = asyncio.Lock()

    # ===================== 会话管理 =====================

    @classmethod
    async def get_session(
        cls,
        proxy: Optional[str] = None
    ) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话（会话复用）"""
        async with cls._session_lock:
            key = f"{proxy or 'no_proxy'}"

            # 检查现有会话是否可用
            if key in cls._sessions and not cls._sessions[key].closed:
                return cls._sessions[key]

            # 创建新会话
            connector = aiohttp.TCPConnector(
                ssl=cls.ssl_verify,
                limit=100,
                limit_per_host=30,
            )

            timeout = aiohttp.ClientTimeout(total=30)

            session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                trust_env=True,
            )

            cls._sessions[key] = session
            return session

    # ===================== Token 管理 =====================

    async def refresh_token(self, cred: str, force: bool = False) -> Optional[str]:
        """刷新 Token（从数据库读取，失效时自动刷新）

        Args:
            cred: 用户凭证
            force: 是否强制刷新（忽略 3 分钟缓存）

        Returns:
            token 字符串，失败返回 None
        """
        if not cred:
            return None

        # 1. 先从数据库读取用户信息
        user = await EndUser.select_data_by_cred(cred)

        # 2. 检查是否需要刷新（超过 3 分钟或强制刷新）
        current_time = int(time.time())
        need_refresh = False

        if user and user.token:
            if user.last_cred_request_time:
                # 距离上次请求超过 3 分钟（180 秒）
                if current_time - user.last_cred_request_time > 180:
                    need_refresh = True
                    logger.info(f"[EndUID] Token 超过 3 分钟，需要刷新")
                else:
                    logger.info(f"[EndUID] 使用缓存的 token（距上次请求 {current_time - user.last_cred_request_time} 秒）")
            else:
                # 没有记录时间，需要刷新
                need_refresh = True

            if not need_refresh and not force:
                return user.token
        else:
            # 没有 token，需要刷新
            need_refresh = True

        # 3. 调用刷新 API
        if not need_refresh and not force:
            return user.token if user and user.token else None

        headers = get_refresh_header(cred)
        session = await self.get_session()

        try:
            logger.debug(f"[EndUID][RefreshToken] GET {REFRESH_TOKEN_URL} cred_len={len(cred)}")
            async with session.get(
                REFRESH_TOKEN_URL,
                headers=headers,
            ) as resp:
                if resp.content_type and "json" in resp.content_type:
                    res = await resp.json()
                    logger.debug(f"[EndUID][RefreshToken] response: {res}")
                else:
                    text = await resp.text()
                    logger.error(
                        f"[EndUID] Token 刷新失败: HTTP {resp.status}, body={text[:200]}"
                    )
                    return None

                if res.get("code") == RespCode.OK and res.get("message") == "OK":
                    token = res["data"]["token"]
                    timestamp = res.get("timestamp")

                    # 更新数据库
                    await EndUser.update_data_by_xx(
                        {"cookie": cred},
                        token=token,
                        last_cred_request_time=current_time
                    )

                    logger.info(f"[EndUID] Token 刷新成功 (timestamp={timestamp})")
                    return token
                else:
                    logger.error(f"[EndUID] Token 刷新失败: {res}")
                    return None
        except Exception as e:
            logger.error(f"[EndUID] Token 刷新异常: {e}")
            return None

    # ===================== 通用请求方法 =====================

    async def request(
        self,
        url: str,
        method: str = "POST",
        cred: Optional[str] = None,
        uid: Optional[str] = None,
        game_id: Optional[int] = None,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
        use_device_id: bool = False,
        extra_headers: Optional[dict] = None,
        user_agent: Optional[str] = None,
        accept_encoding: Optional[str] = None,
        platform: Optional[int] = None,
        vname: Optional[str] = None,
    ) -> Optional[dict]:
        """通用请求方法

        Args:
            url: 完整 URL
            method: HTTP 方法（GET/POST）
            cred: 用户凭证
            uid: 游戏 UID
            game_id: 游戏 ID
            params: GET 查询参数
            body: POST 请求体
        """
        if platform is None:
            platform = PLATFORM_ENDFIELD
        if vname is None:
            vname = SIGN_VNAME

        # 1. 获取 Token
        token = await self.refresh_token(cred)
        if not token:
            return None

        # 2. 解析 URL 并构造完整 URL（含查询参数）
        parsed = urlparse(url)
        path = parsed.path

        # 3. 生成签名所需字符串
        query_string = ""
        if params:
            query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
            # 对于 GET 请求，直接在 URL 中拼接参数（避免 aiohttp 自动编码）
            if method == "GET":
                url = f"{url}?{query_string}"

        body_string = ""
        if body:
            body_string = json.dumps(body, separators=(',', ':'))

        if method == "GET":
            payload_string = query_string
        else:  # POST
            payload_string = f"{query_string}{body_string}"

        async def do_request(token: str) -> Optional[dict]:
            effective_user_agent = user_agent
            if not effective_user_agent and extra_headers:
                effective_user_agent = (
                    extra_headers.get("User-Agent")
                    or extra_headers.get("user-agent")
                )
            if not effective_user_agent:
                effective_user_agent = ANDROID_USER_AGENT

            did = ""
            if use_device_id:
                accept_language = None
                referer = None
                if extra_headers:
                    accept_language = (
                        extra_headers.get("Accept-Language")
                        or extra_headers.get("accept-language")
                        or extra_headers.get("language")
                    )
                    referer = (
                        extra_headers.get("Referer")
                        or extra_headers.get("referer")
                        or extra_headers.get("Origin")
                        or extra_headers.get("origin")
                    )
                did = get_device_id(
                    user_agent=effective_user_agent,
                    accept_language=accept_language,
                    referer=referer,
                )
            sign_data = generate_sign(
                token,
                path,
                payload_string,
                platform=str(platform),
                vname=vname,
                did=did,
            )
            headers = get_base_header(
                cred=cred,
                timestamp=sign_data["timestamp"],
                sign=sign_data["sign"],
                platform=platform,
                uid=uid,
                game_id=game_id,
                vname=vname,
                did=did,
                user_agent=effective_user_agent,
                accept_encoding=accept_encoding or "gzip",
            )
            if extra_headers:
                headers.update(extra_headers)

            logger.debug(f"[EndUID][请求头] {json.dumps(headers, indent=2, ensure_ascii=False)}")

            session = await self.get_session()
            try:
                logger.debug(
                    f"[EndUID][Request] {method} {url} uid={uid} game_id={game_id} "
                    f"params={params if method == 'GET' else None} body={body if method != 'GET' else None}"
                )
                async def read_response(resp: aiohttp.ClientResponse) -> dict:
                    if resp.content_type and "json" in resp.content_type:
                        try:
                            return await resp.json()
                        except Exception:
                            text = await resp.text()
                            return {"code": RespCode.REQUEST_ERROR, "data": text}
                    text = await resp.text()
                    return {"code": RespCode.REQUEST_ERROR, "data": text}

                if method == "GET":
                    # 不使用 params 参数，因为我们已经在 URL 中拼接了查询参数
                    async with session.get(url, headers=headers) as resp:
                        res = await read_response(resp)
                        logger.debug(f"[EndUID][Request] response: {res}")

                        if resp.status in [400, 403]:
                            if res.get("code") == RespCode.CRED_INVALID:
                                message = res.get("message", "")
                                if "签到" in message:
                                    logger.info(f"[EndUID] 已签到: {message}")
                                else:
                                    logger.info(f"[EndUID] Cred 失效: {message}")
                            elif res.get("code") == RespCode.TOKEN_INVALID:
                                logger.info(f"[EndUID] Token 失效，准备刷新")
                            return res

                        if resp.status != 200:
                            logger.error(f"[EndUID] 请求失败: {resp.status}")
                            return None

                        return res
                else:  # POST
                    # POST 请求：如果有 query 参数，已经在 URL 中拼接；body 作为 data 传递
                    request_kwargs = {"headers": headers}
                    if body is not None:
                        request_kwargs["data"] = body_string
                    async with session.post(
                        url,
                        **request_kwargs
                    ) as resp:
                        res = await read_response(resp)
                        logger.debug(f"[EndUID][Request] response: {res}")

                        if resp.status in [400, 403]:
                            if res.get("code") == RespCode.CRED_INVALID:
                                message = res.get("message", "")
                                if "签到" in message:
                                    logger.info(f"[EndUID] 已签到: {message}")
                                else:
                                    logger.info(f"[EndUID] Cred 失效: {message}")
                            elif res.get("code") == RespCode.TOKEN_INVALID:
                                logger.info(f"[EndUID] Token 失效，准备刷新")
                            return res

                        if resp.status != 200:
                            logger.error(f"[EndUID] 请求失败: {resp.status}")
                            return None

                        return res
            except Exception as e:
                logger.error(f"[EndUID] 请求异常: {e}")
                return None

        res = await do_request(token)
        return res

    # ===================== 具体 API 方法 =====================

    async def get_binding(self, cred: str) -> Optional[dict]:
        """获取绑定的游戏账号列表"""
        return await self.request(
            url=BINDING_URL,
            method="GET",
            cred=cred,
        )

    async def get_user_info(
        self,
        cred: str,
        extra_headers: Optional[dict] = None,
    ) -> Optional[dict]:
        """获取 Skland 用户信息"""
        effective_user_agent = None
        if extra_headers:
            effective_user_agent = (
                extra_headers.get("User-Agent")
                or extra_headers.get("user-agent")
            )
        if not effective_user_agent:
            effective_user_agent = SKLAND_APP_USER_AGENT

        headers = get_skland_app_headers(user_agent=effective_user_agent)
        headers.update(get_skland_app_security_headers())
        if extra_headers:
            headers.update(extra_headers)

        return await self.request(
            url=USER_INFO_URL,
            method="GET",
            cred=cred,
            use_device_id=True,
            user_agent=effective_user_agent,
            accept_encoding="gzip",
            extra_headers=headers,
            platform=SKLAND_APP_PLATFORM,
            vname=SKLAND_APP_VNAME,
        )

    async def attendance(
        self,
        cred: str,
        uid: str,
    ) -> Optional[dict]:
        """终末地签到"""
        return await self.request(
            url=ENDFIELD_ATTENDANCE_URL,
            method="POST",
            cred=cred,
            uid=uid,
            game_id=GAME_ID_ENDFIELD,
            body={"uid": uid, "gameId": str(GAME_ID_ENDFIELD)},
            use_device_id=False,
            accept_encoding="gzip, deflate, br, zstd",
        )

    async def get_player_info(
        self,
        cred: str,
        uid: str,
        game_id: int = GAME_ID_ENDFIELD,
    ) -> Optional[dict]:
        """获取玩家信息"""
        return await self.request(
            url=GAME_PLAYER_INFO_URL,
            method="GET",
            cred=cred,
            uid=uid,
            game_id=game_id,
            params={"uid": uid, "gameId": game_id},
        )

    async def get_endfield_enums(self, cred: str) -> Optional[dict]:
        """获取终末地枚举数据（道具、角色等）"""
        return await self.request(
            url=ENDFIELD_ENUMS_URL,
            method="GET",
            cred=cred,
        )

    async def get_card_detail(
        self,
        cred: str,
        uid: str,
        server_id: str = "1",
        user_id: Optional[str] = None,
        qq_user_id: Optional[str] = None,
        bot_id: Optional[str] = None,
    ) -> Optional[dict]:
        """获取卡片详情（角色、武器、基地等完整数据）

        Args:
            cred: 森空岛 Cred
            uid: 游戏 UID (roleId)
            server_id: 服务器 ID，默认 "1"
            user_id: 森空岛 用户 ID

        Returns:
            卡片详情数据
        """
        resolved_user_id = user_id
        resolved_server_id = server_id

        if qq_user_id and bot_id:
            stored = await EndUser.select_end_user(uid, qq_user_id, bot_id)
            if stored:
                if not resolved_user_id and stored.skland_user_id:
                    resolved_user_id = stored.skland_user_id

                if stored.server_id:
                    resolved_server_id = stored.server_id

        if not resolved_user_id:
            user_info = await self.get_user_info(cred)
            if user_info and user_info.get("code") == 0:
                skland_user_id = user_info.get("data", {}).get("user", {}).get("id")
                if skland_user_id:
                    resolved_user_id = str(skland_user_id)
                    if qq_user_id and bot_id:
                        await EndUser.update_data_by_uid(
                            uid,
                            bot_id,
                            skland_user_id=resolved_user_id,
                        )

        if not resolved_user_id:
            logger.error("[EndUID] 获取 Skland 用户ID失败，无法请求卡片详情")
            return None

        params = {
            "roleId": uid,
            "serverId": resolved_server_id,
            "userId": resolved_user_id,
        }

        return await self.request(
            url=CARD_DETAIL_URL,
            method="GET",
            cred=cred,
            uid=None,
            game_id=None,
            params=params,
            use_device_id=True,
            extra_headers=get_endfield_web_headers(),
            accept_encoding="gzip, deflate",
        )

    # ===================== OAuth 相关方法（扫码登录）=====================

    async def get_scan_id(self) -> Optional[str]:
        """获取扫码登录的 scanId"""
        headers = get_oauth_header()
        body = {"appCode": APP_CODE}

        session = await self.get_session()

        try:
            logger.debug(f"[EndUID][OAuth] POST {SCAN_LOGIN_API}")
            async with session.post(
                SCAN_LOGIN_API,
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=25)
            ) as resp:
                if not resp.ok:
                    logger.error(f"[EndUID][获取扫码ID] {resp.status} {resp.reason}")
                    return None

                res = await resp.json()
                logger.debug(f"[EndUID][OAuth][scan_login] response: {res}")
                if res.get("status") != 0 or res.get("msg") != "OK":
                    logger.error(f"[EndUID][获取扫码ID] {res}")
                    return None

                scan_id = res["data"]["scanId"]
                logger.info(f"[EndUID] 获取到扫码ID: {scan_id}")
                return scan_id
        except Exception as e:
            logger.error(f"[EndUID][获取扫码ID] {e}")
            return None

    async def get_scan_status(self, scan_id: str) -> Optional[str]:
        """检查扫码状态

        Returns:
            scanCode 或 None（未扫码或超时）
        """
        url = f"{SCAN_STATUS_API}?scanId={scan_id}"
        session = await self.get_session()

        try:
            logger.debug(f"[EndUID][OAuth] GET {url}")
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=25)
            ) as resp:
                if not resp.ok:
                    logger.debug(f"[EndUID][检查扫码状态] {resp.status}")
                    return None

                res = await resp.json()
                logger.debug(f"[EndUID][OAuth][scan_status] response: {res}")
                if res.get("status") != 0:
                    # 未扫码时会返回非0状态，这是正常的
                    return None

                scan_code = res["data"]["scanCode"]
                logger.info(f"[EndUID] 获取到扫码Code: {scan_code}")
                return scan_code
        except Exception as e:
            logger.debug(f"[EndUID][检查扫码状态] {e}")
            return None

    async def get_token_by_scan_code(self, scan_code: str) -> Optional[str]:
        """通过 scanCode 获取 token"""
        headers = get_oauth_header()
        body = {"scanCode": scan_code}

        session = await self.get_session()

        try:
            logger.debug(f"[EndUID][OAuth] POST {TOKEN_BY_SCAN_CODE_API}")
            async with session.post(
                TOKEN_BY_SCAN_CODE_API,
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=25)
            ) as resp:
                if not resp.ok:
                    logger.error(f"[EndUID][获取Token] {resp.status}")
                    return None

                res = await resp.json()
                logger.debug(f"[EndUID][OAuth][token_by_scan] response: {res}")
                if res.get("status") != 0:
                    logger.error(f"[EndUID][获取Token] {res}")
                    return None

                token = res["data"]["token"]
                logger.info(f"[EndUID] 获取到Token（长度: {len(token)}）")
                return token
        except Exception as e:
            logger.error(f"[EndUID][获取Token] {e}")
            return None

    async def get_cred_info_by_token(self, token: str) -> Optional[dict]:
        """通过 token 获取 cred 与 skland_user_id"""
        headers = get_oauth_header()

        # 1. 先获取 OAuth code
        body = {"appCode": APP_CODE, "token": token, "type": 0}

        session = await self.get_session()

        try:
            logger.debug(f"[EndUID][OAuth] POST {OAUTH_API}")
            async with session.post(
                OAUTH_API,
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=25)
            ) as resp:
                if resp.status == 405:
                    logger.error(f"[EndUID][OAUTH API] 405 当前服务暂时无法使用token")
                    return "405"

                if not resp.ok:
                    logger.error(f"[EndUID][OAUTH API] {resp.status}")
                    return None

                res = await resp.json()
                logger.debug(f"[EndUID][OAuth][oauth_code] response: {res}")
                if res.get("status") != 0:
                    logger.error(f"[EndUID][OAUTH API] {res}")
                    return None

                code = res["data"]["code"]
                logger.debug(f"[EndUID] 获取到OAUTH CODE: {code}")

        except Exception as e:
            logger.error(f"[EndUID][OAUTH API] {e}")
            return None

        # 2. 用 code 换取 cred，并从该接口返回中读取 skland_user_id
        body = {"kind": 1, "code": code}
        headers = get_cred_header()

        try:
            logger.debug(f"[EndUID][OAuth] POST {CRED_API}")
            async with session.post(
                CRED_API,
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=25)
            ) as resp:
                if not resp.ok:
                    logger.error(f"[EndUID][CRED API] {resp.status}")
                    return None

                res = await resp.json()
                logger.debug(f"[EndUID][OAuth][generate_cred] response: {res}")
                if res.get("code") != 0:
                    logger.error(f"[EndUID][CRED API] {res}")
                    return None

                data = res.get("data", {}) or {}
                cred = data.get("cred")
                if not cred:
                    logger.error(f"[EndUID][CRED API] missing cred: {res}")
                    return None

                skland_user_id = (
                    data.get("userId")
                    or data.get("user_id")
                    or data.get("uid")
                    or data.get("sklandUserId")
                    or data.get("skland_user_id")
                )
                if skland_user_id is not None:
                    skland_user_id = str(skland_user_id)

                logger.info(f"[EndUID] 获取到Cred（长度: {len(cred)}）")
                return {
                    "cred": cred,
                    "skland_user_id": skland_user_id,
                }
        except Exception as e:
            logger.error(f"[EndUID][CRED API] {e}")
            return None

    async def get_cred_by_token(self, token: str) -> Optional[str]:
        """通过 token 获取 cred（兼容旧方法）"""
        info = await self.get_cred_info_by_token(token)
        if info == "405":
            return "405"
        if not info:
            return None
        return info.get("cred")

    # ===================== Cookie 管理 =====================

    async def get_ck_result(
        self,
        uid: str,
        user_id: str,
        bot_id: str,
    ) -> tuple[bool, Optional[str]]:
        """获取有效 Cookie（四层获取机制）

        Returns:
            (is_self_cookie, cookie)
            - is_self_cookie: True=用户自己的 Cookie, False=公共 Cookie
            - cookie: cred 字符串
        """
        # 1. 尝试获取用户自己的 Cookie
        self_ck = await self.get_self_end_ck(uid, user_id, bot_id)
        if self_ck:
            return True, self_ck

        # 2. 尝试获取随机公共 Cookie
        random_ck = await self.get_end_random_cookie()
        if random_ck:
            return False, random_ck

        # 3. 返回 None（无可用 Cookie）
        return False, None

    async def get_self_end_ck(
        self,
        uid: str,
        user_id: str,
        bot_id: str,
    ) -> Optional[str]:
        """获取用户自己的 Cookie 并验证"""
        # 从数据库查询
        user = await EndUser.select_end_user(uid, user_id, bot_id)
        if not user or not user.cookie:
            return None

        # 检查 Cookie 状态
        if user.cookie_status == "无效":
            return None

        # 验证 Token 可用性
        token = await self.refresh_token(user.cookie)
        if not token:
            # 标记为无效
            await EndUser.mark_invalid(uid, user_id, bot_id)
            return None

        # 更新最后使用时间
        await EndUser.update_last_used_time(uid, user_id, bot_id)

        return user.cookie

    async def get_end_random_cookie(self) -> Optional[str]:
        """从所有有效用户中随机选择 Cookie"""
        # 查询所有有效 Cookie
        users = await EndUser.get_all_valid_users()
        if not users:
            return None

        # 随机选择
        import random
        user = random.choice(users)
        return user.cookie


# 创建全局实例
end_api = EndApi()
