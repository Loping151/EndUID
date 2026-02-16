"""EndUID - 终末地插件"""
import asyncio

from gsuid_core.sv import Plugins
from gsuid_core.logger import logger
from gsuid_core.server import on_core_shutdown

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

# ===== 活跃度批量写入缓冲 =====
_activity_buffer: dict[str, tuple[str, str, str]] = {}
_FLUSH_INTERVAL = 60


async def _flush_activity_buffer():
    if not _activity_buffer:
        return
    pending = dict(_activity_buffer)
    _activity_buffer.clear()
    for key, (user_id, bot_id, bot_self_id) in pending.items():
        try:
            await EndUserActivity.update_user_activity(user_id, bot_id, bot_self_id)
        except Exception as e:
            logger.warning(f"[EndUID] 批量活跃度写入失败: {e}")


async def _activity_flush_loop():
    while True:
        await asyncio.sleep(_FLUSH_INTERVAL)
        try:
            await _flush_activity_buffer()
        except Exception as e:
            logger.warning(f"[EndUID] 活跃度刷写循环异常: {e}")

asyncio.get_event_loop().create_task(_activity_flush_loop())


@on_core_shutdown
async def _flush_on_shutdown():
    logger.info("[EndUID] 退出前刷写活跃度缓冲区...")
    await _flush_activity_buffer()
    logger.info("[EndUID] 活跃度缓冲区刷写完成")


# 1. 安装 Bot Hook（Monkey Patch）
install_bot_hooks()

# 2. 注册自定义 Hook

async def end_bot_check_hook(group_id: str, bot_self_id: str):
    """Bot-群组绑定 Hook"""
    logger.debug(
        f"[EndUID Hook] bot_check_hook 被调用: group_id={group_id}, bot_self_id={bot_self_id}"
    )

    if group_id:
        try:
            await EndSubscribe.check_and_update_bot(group_id, bot_self_id)
        except Exception as e:
            logger.warning(f"[EndUID] Bot检测失败: {e}")


async def end_user_activity_hook(user_id: str, bot_id: str, bot_self_id: str):
    """用户活跃度 Hook - 写入缓冲区，定时批量刷写"""
    if not is_from_end_plugin():
        return
    if not user_id:
        return
    _activity_buffer[f"{user_id}:{bot_id}:{bot_self_id}"] = (user_id, bot_id, bot_self_id)


# 注册 Hook
register_target_send_hook(end_bot_check_hook)
register_user_activity_hook(end_user_activity_hook)

logger.success("[EndUID] Hook 已注册")
