"""抽卡记录功能命令处理"""
from urllib.parse import urlparse, parse_qs

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.segment import MessageSegment

from ..end_config import PREFIX
from ..utils.tips import TIP_NOT_BOUND
from ..end_config.config_default import EndConfig
from ..utils.database.models import EndBind, EndUser
from ..utils.api.requests import end_api
from ..utils.util import hide_uid
from .get_gachalogs import (
    get_new_gachalog,
    is_uid_locked,
    import_from_json,
    export_gachalogs,
    delete_gachalogs,
)
from .draw_gachalogs import draw_gacha_card, draw_gacha_help
from .web_view import make_gacha_web_url, feature_disabled_msg, _is_feature_enabled
from ..utils.util import get_hide_uid_pref

sv_gacha_help = SV("End抽卡帮助")
sv_gacha_tool = SV("End抽卡工具")
sv_gacha_import = SV("End导入抽卡记录", priority=4)
sv_gacha_record = SV("End抽卡记录")
sv_gacha_export = SV("End导出抽卡记录")
sv_gacha_delete = SV("End删除抽卡记录")
sv_gacha_web = SV("End抽卡网页")


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


@sv_gacha_help.on_fullmatch(
    ("抽卡帮助", "ckbz"),
    block=True,
    to_ai="""返回终末地抽卡功能（导入抽卡记录 / 抽卡链接获取方式）的使用说明图。

当用户问「终末地抽卡帮助 / end 抽卡说明 / 抽卡链接怎么搞」时调用。

Args:
    text: 无需参数。
""",
)
async def send_gacha_help(bot: Bot, ev: Event):
    im = await draw_gacha_help()
    await bot.send(im)


@sv_gacha_tool.on_fullmatch(
    ("抽卡工具", "ckgj"),
    block=True,
    to_ai="""返回 Windows 端抽卡链接提取工具的下载地址。

当用户问「终末地抽卡工具 / end 抽卡链接提取工具 / 抽卡工具下载」时调用。

Args:
    text: 无需参数。
""",
)
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


@sv_gacha_import.on_command(("导入抽卡记录", "导入抽卡", "更新抽卡记录", "更新抽卡", "刷新抽卡记录", "刷新抽卡"), block=True)
async def import_gacha_record(bot: Bot, ev: Event):
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(TIP_NOT_BOUND)

    if is_uid_locked(uid):
        return

    text = ev.text.strip()

    if text:
        u8_token, _, _ = _parse_gacha_token(text)
        if not u8_token:
            return await bot.send("无法识别 u8_token，请检查输入")
        await bot.send("正在获取抽卡记录，请稍候...")
    else:
        user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
        if not user or not user.hg_token:
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

        u8_token = await end_api.get_u8_token(user.hg_token, binding_uid)
        if not u8_token:
            return await bot.send(
                "自动获取 token 失败！\n"
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


@sv_gacha_record.on_fullmatch(
    ("抽卡记录", "ckjl"),
    block=True,
    to_ai="""查询自己终末地账号已导入的抽卡记录统计图（各池子出货情况、保底进度等）。

当用户问「我的抽卡记录 / 终末地抽卡记录 / end 抽卡记录」时调用。
需先导入过抽卡记录。

Args:
    text: 无需参数。
""",
)
async def send_gacha_record(bot: Bot, ev: Event):
    im = await draw_gacha_card(ev)
    await bot.send(im)


@sv_gacha_export.on_fullmatch(
    ("导出抽卡记录", "dcckjl"),
    block=True,
    to_ai="""导出自己终末地账号的抽卡记录（标准 JSON 格式文件）。

当用户问「导出抽卡记录 / 备份抽卡 / end 抽卡导出」时调用。需先导入过记录。

Args:
    text: 无需参数。
""",
)
async def export_gacha_record(bot: Bot, ev: Event):
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(
            TIP_NOT_BOUND
        )

    user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
    if not user or not user.cookie:
        return await bot.send(
            f"请先使用「{PREFIX}登录」绑定账号后再导出抽卡记录"
        )

    export = await export_gachalogs(uid)
    if not export:
        return await bot.send(
            f"未找到抽卡记录，请先使用「{PREFIX}导入抽卡记录」导入"
        )

    await bot.send(MessageSegment.file(export["url"], export["name"]))


@sv_gacha_web.on_fullmatch(
    ("抽卡页面", "抽卡网页", "网页抽卡记录", "抽卡记录网页"),
    block=True,
    to_ai="""返回自己终末地抽卡记录的网页查看链接（10 分钟内有效）。

当用户问「终末地抽卡页面 / 抽卡网页 / 网页看抽卡记录」时调用。需先导入抽卡记录，且主人已开启网页开关。

Args:
    text: 无需参数。
""",
)
async def send_gacha_web_link(bot: Bot, ev: Event):
    if not _is_feature_enabled():
        return await bot.send(feature_disabled_msg())

    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(TIP_NOT_BOUND)

    user_pref = await get_hide_uid_pref(uid, ev.user_id, ev.bot_id)
    url, msg = await make_gacha_web_url(uid, ev, user_pref)
    if not url:
        return await bot.send(msg)

    title = f"「终末地」UID{hide_uid(uid, user_pref)} 的抽卡记录网页"
    expire = "该链接 10 分钟内有效，过期后请重新发送指令。"
    if not ev.group_id and ev.bot_id == "onebot":
        await bot.send("\n".join([title, url, expire]))
    else:
        await bot.send(MessageSegment.node([title, f" {url}", expire]))


@sv_gacha_delete.on_command(("删除抽卡记录", "scckjl"), block=True)
async def delete_gacha_record(bot: Bot, ev: Event):
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(
            TIP_NOT_BOUND
        )

    user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
    if not user or not user.cookie:
        return await bot.send(
            f"请先使用「{PREFIX}登录」绑定账号后再删除抽卡记录"
        )

    success = await delete_gachalogs(uid)
    if success:
        await bot.send(f"已删除UID {hide_uid(uid)} 的抽卡记录")
    else:
        await bot.send(f"未找到 UID {hide_uid(uid)} 的抽卡记录")
