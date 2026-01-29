"""HTTP 请求工具和常量"""
import os
import subprocess
import time
from enum import IntEnum
from pathlib import Path
from typing import Optional

class RespCode(IntEnum):
    """森空岛 API 响应码"""
    OK = 0                  # 请求成功
    OK_HTTP = 200           # HTTP 成功

    # 认证相关
    TOKEN_INVALID = 220     # 登录过期
    CRED_INVALID = 10001    # Cred 失效或已签到

    # 请求相关
    REQUEST_ERROR = 10000   # 请求异常
    BAD_REQUEST = 400       # 错误请求
    FORBIDDEN = 403         # 禁止访问
    METHOD_NOT_ALLOWED = 405  # 方法不允许（可能是IP受限）

    # 验证码相关
    CAPTCHA_ERROR = 130     # 验证码错误
    CAPTCHA_EXPIRED = 132   # 验证码过期



# iOS User-Agent
IOS_USER_AGENT = "Skland/1.21.0 (com.hypergryph.skland; build:102100065; iOS 17.6.0) Alamofire/5.7.1"

# Android User-Agent
ANDROID_USER_AGENT = "Mozilla/5.0 (Linux; Android 12; SM-S9280 Build/V417IR; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/101.0.4951.61 Mobile Safari/537.36; SKLand/1.52.1"

SKLAND_APP_USER_AGENT = (
    "Skland/1.52.1 (com.hypergryph.skland; build:105201003; Android 32; ) Okhttp/4.11.0"
)

# Web User-Agent（用于 CRED 兑换）
WEB_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"

SIGN_VNAME = "1.0.0"

SKLAND_APP_VNAME = "1.52.1"
SKLAND_APP_VCODE = "105201003"
SKLAND_APP_PLATFORM = 1

SKLAND_APP_LANGUAGE = "zh-cn"
SKLAND_APP_OS = "32"
SKLAND_APP_NID = "1"
SKLAND_APP_CHANNEL = "OF"
SKLAND_APP_MANUFACTURER = "Samsung"


def get_device_id(
    user_agent: Optional[str] = None,
    accept_language: Optional[str] = None,
    referer: Optional[str] = None,
    platform: Optional[str] = None,
) -> str:
    """获取设备 ID（用于需要 dId 的接口）

    与 arknights-plugin 行为一致：每次请求重新生成，不缓存、不落盘。
    """
    return _get_device_id_from_smsdk(
        user_agent=user_agent,
        accept_language=accept_language,
        referer=referer,
        platform=platform,
    )


def _find_smsdk_path() -> Optional[Path]:
    current = Path(__file__).resolve()
    local = current.parent / "sm.sdk.js"
    if local.exists():
        return local
    for parent in current.parents:
        candidate = parent / "arknights-plugin" / "utils" / "sm.sdk.js"
        if candidate.exists():
            return candidate
    return None


def _get_device_id_from_smsdk(
    user_agent: Optional[str] = None,
    accept_language: Optional[str] = None,
    referer: Optional[str] = None,
    platform: Optional[str] = None,
) -> str:
    sdk_path = _find_smsdk_path()
    if not sdk_path:
        raise RuntimeError("smsdk failed: sm.sdk.js not found")

    runner_path = Path(__file__).resolve().parent / "smsdk_runner.js"
    env = os.environ.copy()
    if user_agent:
        env["SMSDK_USER_AGENT"] = user_agent
    if accept_language:
        env["SMSDK_ACCEPT_LANGUAGE"] = accept_language
    if referer:
        env["SMSDK_REFERER"] = referer
    if platform:
        env["SMSDK_PLATFORM"] = platform

    try:
        result = subprocess.run(
            ["node", str(runner_path), str(sdk_path)],
            cwd=str(sdk_path.parent),
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("smsdk failed: node not found, please install Node.js") from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"smsdk failed: code={result.returncode} stderr={stderr}")

    output = (result.stdout or "").strip().splitlines()
    device_id = output[-1].strip() if output else ""
    if not device_id:
        raise RuntimeError("smsdk failed: empty device id")
    return device_id


