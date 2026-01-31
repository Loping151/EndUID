"""抽卡记录功能命令处理"""
from urllib.parse import urlparse, parse_qs

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.segment import MessageSegment

from ..end_config import PREFIX
from ..utils.database.models import EndBind
from .get_gachalogs import (
    get_new_gachalog,
    export_gachalogs,
    delete_gachalogs,
    load_gachalogs,
)
from .draw_gachalogs import draw_gacha_card, draw_gacha_help

sv_gacha_help = SV("End抽卡帮助")
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

    # 尝试从 URL 解析
    if "u8_token=" in text or "u8Token=" in text:
        try:
            # 如果不是完整 URL，补上 scheme
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

    # 纯文本当作 token
    return text, channel, sub_channel


@sv_gacha_help.on_fullmatch(("抽卡帮助", "ckbz"), block=True)
async def send_gacha_help(bot: Bot, ev: Event):
    im = await draw_gacha_help()
    await bot.send(im)


@sv_gacha_import.on_command(("导入抽卡记录", "导入抽卡", "drckjl"), block=True)
async def import_gacha_record(bot: Bot, ev: Event):
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(
            f"未绑定终末地账号，请先使用「{PREFIX}登录」绑定"
        )

    text = ev.text.strip()
    if not text:
        return await bot.send(
            f"请在命令后附带抽卡链接或 u8_token\n"
            f"例如：{PREFIX}导入抽卡记录 <链接或token>\n"
            f"发送「{PREFIX}抽卡帮助」查看获取方式"
        )

    u8_token, channel, sub_channel = _parse_gacha_token(text)
    if not u8_token:
        return await bot.send("无法识别 u8_token，请检查输入")

    await bot.send("正在获取抽卡记录，请稍候...")

    success, msg, _ = await get_new_gachalog(
        uid=uid,
        u8_token=u8_token,
        server_id="1",
        channel=channel,
        sub_channel=sub_channel,
    )

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

    data = await export_gachalogs(uid)
    if not data:
        return await bot.send(
            f"未找到抽卡记录，请先使用「{PREFIX}导入抽卡记录」导入"
        )

    file_bytes = data.encode("utf-8")
    filename = f"EndUID_gacha_{uid}.json"
    await bot.send(MessageSegment.file(file_bytes, filename))


@sv_gacha_delete.on_command(("删除抽卡记录", "scckjl"), block=True)
async def delete_gacha_record(bot: Bot, ev: Event):
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(
            f"未绑定终末地账号，请先使用「{PREFIX}绑定」"
        )

    success = await delete_gachalogs(uid)
    if success:
        await bot.send("已删除抽卡记录（已备份）")
    else:
        await bot.send("未找到抽卡记录或删除失败")
