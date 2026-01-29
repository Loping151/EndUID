import asyncio
import re
from pathlib import Path

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.segment import MessageSegment
from gsuid_core.utils.cookie_manager.qrlogin import get_qrcode_base64

from ..end_config import PREFIX
from ..utils.api.requests import end_api
from ..utils.database.models import EndBind, EndUser

GAME_TITLE = "[终末地]"

EndBindUID = SV("End绑定UID", priority=10)
EndLogin = SV("End登录", priority=5)


def _normalize_text(text: str) -> str:
    text = re.sub(r'["\n\t ]+', "", text.strip())
    return text.replace("，", ",")


def _parse_credential(text: str) -> tuple[str, str]:
    raw = text.strip()
    lower = raw.lower()
    for prefix in ("cred=", "cred:", "token=", "token:"):
        if lower.startswith(prefix):
            return ("cred" if "cred" in prefix else "token", raw[len(prefix):])
    if len(raw) == 32:
        return "cred", raw
    if len(raw) == 24:
        return "token", raw
    return "", raw


async def _send_text(bot: Bot, ev: Event, msg: str):
    at_sender = True if ev.group_id else False
    return await bot.send(
        (" " if at_sender else "") + msg,
        at_sender=at_sender,
    )


@EndBindUID.on_command(("绑定", "bind"), block=True)
async def send_end_bind_msg(bot: Bot, ev: Event):
    text = _normalize_text(ev.text)
    if not text:
        msg = (
            f"{GAME_TITLE} 请发送 cred 或 token\n"
            f"例如：{PREFIX}绑定 cred\n"
            f"或：{PREFIX}绑定 token"
        )
        return await _send_text(bot, ev, msg)

    kind, credential = _parse_credential(text)
    if kind == "token":
        return await check_token(bot, ev, credential)
    if kind == "cred":
        return await check_cred(bot, ev, credential)

    msg = f"{GAME_TITLE} 格式错误，请发送 32位 cred 或 24位 token"
    return await _send_text(bot, ev, msg)


@EndLogin.on_command(("登录", "登陆", "登入", "登龙", "login", "dl"), block=True)
async def send_end_login_msg(bot: Bot, ev: Event):
    text = _normalize_text(ev.text)
    if text:
        kind, credential = _parse_credential(text)
        if kind == "token":
            return await check_token(bot, ev, credential)
        if kind == "cred":
            return await check_cred(bot, ev, credential)
        msg = f"{GAME_TITLE} 登录参数错误，请使用【{PREFIX}登录】扫码或【{PREFIX}绑定】绑定"
        return await _send_text(bot, ev, msg)

    at_sender = True if ev.group_id else False

    scan_id = await end_api.get_scan_id()
    if not scan_id:
        return await _send_text(bot, ev, f"{GAME_TITLE} 获取二维码失败，请稍后重试")

    scan_url = f"hypergryph://scan_login?scanId={scan_id}"
    logger.info(f"[EndUID] 扫码URL: {scan_url}")

    qr_path = Path(__file__).parent / f"{ev.user_id}.gif"
    try:
        qr_base64 = await get_qrcode_base64(scan_url, qr_path, ev.bot_id)
        msg = [
            f"{GAME_TITLE} 请使用森空岛APP扫码登录，二维码有效时间为2分钟。\n⚠️ 请不要扫描他人的登录二维码！",
            MessageSegment.image(qr_base64),
        ]
        await bot.send(msg, at_sender=at_sender)
    except Exception as e:
        logger.error(f"[EndUID] 生成二维码失败: {e}")
        return await _send_text(bot, ev, f"{GAME_TITLE} 生成二维码失败")
    finally:
        if qr_path.exists():
            qr_path.unlink()

    max_attempts = 50
    scan_code = None
    for _ in range(max_attempts):
        await asyncio.sleep(2)
        scan_code = await end_api.get_scan_status(scan_id)
        if scan_code:
            logger.info(f"[EndUID] 用户已扫码，scanCode: {scan_code}")
            break

    if not scan_code:
        return await _send_text(bot, ev, f"{GAME_TITLE} 二维码已超时，请重新获取并扫码")

    token = await end_api.get_token_by_scan_code(scan_code)
    if not token:
        return await _send_text(bot, ev, f"{GAME_TITLE} 获取 token 失败，请重试")

    cred_info = await end_api.get_cred_info_by_token(token)
    if cred_info == "405":
        return await _send_text(bot, ev, f"{GAME_TITLE} 当前服务无法使用token登录，请尝试使用cred")
    if not cred_info or not cred_info.get("cred"):
        return await _send_text(bot, ev, f"{GAME_TITLE} 获取 cred 失败，请重试")

    return await check_cred(
        bot,
        ev,
        cred_info["cred"],
        used_token=token,
        skland_user_id=cred_info.get("skland_user_id"),
    )