def check_node_version() -> Optional[str]:
    try:
        result = subprocess.run(
            ["node", "-v"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None

    if result.returncode != 0:
        return None

    version = (result.stdout or "").strip()
    return version or None



def get_base_header(
    cred: str,
    timestamp: str,
    sign: str,
    platform: int = 3,
    uid: Optional[str] = None,
    game_id: Optional[int] = None,
    vname: str = SIGN_VNAME,
    did: str = "",
    user_agent: Optional[str] = None,
    accept_encoding: str = "gzip",
) -> dict:
    """构造基础请求头

    Args:
        cred: 用户凭证
        timestamp: 时间戳（字符串）
        sign: 签名
        platform: 平台 ID（3=终末地）
        uid: 用户游戏 UID
        game_id: 游戏 ID

    Returns:
        完整的 HTTP 请求头字典
    """
    if not user_agent:
        user_agent = ANDROID_USER_AGENT

    headers = {
        "User-Agent": user_agent,
        "Accept-Encoding": accept_encoding,
        "Content-Type": "application/json",
        "cred": cred,
        "timestamp": timestamp,
        "sign": sign,
        "vName": vname,
        "dId": did,
        "platform": str(platform),
    }

    # 如果需要携带角色信息
    if uid and game_id:
        headers["sk-game-role"] = f"{platform}_{uid}_{game_id}"

    return headers


def get_endfield_web_headers() -> dict:
    """终末地 Web 端接口需要的额外请求头"""
    return {
        "Accept": "*/*",
        "Origin": "https://game.skland.com",
        "X-Requested-With": "com.hypergryph.skland",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://game.skland.com/",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Host": "zonai.skland.com",
        "Connection": "keep-alive",
    }


def _guess_manufacturer(user_agent: Optional[str]) -> str:
    if not user_agent:
        return SKLAND_APP_MANUFACTURER
    ua = user_agent.lower()
    if "samsung" in ua or "sm-" in ua:
        return "Samsung"
    if "xiaomi" in ua or "mi " in ua or "redmi" in ua or "poco" in ua:
        return "Xiaomi"
    if "huawei" in ua or "honor" in ua:
        return "Huawei"
    if "oneplus" in ua:
        return "OnePlus"
    if "oppo" in ua:
        return "Oppo"
    if "vivo" in ua:
        return "Vivo"
    return SKLAND_APP_MANUFACTURER


def get_skland_app_headers(user_agent: Optional[str] = None) -> dict:
    """Skland App 接口所需的额外请求头"""
    return {
        "language": SKLAND_APP_LANGUAGE,
        "os": SKLAND_APP_OS,
        "nId": SKLAND_APP_NID,
        "vCode": SKLAND_APP_VCODE,
        "channel": SKLAND_APP_CHANNEL,
        "manufacturer": _guess_manufacturer(user_agent),
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }


def get_refresh_header(cred: str) -> dict:
    """获取 Token 刷新请求头

    Token 刷新不需要签名，只需要 cred
    """
    return {
        "cred": cred,
        "User-Agent": IOS_USER_AGENT,
        "Content-Type": "application/json",
    }


def get_oauth_header() -> dict:
    """获取 OAuth 请求头（扫码登录）"""
    return {
        "User-Agent": IOS_USER_AGENT,
        "Content-Type": "application/json;charset=utf-8",
    }


def get_cred_header() -> dict:
    """获取 CRED 兑换请求头（扫码登录）"""
    accept_language = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    return {
        "content-type": "application/json",
        "user-agent": WEB_USER_AGENT,
        "referer": "https://www.skland.com/",
        "origin": "https://www.skland.com",
        "dId": get_device_id(
            user_agent=WEB_USER_AGENT,
            accept_language=accept_language,
            referer="https://www.skland.com/",
        ),
        "platform": "3",
        "timestamp": str(int(time.time())),
        "vName": "1.0.0",
    }
