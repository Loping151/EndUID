from typing import Dict

from gsuid_core.utils.plugins_config.models import (
    GSC,
    GsIntConfig,
    GsStrConfig,
    GsBoolConfig,
    GsListStrConfig,
)
from gsuid_core.utils.plugins_config.gs_config import StringConfig
from ..utils.path import CONFIG_PATH

CONFIG_DEFAULT: Dict[str, GSC] = {
    "LocalProxyUrl": GsStrConfig(
        "本地代理地址",
        "本地代理地址",
        "",
    ),
    "NeedProxyFunc": GsListStrConfig(
        "需要代理的函数",
        "需要代理的函数",
        ["all"],
        options=[
            "all",
        ],
    ),

    "SigninMaster": GsBoolConfig(
        "全部开启签到",
        "开启后自动帮登录的人签到",
        False,
    ),
    "SchedSignin": GsBoolConfig(
        "定时签到",
        "定时签到",
        False,
    ),
    "SignTime": GsListStrConfig(
        "每晚签到时间设置",
        "每晚签到时间设置（时，分）",
        ["3", "0"],
    ),
    "SigninConcurrentNum": GsIntConfig(
        "自动签到并发数量",
        "自动签到并发数量",
        1,
        max_value=10,
    ),
    "SigninConcurrentNumInterval": GsListStrConfig(
        "自动签到并发数量间隔",
        "自动签到并发数量间隔，默认3-5秒",
        ["3", "5"],
    ),
    "ActiveDays": GsIntConfig(
        "活跃账号认定天数",
        "活跃账号认定天数",
        30,
        max_value=365,
    ),
    "PrivateSignReport": GsBoolConfig(
        "签到私聊报告",
        "关闭后将不再给任何人推送当天签到任务完成情况",
        False,
    ),
    "GroupSignReport": GsBoolConfig(
        "签到群组报告",
        "关闭后将不再给任何群推送当天签到任务完成情况",
        False,
    ),

    # ==================== 渲染配置 ====================
    "UseHtmlRender": GsBoolConfig(
        "使用HTML渲染",
        "开启后将使用HTML渲染公告卡片，关闭后将回退到PIL或纯文本",
        True,
    ),
    "RemoteRenderEnable": GsBoolConfig(
        "外置渲染开关",
        "开启后将使用外置渲染服务进行HTML渲染，失败时自动回退到本地渲染",
        False,
    ),
    "RemoteRenderUrl": GsStrConfig(
        "外置渲染地址",
        "外置渲染服务的API地址，例如：http://127.0.0.1:3000/render",
        "http://127.0.0.1:3000/render",
    ),
    "FontCssUrl": GsStrConfig(
        "外置渲染字体CSS地址",
        "用于HTML渲染的字体CSS URL，外置渲染时传递，一般保留默认即可，如果在本地，可以填http://127.0.0.1:8765/end/fonts/fonts.css，如果有自己的登录域名：可以使用 你的登录域名根/end/fonts/fonts.css",
        "https://fonts.loli.net/css2?family=JetBrains+Mono:wght@500;700&family=Oswald:wght@500;700&family=Noto+Sans+SC:wght@400;700&family=Noto+Color+Emoji&display=swap",
    ),
}


EndConfig = StringConfig(
    "EndUID",
    CONFIG_PATH,
    CONFIG_DEFAULT,
)