async def check_cred(
    bot: Bot,
    ev: Event,
    cred: str,
    used_token: str = None,
    skland_user_id: str = None,
):
    if not skland_user_id:
        try:
            user_info = await end_api.get_user_info(cred)
            if user_info and user_info.get("code") == 0:
                skland_user_id = user_info.get("data", {}).get("user", {}).get("id")
                if skland_user_id:
                    skland_user_id = str(skland_user_id)
            else:
                logger.warning("[EndUID] 获取 森空岛 用户信息失败，已跳过写入用户ID")
        except Exception as e:
            logger.warning(f"[EndUID] 获取 森空岛 用户信息异常: {e}")

    res = await end_api.get_binding(cred)
    if not res or res.get("code") != 0 or res.get("message") != "OK":
        logger.error(f"[EndUID] 绑定失败，响应: {res}")
        return await _send_text(bot, ev, f"{GAME_TITLE} 绑定失败，请检查 cred 是否正确")

    binding_list = res.get("data", {}).get("list", [])
    endfield_uid = None
    nickname = None
    channel = None
    record_uid = None
    server_id = "1"

    for binding_item in binding_list:
        if binding_item.get("appCode") == "endfield":
            binding_list_data = binding_item.get("bindingList", [])
            if binding_list_data:
                first_bind = binding_list_data[0]
                default_role = first_bind.get("defaultRole")
                if not default_role and first_bind.get("roles"):
                    default_role = first_bind["roles"][0]

                if default_role:
                    endfield_uid = default_role.get("roleId")
                    nickname = (
                        default_role.get("nickname")
                        or first_bind.get("nickName")
                        or "终末地角色"
                    )
                    channel = first_bind.get("channelName", "官服")
                    record_uid = first_bind.get("uid")
                    if default_role.get("serverId"):
                        server_id = str(default_role.get("serverId"))
            break

    if not endfield_uid:
        return await _send_text(bot, ev, f"{GAME_TITLE} 未找到账号绑定信息")

    result = await EndBind.insert_end_uid(
        user_id=ev.user_id,
        bot_id=ev.bot_id,
        uid=endfield_uid,
        group_id=ev.group_id,
    )

    if result == -1:
        return await _send_text(bot, ev, f"{GAME_TITLE} UID 格式错误")
    if result == -3:
        return await _send_text(bot, ev, f"{GAME_TITLE} UID 包含非法字符")

    user = await EndUser.select_end_user(endfield_uid, ev.user_id, ev.bot_id)
    if not user:
        user = EndUser(
            user_id=ev.user_id,
            bot_id=ev.bot_id,
            uid=endfield_uid,
        )

    user.cookie = cred
    user.nickname = nickname
    user.platform = "3"

    if used_token:
        user.token = used_token

    if record_uid:
        user.record_id = record_uid
    user.server_id = server_id
    if skland_user_id:
        user.skland_user_id = skland_user_id

    exists = await EndUser.select_end_user(endfield_uid, ev.user_id, ev.bot_id)
    if not exists:
        await EndUser.insert_data(
            user_id=ev.user_id,
            bot_id=ev.bot_id,
            uid=endfield_uid,
            cookie=user.cookie,
            token=user.token,
            nickname=user.nickname,
            platform=user.platform,
            record_id=user.record_id,
            server_id=user.server_id,
            skland_user_id=user.skland_user_id,
        )
    else:
        await EndUser.update_data_by_uid(
            endfield_uid,
            ev.bot_id,
            cookie=user.cookie,
            token=user.token,
            nickname=user.nickname,
            platform=user.platform,
            record_id=user.record_id,
            server_id=user.server_id,
            skland_user_id=user.skland_user_id,
        )

    msg = (
        f"{GAME_TITLE} 绑定成功！\n"
        f"游戏昵称: {nickname}\n"
        f"服务器: {channel}\n"
        f"UID: {endfield_uid}"
    )
    return await _send_text(bot, ev, msg)


