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
    ANDROID_USER_AGENT,
    IOS_USER_AGENT,
    SKLAND_APP_USER_AGENT,
    SKLAND_APP_VNAME,
    SKLAND_APP_PLATFORM,
    SIGN_VNAME,
    ARK_SIGN_VNAME,
    WEB_USER_AGENT,
    RespCode,
)
from ..database.models import EndUser


class CredentialInvalidError(Exception):
    """凭证失效异常（Token 刷新时发现 cred 已过期）"""
    pass


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

        网络失败自动重试最多 3 次；凭证失效抛出 CredentialInvalidError。

        Args:
            cred: 用户凭证
            force: 是否强制刷新（忽略 3 分钟缓存）

        Returns:
            token 字符串，网络失败返回 None

        Raises:
            CredentialInvalidError: 凭证已失效（调用方应标记用户无效）
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

        # 3. 调用刷新 API（带网络重试）
        if not need_refresh and not force:
            return user.token if user and user.token else None

        headers = get_refresh_header(cred)
        session = await self.get_session()
        max_retries = 3
        retry_delay = 1.0

        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(f"[EndUID][RefreshToken] GET {REFRESH_TOKEN_URL} cred_len={len(cred)}")
                proxy = self._get_proxy()
                async with session.get(
                    REFRESH_TOKEN_URL,
                    headers=headers,
                    proxy=proxy,
                ) as resp:
                    if resp.content_type and "json" in resp.content_type:
                        res = await resp.json()
                        logger.debug(f"[EndUID][RefreshToken] response: {res}")
                    else:
                        text = await resp.text()
                        logger.error(
                            f"[EndUID] Token 刷新失败: HTTP {resp.status}, body={text[:200]}"
                        )
                        if attempt < max_retries:
                            logger.warning(f"[EndUID] Token 刷新非JSON响应，第 {attempt}/{max_retries} 次重试")
                            await asyncio.sleep(retry_delay)
                            continue
                        return None

                    code = res.get("code")

                    if code == RespCode.OK and res.get("message") == "OK":
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
                    elif code in (RespCode.CRED_INVALID, RespCode.TOKEN_INVALID, RespCode.LOGIN_EXPIRED):
                        # 凭证失效，不重试，直接抛出
                        logger.warning(f"[EndUID] Token 刷新失败（凭证失效 code={code}）")
                        raise CredentialInvalidError(f"凭证失效 code={code}")
                    else:
                        logger.error(f"[EndUID] Token 刷新失败: {res}")
                        if attempt < max_retries:
                            logger.warning(f"[EndUID] Token 刷新未知错误，第 {attempt}/{max_retries} 次重试")
                            await asyncio.sleep(retry_delay)
                            continue
                        return None
            except CredentialInvalidError:
                raise
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"[EndUID] Token 刷新异常（第 {attempt}/{max_retries} 次重试）: {e}")
                    await asyncio.sleep(retry_delay)
                    continue
                logger.error(f"[EndUID] Token 刷新异常（已重试{max_retries}次）: {e}")
                return None

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
        try:
            token = await self.refresh_token(cred)
        except CredentialInvalidError:
            logger.warning(f"[EndUID] 凭证失效，请求中止")
            return None
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

                proxy = self._get_proxy()

                if method == "GET":
                    # 不使用 params 参数，因为我们已经在 URL 中拼接了查询参数
                    async with session.get(url, headers=headers, proxy=proxy) as resp:
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

                        if resp.status == 401:
                            logger.warning(f"[EndUID] 请求返回 401，凭证失效")
                            return {"code": RespCode.CRED_INVALID, "message": "HTTP 401 Unauthorized"}

                        if resp.status != 200:
                            logger.error(f"[EndUID] 请求失败: {resp.status}")
                            return None

                        return res
                else:  # POST
                    # POST 请求：如果有 query 参数，已经在 URL 中拼接；body 作为 data 传递
                    request_kwargs = {"headers": headers, "proxy": proxy}
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

                        if resp.status == 401:
                            logger.warning(f"[EndUID] 请求返回 401，凭证失效")
                            return {"code": RespCode.CRED_INVALID, "message": "HTTP 401 Unauthorized"}

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
            use_device_id=True,
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
            accept_encoding="gzip, deflate",
        )

    async def ark_attendance(
        self,
        cred: str,
        uid: str,
    ) -> Optional[dict]:
        """明日方舟签到"""
        return await self.request(
            url=GAME_ATTENDANCE_URL,
            method="POST",
            cred=cred,
            uid=uid,
            game_id=1,
            body={"uid": uid, "gameId": 1},
            use_device_id=False,
            platform=1,
            vname=ARK_SIGN_VNAME,
            user_agent=IOS_USER_AGENT,
            accept_encoding="gzip",
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

    async def get_indie_hard(
        self,
        cred: str,
        uid: str,
        server_id: str = "1",
        user_id: Optional[str] = None,
        qq_user_id: Optional[str] = None,
        bot_id: Optional[str] = None,
    ) -> Optional[dict]:
        """获取影拓丰碑详情（每期勋章 + 所有副本 + 通关阵容）

        Args:
            cred: 森空岛 Cred
            uid: 游戏 UID (roleId)
            server_id: 服务器 ID
            user_id: 森空岛用户 ID（不传时从 EndUser/user_info 回填）
            qq_user_id / bot_id: 用于补 skland_user_id
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
                skland_user_id = (
                    user_info.get("data", {}).get("user", {}).get("id")
                )
                if skland_user_id:
                    resolved_user_id = str(skland_user_id)
                    if qq_user_id and bot_id:
                        await EndUser.update_data_by_uid(
                            uid, bot_id, skland_user_id=resolved_user_id,
                        )

        if not resolved_user_id:
            logger.error("[EndUID] 获取 Skland 用户 ID 失败，无法请求 indie-hard")
            return None

        params = {
            "roleId": uid,
            "serverId": resolved_server_id,
            "userId": resolved_user_id,
        }

        return await self.request(
            url=INDIE_HARD_URL,
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
        body = {}

        session = await self.get_session()
        proxy = self._get_proxy()

        try:
            logger.debug(f"[EndUID][OAuth] POST {SCAN_LOGIN_API}")
            async with session.post(
                SCAN_LOGIN_API,
                headers=headers,
                json=body,
                proxy=proxy,
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
        proxy = self._get_proxy()

        try:
            logger.debug(f"[EndUID][OAuth] GET {url}")
            async with session.get(
                url,
                proxy=proxy,
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

    async def get_token_by_scan_code(
        self, scan_code: str
    ) -> Optional[dict]:
        """通过 scanCode 获取 token 和 deviceToken

        Returns:
            {"token": str, "device_token": str} 或 None
        """
        headers = get_oauth_header()
        body = {"scanCode": scan_code}

        session = await self.get_session()
        proxy = self._get_proxy()

        try:
            logger.debug(f"[EndUID][OAuth] POST {TOKEN_BY_SCAN_CODE_API}")
            async with session.post(
                TOKEN_BY_SCAN_CODE_API,
                headers=headers,
                json=body,
                proxy=proxy,
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

                data = res.get("data", {})
                token = data.get("token", "")
                device_token = data.get("deviceToken", "")
                logger.info(
                    f"[EndUID] 获取到Token（长度: {len(token)}）"
                    f", deviceToken={'有' if device_token else '无'}"
                )
                return {"token": token, "device_token": device_token}
        except Exception as e:
            logger.error(f"[EndUID][获取Token] {e}")
            return None

    async def get_cred_info_by_token(self, token: str) -> Optional[dict]:
        """通过 token 获取 cred 与 skland_user_id"""
        headers = get_oauth_header()

        # 1. 先获取 OAuth code
        body = {"appCode": APP_CODE, "token": token, "type": 0}

        session = await self.get_session()
        proxy = self._get_proxy()

        try:
            logger.debug(f"[EndUID][OAuth] POST {OAUTH_API}")
            async with session.post(
                OAUTH_API,
                headers=headers,
                json=body,
                proxy=proxy,
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
        try:
            token = await self.refresh_token(user.cookie)
        except CredentialInvalidError:
            # 凭证确认失效，标记为无效
            logger.warning(f"[EndUID] {uid} 凭证失效，标记为无效")
            await EndUser.mark_invalid(uid, user_id, bot_id)
            return None
        if not token:
            # 网络错误，不标记无效
            logger.warning(f"[EndUID] {uid} Token 刷新失败（网络错误），跳过")
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



    @staticmethod
    def _get_proxy() -> Optional[str]:
        from ...end_config.config_default import EndConfig
        url = EndConfig.get_config("LocalProxyUrl").data
        return url if url else None

    async def get_gacha_grant_token(
        self, login_token: str, device_token: str = ""
    ) -> Optional[str]:
        """通过 login token 获取抽卡 grant token"""
        session = await self.get_session()
        proxy = self._get_proxy()
        try:
            grant_body = {
                "type": 1,
                "appCode": "be36d44aa36bfb5b",
                "token": login_token,
            }
            if device_token:
                grant_body["deviceToken"] = device_token
            async with session.post(
                "https://as.hypergryph.com/user/oauth2/v2/grant",
                json=grant_body,
                proxy=proxy,
            ) as resp:
                grant_res = await resp.json()

            logger.debug(f"[EndUID][Gacha] grant response: {grant_res}")

            grant_status = grant_res.get("status")
            if grant_status != 0:
                msg = grant_res.get("msg", "未知错误")
                logger.warning(
                    f"[EndUID][Gacha] OAuth grant 失败: "
                    f"status={grant_status}, msg={msg}"
                )
                return None

            grant_data = grant_res.get("data") or {}
            grant_token = grant_data.get("token")
            if not grant_token:
                logger.error(
                    f"[EndUID][Gacha] grant 响应缺少 token: {grant_res}"
                )
                return None

            logger.debug(
                f"[EndUID][Gacha] grant_token={grant_token[:8]}..."
            )
            return grant_token

        except Exception as e:
            logger.warning(
                f"[EndUID][Gacha] 获取 gacha grant token 异常: {e}"
            )
            return None

    async def get_u8_token_by_grant(
        self, grant_token: str, binding_uid: str
    ) -> Optional[str]:
        """通过已获取的 grant token + binding uid 获取 u8_token"""
        session = await self.get_session()
        proxy = self._get_proxy()
        try:
            async with session.post(
                "https://binding-api-account-prod.hypergryph.com"
                "/account/binding/v1/u8_token_by_uid",
                json={"uid": binding_uid, "token": grant_token},
                proxy=proxy,
            ) as resp:
                u8_res = await resp.json()

            logger.debug(
                f"[EndUID][Gacha] u8_token_by_uid response: {u8_res}"
            )

            u8_data = u8_res.get("data") or {}
            u8_token = u8_data.get("token")
            if not u8_token:
                msg = u8_res.get("msg", "未知错误")
                logger.error(f"[EndUID][Gacha] 获取 u8_token 失败: {msg}")
                return None

            logger.info(
                f"[EndUID][Gacha] 获取 u8_token 成功: {u8_token[:8]}..."
            )
            return u8_token

        except Exception as e:
            logger.error(f"[EndUID][Gacha] 获取 u8_token 异常: {e}")
            return None

    async def get_u8_token(
        self, token: str, uid: str, device_token: str = ""
    ) -> Optional[str]:
        """通过 login token 获取 u8_token（便捷方法）"""
        grant_token = await self.get_gacha_grant_token(token, device_token)
        if not grant_token:
            return None
        return await self.get_u8_token_by_grant(grant_token, uid)

    async def _gacha_request(
        self,
        url: str,
        params: dict,
    ) -> Optional[dict]:
        """抽卡记录通用请求（使用复用会话，无需 Skland 签名）

        Args:
            url: 完整 API URL
            params: 查询参数

        Returns:
            JSON 响应或 None
        """
        session = await self.get_session()
        proxy = self._get_proxy()

        try:
            logger.debug(
                f"[EndUID][Gacha] GET {url} params={list(params.keys())}"
            )
            async with session.get(url, params=params, proxy=proxy) as resp:
                if resp.content_type and "json" in resp.content_type:
                    res = await resp.json()
                else:
                    text = await resp.text()
                    logger.error(
                        f"[EndUID][Gacha] 非 JSON 响应: HTTP {resp.status}, body={text[:200]}"
                    )
                    return None

                logger.debug(f"[EndUID][Gacha] response: {res}")

                if resp.status != 200:
                    logger.error(f"[EndUID][Gacha] 请求失败: HTTP {resp.status}")
                    return None

                return res
        except Exception as e:
            logger.error(f"[EndUID][Gacha] 请求异常: {e}")
            return None

    async def get_gacha_char_record(
        self,
        u8_token: str,
        server_id: str = "1",
        pool_type: str = "E_CharacterGachaPoolType_Special",
        seq_id: Optional[str] = None,
        lang: str = "zh-cn",
    ) -> Optional[dict]:
        """获取角色寻访记录

        Args:
            u8_token: 游戏内抽卡页面的 u8_token
            server_id: 服务器 ID
            pool_type: 池类型枚举字符串
            seq_id: 分页用序列 ID（传入上一页最后一条的 seqId）
            lang: 语言

        Returns:
            角色寻访记录
        """
        params = {
            "token": u8_token,
            "server_id": server_id,
            "pool_type": pool_type,
            "lang": lang,
        }
        if seq_id:
            params["seq_id"] = seq_id

        return await self._gacha_request(
            url=GACHA_CHAR_RECORD_URL,
            params=params,
        )

    async def get_gacha_weapon_pools(
        self,
        u8_token: str,
        server_id: str = "1",
        lang: str = "zh-cn",
    ) -> Optional[dict]:
        """获取武器寻访池列表

        Args:
            u8_token: 游戏内抽卡页面的 u8_token
            server_id: 服务器 ID
            lang: 语言

        Returns:
            武器池列表
        """
        params = {
            "token": u8_token,
            "server_id": server_id,
            "lang": lang,
        }

        return await self._gacha_request(
            url=GACHA_WEAPON_POOL_LIST_URL,
            params=params,
        )

    async def get_gacha_weapon_record(
        self,
        u8_token: str,
        server_id: str = "1",
        pool_id: str = "",
        seq_id: Optional[str] = None,
        lang: str = "zh-cn",
    ) -> Optional[dict]:
        """获取武器寻访记录

        Args:
            u8_token: 游戏内抽卡页面的 u8_token
            server_id: 服务器 ID
            pool_id: 武器池 ID
            seq_id: 分页用序列 ID
            lang: 语言

        Returns:
            武器寻访记录
        """
        params = {
            "token": u8_token,
            "server_id": server_id,
            "pool_id": pool_id,
            "lang": lang,
        }
        if seq_id:
            params["seq_id"] = seq_id

        return await self._gacha_request(
            url=GACHA_WEAPON_RECORD_URL,
            params=params,
        )

    # ===================== 公告相关方法 =====================

    ann_list_data: list = []
    ann_list_cache_time: float = 0  # 公告列表缓存时间戳
    ann_map: dict = {}

    ANN_LIST_CACHE_DURATION = 600  # 公告列表缓存有效期：10分钟（600秒）

    # 森空岛公开 Web API 使用独立短期 token（非用户 cred token），由 /web/v1/auth/refresh 颁发
    _web_public_token: str = ""
    _web_public_token_time: float = 0
    WEB_PUBLIC_TOKEN_TTL = 1500  # 25 分钟，到期前主动刷新

    async def _web_public_refresh_token(self, force: bool = False) -> Optional[str]:
        """获取森空岛公开 Web API 使用的 token。

        该 token 由 /web/v1/auth/refresh 直接颁发，无需用户登录。
        首次调用时使用空 token 签名，服务端会返回一个短期 token，
        后续对 /web/v1/home/index、/web/v1/item 等公开接口的请求使用该 token 作为 HMAC 密钥。
        """
        current_time = time.time()
        if (
            not force
            and EndApi._web_public_token
            and (current_time - EndApi._web_public_token_time) < self.WEB_PUBLIC_TOKEN_TTL
        ):
            return EndApi._web_public_token

        path = "/web/v1/auth/refresh"
        sign_data = generate_sign(
            token="",
            path=path,
            query_or_body="",
            platform="3",
            vname=SIGN_VNAME,
            did="",
        )
        headers = {
            "platform": "3",
            "timestamp": sign_data["timestamp"],
            "dId": "",
            "vName": SIGN_VNAME,
            "sign": sign_data["sign"],
            "User-Agent": WEB_USER_AGENT,
            "Referer": "https://www.skland.com/",
            "Accept": "application/json",
        }

        session = await self.get_session()
        try:
            async with session.get(
                SKLAND_WEB_REFRESH_URL,
                headers=headers,
                proxy=self._get_proxy(),
            ) as resp:
                res = await resp.json()
        except Exception as e:
            logger.error(f"[EndUID][Ann] 获取 web token 异常: {e}")
            return None

        if res.get("code") != 0:
            logger.error(f"[EndUID][Ann] 获取 web token 失败: {res}")
            return None

        token = res.get("data", {}).get("token")
        if not token:
            logger.error(f"[EndUID][Ann] 获取 web token 响应缺少 token 字段: {res}")
            return None

        EndApi._web_public_token = token
        EndApi._web_public_token_time = current_time
        logger.info("[EndUID][Ann] 刷新 web token 成功")
        return token

    async def _web_public_get(
        self,
        path: str,
        params: Optional[dict] = None,
    ) -> Optional[dict]:
        """调用公开 Web API（自动获取 token 并签名，token 失效自动刷新重试一次）"""
        query_string = ""
        if params:
            query_string = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"https://zonai.skland.com{path}" + (f"?{query_string}" if query_string else "")

        async def do_request(token: str) -> Optional[dict]:
            sign_data = generate_sign(
                token=token,
                path=path,
                query_or_body=query_string,
                platform="3",
                vname=SIGN_VNAME,
                did="",
            )
            headers = {
                "platform": "3",
                "timestamp": sign_data["timestamp"],
                "dId": "",
                "vName": SIGN_VNAME,
                "sign": sign_data["sign"],
                "User-Agent": WEB_USER_AGENT,
                "Referer": "https://www.skland.com/",
                "Accept": "application/json",
            }
            session = await self.get_session()
            try:
                async with session.get(
                    url,
                    headers=headers,
                    proxy=self._get_proxy(),
                ) as resp:
                    return await resp.json()
            except Exception as e:
                logger.error(f"[EndUID][Ann] 请求 {path} 异常: {e}")
                return None

        token = await self._web_public_refresh_token()
        if not token:
            return None

        res = await do_request(token)
        if res is None:
            return None

        # token 失效时服务端返回 code=10000 "请求异常"，刷新 token 后再试一次
        if res.get("code") == RespCode.REQUEST_ERROR:
            logger.info(f"[EndUID][Ann] token 可能已失效，强制刷新后重试: {path}")
            token = await self._web_public_refresh_token(force=True)
            if not token:
                return None
            res = await do_request(token)

        return res

    async def get_ann_list(self, is_cache: bool = False, page_size: int = 18) -> list:
        """获取森空岛公告列表（纯 HTTP 签名调用）

        Args:
            is_cache: 是否使用缓存
            page_size: 目标条数（通过分页累计）

        Returns:
            公告列表
        """
        current_time = time.time()
        cache_valid = (
            self.ann_list_data
            and (current_time - self.ann_list_cache_time) < self.ANN_LIST_CACHE_DURATION
        )
        if is_cache and cache_valid:
            logger.debug(
                f"[EndUID][Ann] 使用缓存的公告列表（距上次请求 "
                f"{int(current_time - self.ann_list_cache_time)} 秒）"
            )
            return self.ann_list_data

        # 服务端 pageSize 上限为 10，超过即 400 参数错误，需要分页累计
        per_page = 10
        collected_raw: list = []
        page_token = ""

        while len(collected_raw) < page_size:
            params: Dict[str, str] = {"pageSize": str(per_page)}
            if page_token:
                params["pageToken"] = page_token
            params["sortType"] = "2"
            params["gameId"] = str(SKLAND_GAME_ID_ENDFIELD)
            params["cateId"] = str(SKLAND_CATE_ID_ENDFIELD)

            res = await self._web_public_get("/web/v1/home/index", params)
            if not res or res.get("code") != 0:
                logger.error(f"[EndUID][Ann] 获取公告列表失败: {res}")
                break

            data = res.get("data", {}) or {}
            page_items = data.get("list", []) or []
            if not page_items:
                break
            collected_raw.extend(page_items)

            page_token = data.get("pageToken", "") or ""
            if not page_token:
                break

        # 转换为与旧实现一致的结构
        formatted: list = []
        for entry in collected_raw:
            item = entry.get("item", {}) or {}
            user = entry.get("user", {}) or {}
            if not item.get("id"):
                continue

            cover_url = ""
            if item.get("imageCover"):
                cover_url = item["imageCover"].get("url", "")
            elif item.get("imageListSlice"):
                cover_url = item["imageListSlice"][0].get("url", "")
            elif item.get("videoListSlice"):
                video = item["videoListSlice"][0]
                cover_url = video.get("cover", {}).get("url", "")

            created_ts = (
                item.get("publishedAtTs")
                or item.get("timestamp")
                or 0
            )

            formatted.append({
                "id": item.get("id"),
                "title": item.get("title", ""),
                "coverUrl": cover_url,
                "createdAtTs": created_ts,
                "userName": user.get("nickname", ""),
                "userAvatar": user.get("avatar", ""),
                "userIpLocation": user.get("latestIpLocation", ""),
                "viewKind": item.get("viewKind"),
                "gameId": item.get("gameId"),
                "cateId": item.get("cateId"),
            })

        seen_ids = set()
        unique_list = []
        for it in formatted:
            if it["id"] in seen_ids:
                continue
            seen_ids.add(it["id"])
            unique_list.append(it)

        self.ann_list_data = unique_list[:page_size]
        self.ann_list_cache_time = time.time()
        logger.info(f"[EndUID][Ann] 获取到 {len(self.ann_list_data)} 条公告")
        return self.ann_list_data

    async def get_ann_detail(self, post_id) -> Optional[dict]:
        """获取公告详情（纯 HTTP 签名调用）

        Args:
            post_id: 公告 ID

        Returns:
            公告详情
        """
        post_id_str = str(post_id)
        if post_id_str in self.ann_map:
            return self.ann_map[post_id_str]

        res = await self._web_public_get("/web/v1/item", {"id": post_id_str})
        if not res or res.get("code") != 0:
            logger.error(f"[EndUID][Ann] 获取公告详情失败 id={post_id}: {res}")
            return None

        data = res.get("data", {}) or {}
        item = data.get("item", {}) or {}
        user = data.get("user", {}) or {}

        images = [
            {
                "url": img.get("url", ""),
                "width": img.get("width", 0),
                "height": img.get("height", 0),
            }
            for img in item.get("imageListSlice", []) or []
        ]
        videos = [
            {
                "url": v.get("url", ""),
                "coverUrl": v.get("cover", {}).get("url", ""),
            }
            for v in item.get("videoListSlice", []) or []
        ]

        # textSlice 的存储顺序是乱的，真实显示顺序在 format 字段里。
        # 按 format.data 遍历段落，拼接每个段落内的 text/link 片段（contentId 指向 textSlice.id），
        # 得到与原帖一致的阅读顺序。
        text_lookup = {
            str(t.get("id")): t.get("c", "")
            for t in item.get("textSlice", []) or []
        }
        ordered_text: list = []
        fmt_raw = item.get("format", "") or ""
        if fmt_raw:
            try:
                fmt_obj = json.loads(fmt_raw)
                for node in fmt_obj.get("data", []) or []:
                    if node.get("type") != "paragraph":
                        continue
                    parts = []
                    for c in node.get("contents", []) or []:
                        if c.get("type") in ("text", "link"):
                            cid = c.get("contentId")
                            if cid is not None:
                                parts.append(text_lookup.get(str(cid), ""))
                    ordered_text.append("".join(parts))
            except Exception as e:
                logger.warning(f"[EndUID][Ann] format 解析失败 id={post_id}: {e}")
                ordered_text = []
        if not ordered_text:
            # 兜底：format 缺失或解析失败时退回原始存储顺序
            ordered_text = [t.get("c", "") for t in item.get("textSlice", []) or []]

        created_ts = (
            item.get("publishedAtTs")
            or item.get("timestamp")
            or 0
        )

        result = {
            "id": item.get("id"),
            "title": item.get("title", ""),
            "createdAtTs": created_ts,
            "userName": user.get("nickname", ""),
            "userAvatar": user.get("avatar", ""),
            "userIpLocation": user.get("latestIpLocation", ""),
            "images": images,
            "videos": videos,
            "textContent": ordered_text,
            "format": item.get("format", ""),
        }

        self.ann_map[post_id_str] = result
        return result


# 创建全局实例
end_api = EndApi()
