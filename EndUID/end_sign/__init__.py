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
from ..end_config import EndConfig
from ..utils.tips import TIP_NOT_BOUND

TASK_NAME_SIGN_RESULT = "订阅终末地签到结果"

# 普通签到
end_sign_sv = SV("End签到")
# 全部签到（管理员）
end_sign_all_sv = SV("End全部签到", pm=0)
# 自动签到开关
end_sign_switch_sv = SV("End自动签到")
# 订阅签到结果
end_sign_sub_sv = SV("End订阅签到结果", pm=0)
# 删除无效token（管理员）
end_del_invalid_sv = SV("End删除无效token", priority=1, pm=1)


@end_sign_sv.on_fullmatch(
    ("签到"),
    to_ai="""用户主动执行终末地（明日方舟：终末地）每日签到。

当用户问「签到 / 帮我签到 / end 签到 / 终末地签到」时调用。
需绑定 cookie。用户主动授权 AI 代为执行，不算危险写操作。

Args:
    text: 无需参数。
""",
)
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


@end_sign_switch_sv.on_fullmatch(
    ("开启自动签到", "自动签到"),
    to_ai="""开启自己终末地 / 明日方舟账号的每日自动签到任务。

当用户问「开启自动签到 / 帮我开自动签到 / 终末地自动签到」时调用。需绑定 cookie。

Args:
    text: 无需参数。
""",
)
async def enable_auto_sign(bot: Bot, ev: Event):
    from ..utils.database.models import EndBind, EndUser

    bind_data = await EndBind.get_data_by_user_id(ev.user_id, ev.bot_id)
    if not bind_data or not bind_data.uid:
        return await bot.send(TIP_NOT_BOUND)

    # 收集所有游戏 UID（终末地 + 明日方舟）
    all_uids = [u for u in bind_data.uid.split("_") if u]
    if bind_data.ark_uid:
        all_uids.extend(u for u in bind_data.ark_uid.split("_") if u)

    for uid in all_uids:
        await EndUser.update_data_by_uid(uid, ev.bot_id, bbs_sign_switch="on")

    return await bot.send("✅ 已开启自动签到")


@end_sign_switch_sv.on_fullmatch(
    ("关闭自动签到", "停止自动签到"),
    to_ai="""关闭自己终末地 / 明日方舟账号的每日自动签到任务。

当用户问「关闭自动签到 / 停止自动签到 / 关掉自动签到」时调用。需已绑定。

Args:
    text: 无需参数。
""",
)
async def disable_auto_sign(bot: Bot, ev: Event):
    from ..utils.database.models import EndBind, EndUser

    bind_data = await EndBind.get_data_by_user_id(ev.user_id, ev.bot_id)
    if not bind_data or not bind_data.uid:
        return await bot.send(TIP_NOT_BOUND)

    # 收集所有游戏 UID（终末地 + 明日方舟）
    all_uids = [u for u in bind_data.uid.split("_") if u]
    if bind_data.ark_uid:
        all_uids.extend(u for u in bind_data.ark_uid.split("_") if u)

    for uid in all_uids:
        await EndUser.update_data_by_uid(uid, ev.bot_id, bbs_sign_switch="off")

    return await bot.send("✅ 已关闭自动签到")


# ===================== 删除无效token =====================

@end_del_invalid_sv.on_fullmatch(("删除无效token"), block=True)
async def delete_all_invalid_cookie(bot: Bot, ev: Event):
    from ..utils.database.models import EndUser
    at_sender = True if ev.group_id else False
    del_len = await EndUser.delete_all_invalid_cookie()
    msg = f"[EndUID] 已删除无效token【{del_len}】个"
    await bot.send((" " if at_sender else "") + msg, at_sender)


# ===================== 订阅签到结果 =====================

@end_sign_sub_sv.on_regex("^(订阅|取消订阅)签到结果$")
async def end_sign_result_sub(bot: Bot, ev: Event):

    if "取消" in ev.raw_text:
        option = "关闭"
    else:
        option = "开启"

    if ev.group_id and option == "开启":
        from ..utils.database.models import EndSubscribe
        await EndSubscribe.check_and_update_bot(ev.group_id, ev.bot_id, ev.bot_self_id)

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
            logger.info(f"[ENDUID·签到] 推送签到结果: {msg}")
            for sub in subscribes:
                await sub.send(msg)
    finally:
        signing_state.clear_state()


def setup_scheduler():
    """设置定时任务"""
    if not EndConfig.get_config("SchedSignin").data:
        logger.info("[ENDUID·签到] 定时签到未启用")
        return

    sign_time_config = EndConfig.get_config("SignTime").data
    sign_hour = int(sign_time_config[0])
    sign_minute = int(sign_time_config[1])

    logger.info(f"[ENDUID·签到] 设置定时签到: 每天 {sign_hour:02d}:{sign_minute:02d}")

    try:
        scheduler.add_job(
            end_scheduled_sign,
            "cron",
            id="end_sign_0",
            hour=sign_hour,
            minute=sign_minute,
            replace_existing=True,
        )
        logger.success("[ENDUID·签到] 定时签到任务已注册")
    except Exception as e:
        logger.error(f"[ENDUID·签到] 定时签到任务注册失败: {e}")


setup_scheduler()


# ===================== 清理签到记录 =====================

@scheduler.scheduled_job(
    "cron",
    hour=0,
    minute=5,
    id="end_sign_clear_record",
)
async def clear_end_sign_record():
    """每天 00:05 清除 2 天前的签到记录"""
    from ..utils.database.models import EndSignRecord

    two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    await EndSignRecord.clear_sign_records(two_days_ago)
    logger.info("[ENDUID·签到] 已清除2天前的签到记录")


# ===================== 重启续签 =====================

async def check_and_resume_end_signing():
    """启动时检查状态文件，如果有未完成的签到则继续执行"""
    if not signing_state.should_resume():
        return

    state = signing_state.get_state()
    if not state:
        return

    sign_type = state.get("type", "auto")
    logger.warning(f"[ENDUID·签到] 检测到未完成的签到任务，正在恢复: type={sign_type}")

    await asyncio.sleep(5)

    try:
        if sign_type == "auto":
            await end_scheduled_sign()
        else:
            signing_state.set_state("manual")
            await end_auto_sign()
            signing_state.clear_state()
    except Exception as e:
        logger.error(f"[ENDUID·签到] 恢复签到任务时出错: {e}")
        signing_state.clear_state()


startup_time = datetime.now() + timedelta(seconds=10)
scheduler.add_job(
    check_and_resume_end_signing,
    "date",
    run_date=startup_time,
    id="end_resume_signing_on_startup",
    replace_existing=True,
)
logger.info("[ENDUID·签到] 已注册启动恢复任务，将在启动后10秒检查未完成的签到")

logger.success("[ENDUID·签到] 签到模块加载完成")