async def check_token(bot: Bot, ev: Event, token: str):
    cred_info = await end_api.get_cred_info_by_token(token)
    if cred_info == "405":
        return await _send_text(bot, ev, f"{GAME_TITLE} 当前服务无法使用token登录，请尝试使用cred")
    if not cred_info or not cred_info.get("cred"):
        return await _send_text(bot, ev, f"{GAME_TITLE} Token 验证失败，请检查 token 是否正确")
    return await check_cred(
        bot,
        ev,
        cred_info["cred"],
        used_token=token,
        skland_user_id=cred_info.get("skland_user_id"),
    )


@EndBindUID.on_fullmatch(("我的cred", "查看cred", "获取cred"))
async def my_cred(bot: Bot, ev: Event):
    if ev.user_pm > 0:
        logger.warning(f"[EndUID] 安全起见，禁止获取token")
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await _send_text(bot, ev, f"{GAME_TITLE} 未绑定账号")

    user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
    if not user or not user.cookie:
        return await _send_text(bot, ev, f"{GAME_TITLE} 未找到 cred 信息")

    return await _send_text(bot, ev, user.cookie)


@EndBindUID.on_fullmatch(("我的token", "查看token", "获取token", "获取tk"))
async def my_token(bot: Bot, ev: Event):
    if ev.user_pm > 0:
        logger.warning(f"[EndUID] 安全起见，禁止获取token")
        return
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await _send_text(bot, ev, f"{GAME_TITLE} 未绑定账号")

    user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
    if not user or not user.token:
        return await _send_text(bot, ev, f"{GAME_TITLE} 未找到 token 信息")

    return await _send_text(bot, ev, user.token)


@EndBindUID.on_fullmatch(("删除绑定", "解绑", "删除"))
async def del_bind(bot: Bot, ev: Event):
    target_uid = ''.join(filter(str.isdigit, ev.text.strip()))
    if not target_uid:
        msg = f"{GAME_TITLE} 该命令需要带上正确的uid!\n例如【{PREFIX}删除123456789】"
        return await _send_text(bot, ev, msg)

    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await _send_text(bot, ev, f"{GAME_TITLE} 未绑定账号")

    user = await EndUser.select_end_user(target_uid, ev.user_id, ev.bot_id)
    if user:
        await EndUser.delete_end_user(target_uid, ev.user_id, ev.bot_id)

    res = await EndBind.delete_uid(ev.user_id, ev.bot_id, target_uid)
    if res != 0:
        return await _send_text(bot, ev, f"{GAME_TITLE} 尚未绑定该UID[{target_uid}]")

    return await _send_text(bot, ev, f"{GAME_TITLE} 删除成功")


@EndBindUID.on_command(("切换", "查看"), block=True)
async def switch_or_view_uid(bot: Bot, ev: Event):
    """切换或查看绑定的 UID"""
    at_sender = True if ev.group_id else False

    if "切换" in ev.command:
        target_uid = ''.join(filter(str.isdigit, ev.text.strip()))
        retcode = await EndBind.switch_uid_by_game(
            ev.user_id,
            ev.bot_id,
            target_uid if target_uid else None
        )
        if retcode == 0:
            uid_list = await EndBind.get_all_uids(ev.user_id, ev.bot_id)
            current_uid = uid_list[0] if uid_list else None
            msg = f"{GAME_TITLE} 切换 UID 成功！\n当前 UID: {current_uid}"
            return await _send_text(bot, ev, msg)
        elif retcode == -1:
            return await _send_text(bot, ev, f"{GAME_TITLE} 尚未绑定任何 UID")
        elif retcode == -3:
            return await _send_text(bot, ev, f"{GAME_TITLE} 只绑定了一个 UID，无需切换")
        else:
            return await _send_text(bot, ev, f"{GAME_TITLE} 尚未绑定该 UID[{target_uid}]")
    elif "查看" in ev.command:
        uid_list = await EndBind.get_all_uids(ev.user_id, ev.bot_id)
        if uid_list:
            uids_text = "\n".join([f"{i+1}. {uid}{' (当前)' if i == 0 else ''}" for i, uid in enumerate(uid_list)])
            msg = f"{GAME_TITLE} 已绑定的 UID 列表：\n{uids_text}"
            return await _send_text(bot, ev, msg)
        else:
            return await _send_text(bot, ev, f"{GAME_TITLE} 尚未绑定任何 UID")
