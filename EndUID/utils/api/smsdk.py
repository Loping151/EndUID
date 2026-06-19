"""
uid    = uuid4
priId  = md5(uid)[:16]
ep     = base64(RSA-PKCS1v15(uid, publicKey))
字段   = base64(DES-ECB-ZeroPad(value, key)) 按 ConfusionInfo 混淆
data   = hex(AES-128-CBC-ZeroPad(base64(gzip(json(fp))), priId, iv))
dId    = "D" + base64(json({appId, organization, ep, data, os, encode:5, compress:2}))
"""
import base64
import hashlib
import json
import struct
import time
import uuid
import zlib
from datetime import datetime
from typing import Optional

from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.asymmetric import padding as _rsa_pad
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.serialization import load_der_public_key

ORGANIZATION = "UWXspnCCJN4sfYlNfqps"
APPID = "default"
PUBLIC_KEY = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCmxMNr7n8ZeT0tE1R9j/mPixoinPkeM"
    "+k4VGIn/s0k7N5rJAfnZ0eMER+QhwFvshzo0LNmeUkpR8uIlU/GEVr8mN28sKmwd2gpyg"
    "qj0ePnBmOW4v0ZVwbSYK+izkhVFk2V/doLoMbWy6b+UnA8mkjvg0iYWRByfRsK2gdl7ll"
    "qCwIDAQAB"
)
AES_IV = b"0102030405060708"

# ConfusionInfo（organization 对应的 Protocol 4 配置）：明文字段名 -> 混淆名/是否 DES/DES key
CONFUSION = {
    "appId": ("iq", True, "7vchhrai"),
    "canvas": ("eu", True, "tqfgzsel"),
    "clientSize": ("se", True, "dd0dafz1"),
    "organization": ("jf", True, "vljf9vi2"),
    "os": ("ov", True, "itbukumg"),
    "platform": ("sa", True, "2rupj51i"),
    "plugins": ("ev", True, "pxmuq21g"),
    "pmf": ("uo", True, "jmvbmifl"),
    "referer": ("dr", True, "ifcbsrt8"),
    "res": ("lh", True, "0s4hrauk"),
    "rtype": ("vd", True, "9gbq1eu1"),
    "sdkver": ("bp", True, "niaspcbt"),
    "status": ("gr", True, "7ruo0eyq"),
    "subVersion": ("oi", True, "q71hy97l"),
    "svm": ("bg", True, "ob67y8pr"),
    "time": ("xh", True, "x84559zm"),
    "timezone": ("ae", True, "mt17t5cb"),
    "tn": ("da", True, "0unt9ax1"),
    "trees": ("kl", True, "sjlqw8zu"),
    "ua": ("hp", True, "n4h67t3z"),
    "url": ("vf", True, "516c7ajz"),
    "vpw": ("fu", True, "n4o2up73"),
    "box": ("sp", False, ""),
}

_MOBILE_RE = ("Android", "iPhone", "iPad", "iPod")


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _des_field(value: str, key: str) -> str:
    data = value.encode("utf-8")
    if len(data) % 8:
        data += b"\x00" * (8 - len(data) % 8)
    enc = Cipher(TripleDES(key.encode("ascii")), modes.ECB()).encryptor()
    return base64.b64encode(enc.update(data) + enc.finalize()).decode()


def _aes_hex(data: bytes, key16: bytes) -> str:
    if len(data) % 16:
        data += b"\x00" * (16 - len(data) % 16)
    enc = Cipher(algorithms.AES(key16), modes.CBC(AES_IV)).encryptor()
    return (enc.update(data) + enc.finalize()).hex()


def _gzip(raw: bytes) -> bytes:
    co = zlib.compressobj(6, zlib.DEFLATED, -15)
    body = co.compress(raw) + co.flush()
    head = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03"
    tail = struct.pack("<II", zlib.crc32(raw) & 0xFFFFFFFF, len(raw) & 0xFFFFFFFF)
    return head + body + tail


def _rsa(text: str) -> str:
    key = load_der_public_key(base64.b64decode(PUBLIC_KEY))
    return base64.b64encode(key.encrypt(text.encode(), _rsa_pad.PKCS1v15())).decode()


def _tn(raw: dict) -> str:
    def rec(v):
        if isinstance(v, dict):
            return "".join(
                rec(str(10000 * v[k]) if isinstance(v[k], (int, float)) and not isinstance(v[k], bool) else str(v[k]))
                for k in sorted(v)
            )
        return str(v) if v else ""

    return _md5(rec(raw))


def _gen_smid() -> str:
    now = datetime.now()
    ts = now.strftime("%Y%m%d%H%M%S")
    a = ts + _md5(str(uuid.uuid4())) + "00"
    return a + _md5("smsk_web_" + a)[:14] + "0"


def _confuse(raw: dict) -> dict:
    out = {}
    for k, v in raw.items():
        cfg = CONFUSION.get(k)
        if cfg:
            obf, enc, key = cfg
            out[obf] = _des_field(str(v), key) if (enc and v != "") else v
        else:
            out[k] = v
    return out


def _is_mobile(ua: str) -> bool:
    return any(m in ua for m in _MOBILE_RE)


def _platform(ua: str) -> str:
    if "Android" in ua:
        return "Linux armv8l"
    if any(x in ua for x in ("iPhone", "iPad", "iPod")):
        return "iPhone"
    if "Windows" in ua:
        return "Win32"
    if "Mac OS X" in ua:
        return "MacIntel"
    return "Linux x86_64"


def _screen(ua: str):
    if _is_mobile(ua):
        return 1080, 2400, 360, 780, 3
    return 1920, 1080, 1920, 1040, 1


def _build_raw(user_agent: str, referer: str, platform: Optional[str]) -> dict:
    w, h, iw, ih, dpr = _screen(user_agent)
    now_ms = int(time.time() * 1000)
    return {
        "protocol": 129,
        "organization": ORGANIZATION,
        "appId": APPID,
        "os": "web",
        "version": "3.0.0",
        "sdkver": "3.0.0",
        "box": "",
        "rtype": "all",
        "smid": _gen_smid(),
        "subVersion": "1.0.0",
        "time": 4,
        "platform": platform or _platform(user_agent),
        "clientSize": f"0_0___{w}_{h}_{iw}_{ih}",
        "res": f"{w}_{h}_24_{dpr}",
        "status": "0010",
        "timezone": -480,
        "vpw": str(uuid.uuid4()),
        "svm": now_ms,
        "trees": str(uuid.uuid4()),
        "pmf": now_ms,
        "canvas": "",
        "plugins": "-",
        "referer": referer,
        "ua": user_agent,
        "url": referer,
    }


def get_device_id(
    user_agent: Optional[str] = None,
    accept_language: Optional[str] = None,
    referer: Optional[str] = None,
    platform: Optional[str] = None,
) -> str:
    user_agent = user_agent or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    )
    referer = referer or "https://www.skland.com/"
    uid = str(uuid.uuid4())
    pri_id = _md5(uid)[:16]

    raw = _build_raw(user_agent, referer, platform)
    raw["tn"] = _tn(raw)
    fp = _confuse(raw)

    gz = _gzip(json.dumps(fp, separators=(",", ":")).encode())
    data = _aes_hex(base64.b64encode(gz), pri_id.encode())
    envelope = {
        "appId": APPID,
        "organization": ORGANIZATION,
        "ep": _rsa(uid),
        "data": data,
        "os": "web",
        "encode": 5,
        "compress": 2,
    }
    return "D" + base64.b64encode(json.dumps(envelope, separators=(",", ":")).encode()).decode()
