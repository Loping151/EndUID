"""森空岛签名算法"""
import hashlib
import hmac
import json
import time
from typing import Optional


def generate_sign(
    token: str,
    path: str,
    query_or_body: str = "",
    timestamp: Optional[int] = None,
    platform: str = "3",
    vname: str = "1.0.0",
    did: str = "",
) -> dict:
    """生成森空岛 API 签名

    签名算法：
    1. 构造签名字符串：path + query_or_body + timestamp + header_json
    2. HMAC-SHA256 加密（使用 token 作为密钥）
    3. MD5 二次加密

    Args:
        token: 从 refresh API 获取的 token
        path: API 路径（如 /api/v1/game/player/binding）
        query_or_body:
            - GET 请求：URL 查询参数（如 "uid=123&gameId=1"）
            - POST 请求：JSON body 字符串
        timestamp: 时间戳（秒）

    Returns:
        {
            "sign": "生成的签名",
            "timestamp": "时间戳字符串"
        }
    """
    from gsuid_core.logger import logger

    # 1. 获取时间戳
    if timestamp is None:
        timestamp = int(time.time())

    # 2. 构造 Header 对象（用于签名）
    header_for_sign = {
        "platform": str(platform),
        "timestamp": str(timestamp),
        "dId": did,
        "vName": vname,
    }
    # 注意：JSON 序列化不能有空格
    header_json = json.dumps(header_for_sign, separators=(',', ':'))

    # 3. 构造签名字符串
    sign_string = path + query_or_body + str(timestamp) + header_json

    logger.debug(f"[签名调试] path={path}")
    logger.debug(f"[签名调试] query_or_body={query_or_body}")
    logger.debug(f"[签名调试] timestamp={timestamp}")
    logger.debug(f"[签名调试] header_json={header_json}")
    logger.debug(f"[签名调试] sign_string={sign_string}")
    logger.debug(f"[签名调试] token={token[:20]}...")

    # 4. HMAC-SHA256 加密
    hmac_hash = hmac.new(
        token.encode('utf-8'),
        sign_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    # 5. MD5 二次加密
    md5_hash = hashlib.md5(hmac_hash.encode('utf-8')).hexdigest()

    logger.debug(f"[签名调试] hmac_hash={hmac_hash}")
    logger.debug(f"[签名调试] md5_hash={md5_hash}")

    return {
        "sign": md5_hash,
        "timestamp": str(timestamp),
    }



def sign_get_request(
    token: str,
    path: str,
    params: dict = None,
    platform: str = "3",
    vname: str = "1.0.0",
    did: str = "",
) -> dict:
    """为 GET 请求生成签名"""
    query_string = ""
    if params:
        query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])

    return generate_sign(token, path, query_string, platform=platform, vname=vname, did=did)


def sign_post_request(
    token: str,
    path: str,
    body: dict = None,
    platform: str = "3",
    vname: str = "1.0.0",
    did: str = "",
) -> dict:
    """为 POST 请求生成签名"""
    body_string = ""
    if body:
        # 注意：JSON 序列化不能有空格
        body_string = json.dumps(body, separators=(',', ':'))

    return generate_sign(token, path, body_string, platform=platform, vname=vname, did=did)
