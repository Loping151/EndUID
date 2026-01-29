"""EndUID - 终末地插件"""
from gsuid_core.sv import Plugins
from gsuid_core.logger import logger

from .utils.bot_send_hook import (
    install_bot_hooks,
    register_target_send_hook,
    register_user_activity_hook,
)
from .utils.database.models import EndSubscribe, EndUserActivity
from .utils.plugin_checker import is_from_end_plugin


Plugins(
    name="EndUID",
    force_prefix=["end", "zmd"],
    allow_empty_prefix=False
)

logger.info("[EndUID] 插件加载中...")


# 1. 安装 Bot Hook（Monkey Patch）
install_bot_hooks()

# 2. 注册自定义 Hook

async def end_bot_check_hook(group_id: str, bot_self_id: str):
    """Bot-群组绑定 Hook

    当群消息发送时，自动记录/更新该群使用的 bot_self_id
    """
    logger.debug(
        f"[EndUID Hook] bot_check_hook 被调用: group_id={group_id}, bot_self_id={bot_self_id}"
    )

    if group_id:
        try:
            await EndSubscribe.check_and_update_bot(group_id, bot_self_id)
        except Exception as e:
            logger.warning(f"[EndUID] Bot检测失败: {e}")


async def end_user_activity_hook(user_id: str, bot_id: str, bot_self_id: str):
    """用户活跃度 Hook

    当用户触发本插件的消息时，自动更新活跃度
    """
    if not is_from_end_plugin():
        logger.debug(
            "[EndUID Hook] 消息不是来自本插件，跳过活跃度更新: "
            f"user_id={user_id}"
        )
        return

    logger.debug(
        f"[EndUID Hook] user_activity_hook 被调用: user_id={user_id}, bot_id={bot_id}, bot_self_id={bot_self_id}"
    )

    if user_id:
        try:
            await EndUserActivity.update_user_activity(user_id, bot_id, bot_self_id)
        except Exception as e:
            logger.warning(f"[EndUID] 用户活跃度更新失败: {e}")


# 注册 Hook
register_target_send_hook(end_bot_check_hook)
register_user_activity_hook(end_user_activity_hook)

logger.success("[EndUID] Hook 已注册")
