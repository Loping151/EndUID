def get_main_url() -> str:
    """获取 API 基础 URL"""
    return "https://zonai.skland.com/"


MAIN_URL = get_main_url()
API_VERSION = "v1"

# 平台和游戏 ID
PLATFORM_ENDFIELD = 3  # 终末地平台 ID
GAME_ID_ENDFIELD = 1   # 终末地游戏 ID？为啥到这就是1了

# APP CODE（用于 OAuth）
APP_CODE = "4ca99fa6b56cc2ba"


# OAuth 授权
OAUTH_API = "https://as.hypergryph.com/user/oauth2/v2/grant"

# Cred 获取（通过 Token）
CRED_API = f"{MAIN_URL}api/{API_VERSION}/user/auth/generate_cred_by_code"

# 扫码登录
SCAN_LOGIN_API = "https://as.hypergryph.com/general/v1/gen_scan/login"
SCAN_STATUS_API = "https://as.hypergryph.com/general/v1/scan_status"
TOKEN_BY_SCAN_CODE_API = "https://as.hypergryph.com/user/auth/v1/token_by_scan_code"

# Token 刷新
REFRESH_TOKEN_URL = f"{MAIN_URL}api/{API_VERSION}/auth/refresh"

# 用户绑定信息
BINDING_URL = f"{MAIN_URL}api/{API_VERSION}/game/player/binding"

# 玩家信息
GAME_PLAYER_INFO_URL = f"{MAIN_URL}api/{API_VERSION}/game/player/info"

USER_INFO_URL = f"{MAIN_URL}api/{API_VERSION}/user"

# 签到相关
GAME_ATTENDANCE_URL = f"{MAIN_URL}api/{API_VERSION}/game/attendance"
GAME_ATTENDANCE_QUERY_URL = f"{MAIN_URL}api/{API_VERSION}/game/attendance"

# 卡片信息
GAME_CARDS_URL = f"{MAIN_URL}api/{API_VERSION}/game/cards"


# 签到
ENDFIELD_ATTENDANCE_URL = f"{MAIN_URL}api/{API_VERSION}/game/endfield/attendance"

# 枚举数据（道具、角色等，暂时没啥用）
ENDFIELD_ENUMS_URL = f"{MAIN_URL}api/{API_VERSION}/game/endfield/enums"

# 卡片详情（角色、武器、基地等完整数据）
CARD_DETAIL_URL = f"{MAIN_URL}api/{API_VERSION}/game/endfield/card/detail"


# 公告相关
SKLAND_ANN_LIST_URL = "https://zonai.skland.com/web/v1/home/index"
SKLAND_ANN_DETAIL_URL = "https://zonai.skland.com/web/v1/item"
SKLAND_GAME_ID_ENDFIELD = 3  # 终末地在森空岛的游戏 ID
SKLAND_CATE_ID_ENDFIELD = 12  # 终末地公告分类 ID

# 抽卡记录 (Gacha)
GACHA_BASE_URL_CN = "https://ef-webview.hypergryph.com"
GACHA_BASE_URL_GLOBAL = "https://ef-webview.gryphline.com"

GACHA_CHAR_RECORD_URL = f"{GACHA_BASE_URL_CN}/api/record/char"
GACHA_WEAPON_POOL_LIST_URL = f"{GACHA_BASE_URL_CN}/api/record/weapon/pool"
GACHA_WEAPON_RECORD_URL = f"{GACHA_BASE_URL_CN}/api/record/weapon"


API_MAP = {
    # 认证相关
    "oauth": OAUTH_API,
    "cred": CRED_API,
    "scan_login": SCAN_LOGIN_API,
    "scan_status": SCAN_STATUS_API,
    "token_by_scan": TOKEN_BY_SCAN_CODE_API,
    "refresh_token": REFRESH_TOKEN_URL,

    # 通用数据
    "binding": BINDING_URL,
    "player_info": GAME_PLAYER_INFO_URL,
    "user_info": USER_INFO_URL,
    "attendance": GAME_ATTENDANCE_URL,
    "attendance_query": GAME_ATTENDANCE_QUERY_URL,
    "cards": GAME_CARDS_URL,
    "card_detail": CARD_DETAIL_URL,

    # 终末地专属
    "endfield_attendance": ENDFIELD_ATTENDANCE_URL,
    "endfield_enums": ENDFIELD_ENUMS_URL,

    # 抽卡记录
    "gacha_char_record": GACHA_CHAR_RECORD_URL,
    "gacha_weapon_pool_list": GACHA_WEAPON_POOL_LIST_URL,
    "gacha_weapon_record": GACHA_WEAPON_RECORD_URL,
}
