"""EndUID 签到功能模块"""
import asyncio
from datetime import datetime, timedelta

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.aps import scheduler
from gsuid_core.subscribe import gs_subscribe

from .sign_handler import end_sign_handler, end_auto_sign
from .sign_state import signing_state
from ..end_config import EndConfig, PREFIX

TASK_NAME_SIGN_RESULT = "订阅终末地签到结果"

# 普通签到
end_sign_sv = SV("End签到")
# 全部签到（管理员）
end_sign_all_sv = SV("End全部签到", pm=0)
# 自动签到开关
end_sign_switch_sv = SV("End自动签到")
# 订阅签到结果
end_sign_sub_sv = SV("End订阅签到结果", pm=0)


@end_sign_sv.on_fullmatch(("签到"))
async def sign_in(bot: Bot, ev: Event):
    """签到命令"""
    msg = await end_sign_handler(bot, ev)
    return await bot.send(msg)


@end_sign_all_sv.on_fullmatch(("全部签到"))
async def sign_all(bot: Bot, ev: Event):
    if signing_state.is_signing():
        state = signing_state.get_state()
        sign_type_text = "自动签到" if state and state.get("type") == "auto" else "全部签到"
        return await bot.send(f"[EndUID] 正在执行{sign_type_text}，请稍后...")

    signing_state.set_state("manual")
    await bot.send("[EndUID] 全部签到开始执行...")
    try:
        msg = await end_auto_sign()
        await bot.send(msg)
    finally:
        signing_state.clear_state()


@end_sign_switch_sv.on_fullmatch(("开启自动签到", "自动签到"))
async def enable_auto_sign(bot: Bot, ev: Event):
    from ..utils.database.models import EndBind, EndUser

    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(f"❌ 未绑定终末地账号，请先使用「{PREFIX}绑定」")

    user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
    if not user:
        return await bot.send("❌ 未找到用户信息")

    await EndUser.update_data_by_uid(uid, ev.bot_id, bbs_sign_switch="on")
    return await bot.send("✅ 已开启自动签到")


@end_sign_switch_sv.on_fullmatch(("关闭自动签到", "停止自动签到"))
async def disable_auto_sign(bot: Bot, ev: Event):
    from ..utils.database.models import EndBind, EndUser

    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(f"❌ 未绑定终末地账号，请先使用「{PREFIX}绑定」")

    user = await EndUser.select_end_user(uid, ev.user_id, ev.bot_id)
    if not user:
        return await bot.send("❌ 未找到用户信息")

    await EndUser.update_data_by_uid(uid, ev.bot_id, bbs_sign_switch="off")
    return await bot.send("✅ 已关闭自动签到")


# ===================== 订阅签到结果 =====================

@end_sign_sub_sv.on_regex("^(订阅|取消订阅)签到结果$")
async def end_sign_result_sub(bot: Bot, ev: Event):
    if ev.bot_id != "onebot":
        return

    if "取消" in ev.raw_text:
        option = "关闭"
    else:
        option = "开启"

    if ev.group_id and option == "开启":
        from ..utils.database.models import EndSubscribe
        await EndSubscribe.check_and_update_bot(ev.group_id, ev.bot_self_id)

    if option == "关闭":
        await gs_subscribe.delete_subscribe("single", TASK_NAME_SIGN_RESULT, ev)
    else:
        await gs_subscribe.add_subscribe("single", TASK_NAME_SIGN_RESULT, ev)

    await bot.send(f"[EndUID] 已{option}订阅签到结果")


# ===================== 定时签到 =====================

async def end_scheduled_sign():
    """定时签到入口（带状态文件管理 + 推送订阅结果）"""
    signing_state.set_state("auto")
    try:
        msg = await end_auto_sign()
        subscribes = await gs_subscribe.get_subscribe(TASK_NAME_SIGN_RESULT)
        if subscribes and msg:
            logger.info(f"[EndUID] 推送签到结果: {msg}")
            for sub in subscribes:
                await sub.send(msg)
    finally:
        signing_state.clear_state()


def setup_scheduler():
    """设置定时任务"""
    if not EndConfig.get_config("SchedSignin").data:
        logger.info("[EndUID] 定时签到未启用")
        return

    sign_time_config = EndConfig.get_config("SignTime").data
    sign_hour = int(sign_time_config[0])
    sign_minute = int(sign_time_config[1])

    logger.info(f"[EndUID] 设置定时签到: 每天 {sign_hour:02d}:{sign_minute:02d}")

    try:
        scheduler.add_job(
            end_scheduled_sign,
            "cron",
            id="end_sign_0",
            hour=sign_hour,
            minute=sign_minute,
            replace_existing=True,
        )
        logger.success("[EndUID] 定时签到任务已注册")
    except Exception as e:
        logger.error(f"[EndUID] 定时签到任务注册失败: {e}")


setup_scheduler()


# ===================== 清理签到记录 =====================

@scheduler.scheduled_job("cron", hour=0, minute=5)
async def clear_end_sign_record():
    """每天 00:05 清除 2 天前的签到记录"""
    from ..utils.database.models import EndSignRecord

    two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    await EndSignRecord.clear_sign_records(two_days_ago)
    logger.info("[EndUID] 已清除2天前的签到记录")


# ===================== 重启续签 =====================

async def check_and_resume_end_signing():
    """启动时检查状态文件，如果有未完成的签到则继续执行"""
    if not signing_state.should_resume():
        return

    state = signing_state.get_state()
    if not state:
        return

    sign_type = state.get("type", "auto")
    logger.warning(f"[EndUID] 检测到未完成的签到任务，正在恢复: type={sign_type}")

    await asyncio.sleep(5)

    try:
        if sign_type == "auto":
            await end_scheduled_sign()
        else:
            signing_state.set_state("manual")
            await end_auto_sign()
            signing_state.clear_state()
    except Exception as e:
        logger.error(f"[EndUID] 恢复签到任务时出错: {e}")
        signing_state.clear_state()


startup_time = datetime.now() + timedelta(seconds=10)
scheduler.add_job(
    check_and_resume_end_signing,
    "date",
    run_date=startup_time,
    id="end_resume_signing_on_startup",
)
logger.info("[EndUID] 已注册启动恢复任务，将在启动后10秒检查未完成的签到")

logger.success("[EndUID] 签到模块加载完成")
