"""EndUID 签到功能模块"""
from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.aps import scheduler

from .sign_handler import end_sign_handler, end_auto_sign
from ..end_config import EndConfig



# 普通签到
end_sign_sv = SV("End签到")
# 全部签到（女管理员）
end_sign_all_sv = SV("End全部签到", pm=0)
# 自动签到开关
end_sign_switch_sv = SV("End自动签到")



@end_sign_sv.on_fullmatch(("签到"))
async def sign_in(bot: Bot, ev: Event):
    """签到命令"""
    msg = await end_sign_handler(bot, ev)
    return await bot.send(msg)


@end_sign_all_sv.on_fullmatch(("全部签到"))
async def sign_all(bot: Bot, ev: Event):

    await bot.send("🔄 签到任务开始执行...")

    # 执行自动签到
    await end_auto_sign()

    return await bot.send("✅ 签到任务执行完成")


@end_sign_switch_sv.on_fullmatch(("开启自动签到", "自动签到"))
async def enable_auto_sign(bot: Bot, ev: Event):
    """开启自动签到

    修改用户的 bbs_sign_switch 字段为 "on"
    """
    from ..utils.database.models import EndBind, EndUser

    # 获取 UID
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send("❌ 未绑定终末地账号")

    # 获取用户信息
    user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
    if not user:
        return await bot.send("❌ 未找到用户信息")

    # 更新签到开关
    await EndUser.update_data_by_uid(uid, ev.bot_id, bbs_sign_switch="on")

    return await bot.send("✅ 已开启自动签到")


@end_sign_switch_sv.on_fullmatch(("关闭自动签到", "停止自动签到"))
async def disable_auto_sign(bot: Bot, ev: Event):
    """关闭自动签到"""
    from ..utils.database.models import EndBind, EndUser

    # 获取 UID
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send("❌ 未绑定终末地账号")

    # 获取用户信息
    user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
    if not user:
        return await bot.send("❌ 未找到用户信息")

    # 更新签到开关
    await EndUser.update_data_by_uid(uid, ev.bot_id, bbs_sign_switch="off")

    return await bot.send("✅ 已关闭自动签到")



def setup_scheduler():
    """设置定时任务"""
    # 检查是否启用定时签到
    if not EndConfig.get_config("SchedSignin").data:
        logger.info("[EndUID] 定时签到未启用")
        return

    # 获取签到时间
    sign_time_config = EndConfig.get_config("SignTime").data
    sign_hour = int(sign_time_config[0])
    sign_minute = int(sign_time_config[1])

    logger.info(f"[EndUID] 设置定时签到: 每天 {sign_hour:02d}:{sign_minute:02d}")

    # 添加定时任务
    try:
        scheduler.add_job(
            end_auto_sign,
            "cron",
            id="end_sign_0",
            hour=sign_hour,
            minute=sign_minute,
            replace_existing=True,
        )
        logger.success(f"[EndUID] 定时签到任务已注册")
    except Exception as e:
        logger.error(f"[EndUID] 定时签到任务注册失败: {e}")



# 注册定时任务
setup_scheduler()

logger.success("[EndUID] 签到模块加载完成")
