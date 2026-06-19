"""跨子模块共用的提示文案，统一收口避免散落重复。"""
from ..end_config import PREFIX

# 未绑定账号
TIP_NOT_BOUND = f"未绑定终末地账号，请先使用「{PREFIX}登录」"
# 凭证缺失/失效
TIP_NO_CRED = f"❌ 未找到可用凭证，请使用「{PREFIX}登录」重新绑定"
# 本地卡片缓存缺失
TIP_NO_LOCAL_CARD = f"❌ 本地卡片数据读取失败，请先发送「{PREFIX}刷新」"
