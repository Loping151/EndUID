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
    "AtCheck": GsBoolConfig(
        "允许@查询他人",
        "开启后，查询类指令若@了他人则查询被@用户的数据，头像也取被@用户的；关闭则始终查询发送者自己。",
        True,
    ),
    "HideUid": GsBoolConfig(
        "隐藏uid",
        "开启后，所有渲染卡片中显示的UID将以 前2位 + **** + 后2位 的形式显示",
        False,
    ),
    "NeedProxyFunc": GsListStrConfig(
        "需要代理的函数",
        "需要代理的函数",
        ["all"],
        options=[
            "all",
        ],
    ),

    # ==================== 攻略配置 ====================
    "EndGuideMaxSize": GsIntConfig(
        "攻略图片最大大小(M)",
        "发送攻略图片前会自动转为jpg格式，若超过此大小则自动压缩，单位MB",
        2,
        max_value=50,
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

    # ==================== 公告配置 ====================
    "AnnOpen": GsBoolConfig(
        "公告推送开关",
        "开启后将自动推送终末地最新公告",
        True,
    ),
    "AnnMinuteCheck": GsIntConfig(
        "公告检查间隔（分钟）",
        "每隔多少分钟检查一次新公告",
        15,
        max_value=60,
    ),

    # ==================== 抽卡配置 ====================
    "GachaToolUrl": GsStrConfig(
        "抽卡工具下载链接",
        "用于提取抽卡链接的小工具下载地址",
        "https://github.com/Loping151/EndUID/raw/main/EndUID/end_gacha/EndUIDGacha.exe",
    ),
    "GachaRequestIntervalMs": GsIntConfig(
        "抽卡记录请求间隔(毫秒)",
        "拉取抽卡记录时两次API请求之间的等待间隔(毫秒)。"
        "值越小拉取越快，但也越容易触发服务器限流或风控。"
        "默认100ms(约每秒10次请求)，建议保持默认；如遇报错可适当调大。"
        "修改后立即生效，无需重载。",
        100,
        max_value=10000,
    ),

    # ==================== 蓝图配置 ====================
    "BlueprintMaxResults": GsIntConfig(
        "蓝图搜索最大结果数",
        "搜索蓝图时最多显示的结果数量",
        5,
        max_value=50,
    ),

    # ==================== 渲染配置 ====================
    "UseHtmlRender": GsBoolConfig(
        "使用HTML渲染，需安装浏览器，本插件暂不支持其他渲染方式",
        "开启后将使用HTML渲染公告卡片，暂不支持关闭，招募pil高手",
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
