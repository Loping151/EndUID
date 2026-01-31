"""抽卡记录功能命令处理"""
from urllib.parse import urlparse, parse_qs

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.segment import MessageSegment

from ..end_config import PREFIX
from ..end_config.config_default import EndConfig
from ..utils.database.models import EndBind, EndUser
from ..utils.api.requests import end_api
from .get_gachalogs import (
    get_new_gachalog,
    import_from_json,
    export_gachalogs,
    delete_gachalogs,
)
from .draw_gachalogs import draw_gacha_card, draw_gacha_help

sv_gacha_help = SV("End抽卡帮助")
sv_gacha_tool = SV("End抽卡工具")
sv_gacha_import = SV("End导入抽卡记录", priority=5)
sv_gacha_record = SV("End抽卡记录")
sv_gacha_export = SV("End导出抽卡记录")
sv_gacha_delete = SV("End删除抽卡记录")


def _parse_gacha_token(text: str) -> tuple[str, str, str]:
    """从输入文本中解析 u8_token、channel、subChannel

    支持:
    - 完整 URL: https://ef-webview.hypergryph.com/page/gacha_char?u8_token=xxx&channel=1&subChannel=1
    - 纯 token 字符串

    Returns:
        (u8_token, channel, sub_channel)
    """
    text = text.strip()
    if not text:
        return "", "1", "1"

    channel = "1"
    sub_channel = "1"

    if "u8_token=" in text or "u8Token=" in text:
        try:
            if not text.startswith("http"):
                text = "https://dummy.com/?" + text

            parsed = urlparse(text)
            params = parse_qs(parsed.query)

            token = (
                params.get("u8_token", params.get("u8Token", [""]))[0]
            )
            channel = params.get("channel", ["1"])[0]
            sub_channel = params.get("subChannel", ["1"])[0]

            if token:
                return token, channel, sub_channel
        except Exception:
            pass

    return text, channel, sub_channel


@sv_gacha_help.on_fullmatch(("抽卡帮助", "ckbz"), block=True)
async def send_gacha_help(bot: Bot, ev: Event):
    im = await draw_gacha_help()
    await bot.send(im)


@sv_gacha_tool.on_fullmatch(("抽卡工具", "ckgj"), block=True)
async def send_gacha_tool(bot: Bot, ev: Event):
    url = EndConfig.get_config("GachaToolUrl").data
    if not url:
        return
    await bot.send(f"Windows抽卡链接提取工具下载：\n{url}")


@sv_gacha_import.on_file("json")
async def import_gacha_by_file(bot: Bot, ev: Event):
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return

    if not ev.file:
        return

    raw_json = (
        ev.file.decode("utf-8")
        if isinstance(ev.file, bytes)
        else ev.file
    )
    success, msg = await import_from_json(uid, raw_json)
    if success:
        await bot.send(msg)


@sv_gacha_import.on_command(("导入抽卡记录", "导入抽卡", "更新抽卡记录", "更新抽卡"), block=True)
async def import_gacha_record(bot: Bot, ev: Event):
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(
            f"未绑定终末地账号，请先使用「{PREFIX}登录」绑定"
        )

    text = ev.text.strip()

    if text:
        u8_token, _, _ = _parse_gacha_token(text)
        if not u8_token:
            return await bot.send("无法识别 u8_token，请检查输入")
        await bot.send("正在获取抽卡记录，请稍候...")
    else:
        user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
        if not user or not user.token:
            return await bot.send(
                f"请在命令后附带抽卡链接或 u8_token\n"
                f"也可以先使用「{PREFIX}登录」扫码登录，之后可直接使用本命令自动获取\n"
                f"发送「{PREFIX}抽卡帮助」查看获取方式"
            )

        binding_uid = user.record_id
        if not binding_uid:
            return await bot.send(
                f"缺少绑定信息，请重新「{PREFIX}登录」以补全数据"
            )

        await bot.send("正在获取抽卡记录...为避免请求过快，可能较久，请等待...")
        u8_token = await end_api.get_u8_token(user.token, binding_uid)
        if not u8_token:
            return await bot.send(
                "自动获取 token 失败，可能是使用旧的插件版本登录！\n"
                f"请重新「{PREFIX}登录」或使用方式二、三手动提供抽卡链接"
            )

    success, msg, _ = await get_new_gachalog(
        uid=uid,
        u8_token=u8_token,
        server_id="1",
    )

    if not msg:
        return
    await bot.send(msg if success else f"导入失败: {msg}")


@sv_gacha_record.on_fullmatch(("抽卡记录", "ckjl"), block=True)
async def send_gacha_record(bot: Bot, ev: Event):
    im = await draw_gacha_card(ev)
    await bot.send(im)


@sv_gacha_export.on_fullmatch(("导出抽卡记录", "dcckjl"), block=True)
async def export_gacha_record(bot: Bot, ev: Event):
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(
            f"未绑定终末地账号，请先使用「{PREFIX}绑定」"
        )

    user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
    if not user or not user.token:
        return await bot.send(
            f"请先使用「{PREFIX}登录」绑定账号后再导出抽卡记录"
        )

    export = await export_gachalogs(uid)
    if not export:
        return await bot.send(
            f"未找到抽卡记录，请先使用「{PREFIX}导入抽卡记录」导入"
        )

    await bot.send(MessageSegment.file(export["url"], export["name"]))


@sv_gacha_delete.on_command(("删除抽卡记录", "scckjl"), block=True)
async def delete_gacha_record(bot: Bot, ev: Event):
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(
            f"未绑定终末地账号，请先使用「{PREFIX}绑定」"
        )

    user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
    if not user or not user.token:
        return await bot.send(
            f"请先使用「{PREFIX}登录」绑定账号后再删除抽卡记录"
        )

    success = await delete_gachalogs(uid)
    if success:
        await bot.send(f"已删除UID {uid} 的抽卡记录")
    else:
        await bot.send(f"未找到 UID {uid} 的抽卡记录")
