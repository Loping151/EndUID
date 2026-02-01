import time
import random
import asyncio
from pathlib import Path

from gsuid_core.sv import SV
from gsuid_core.aps import scheduler
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.subscribe import gs_subscribe

from .ann_card import ann_list_card, ann_detail_card
from ..utils.api.requests import end_api
from ..utils.database.models import EndSubscribe
from ..end_config import EndConfig
from ..utils.path import ANN_CACHE_PATH, ANN_RENDER_CACHE_PATH
from .utils.ann_config import get_ann_new_ids, set_ann_new_ids

sv_ann = SV("终末地公告")
sv_ann_sub = SV("订阅终末地公告", pm=3)
sv_ann_clear_cache = SV("终末地公告缓存清理", pm=0, priority=3)

# 缓存保留天数
CACHE_DAYS_TO_KEEP = 30

task_name_ann = "订阅终末地公告"
ann_minute_check: int = EndConfig.get_config("AnnMinuteCheck").data


@sv_ann.on_command("公告")
async def ann_(bot: Bot, ev: Event):
    ann_id = ev.text.strip()

    # 查看公告列表
    if not ann_id or ann_id == "列表":
        img = await ann_list_card()
        return await bot.send(img)

    # 处理 #号
    ann_id = ann_id.replace("#", "").strip()

    if ann_id.isdigit():
        img = await ann_detail_card(int(ann_id))
    else:
        img = await ann_detail_card(ann_id)

    await bot.send(img)


@sv_ann_sub.on_fullmatch("订阅公告")
async def sub_ann_(bot: Bot, ev: Event):
    if ev.bot_id != "onebot":
        logger.debug(f"非onebot禁止订阅终末地公告 【{ev.bot_id}】")
        return

    if ev.group_id is None:
        return await bot.send("请在群聊中订阅")

    if not EndConfig.get_config("AnnOpen").data:
        return await bot.send("终末地公告推送功能已关闭")

    logger.info(
        f"[终末地公告] 群 {ev.group_id} 订阅公告，bot_id={ev.bot_id}, bot_self_id={ev.bot_self_id}"
    )

    if ev.group_id:
        await EndSubscribe.check_and_update_bot(ev.group_id, ev.bot_self_id)

    data = await gs_subscribe.get_subscribe(task_name_ann)
    is_resubscribe = False
    if data:
        for subscribe in data:
            if subscribe.group_id == ev.group_id:
                await gs_subscribe.delete_subscribe("session", task_name_ann, ev)
                is_resubscribe = True
                logger.info(f"[终末地公告] 群 {ev.group_id} 重新订阅，已删除旧订阅")
                break

    await gs_subscribe.add_subscribe(
        "session",
        task_name=task_name_ann,
        event=ev,
        extra_message="",
    )

    if is_resubscribe:
        await bot.send("已重新订阅终末地公告！")
    else:
        await bot.send("成功订阅终末地公告!")


@sv_ann_sub.on_fullmatch(("取消订阅公告", "取消公告", "退订公告"))
async def unsub_ann_(bot: Bot, ev: Event):
    if ev.bot_id != "onebot":
        logger.debug(f"非onebot禁止订阅终末地公告 【{ev.bot_id}】")
        return

    if ev.group_id is None:
        return await bot.send("请在群聊中取消订阅")

    data = await gs_subscribe.get_subscribe(task_name_ann)
    if data:
        for subscribe in data:
            if subscribe.group_id == ev.group_id:
                await gs_subscribe.delete_subscribe("session", task_name_ann, ev)
                return await bot.send("成功取消订阅终末地公告!")
    else:
        if not EndConfig.get_config("AnnOpen").data:
            return await bot.send("终末地公告推送功能已关闭")

    return await bot.send("未曾订阅终末地公告！")


@scheduler.scheduled_job("interval", minutes=ann_minute_check)
async def check_end_ann():
    if not EndConfig.get_config("AnnOpen").data:
        return
    await check_end_ann_state()


async def check_end_ann_state():
    logger.info("[终末地公告] 定时任务: 终末地公告查询..")
    datas = await gs_subscribe.get_subscribe(task_name_ann)
    if not datas:
        logger.info("[终末地公告] 暂无群订阅")
        return

    ids = get_ann_new_ids()
    new_ann_list = await end_api.get_ann_list()
    if not new_ann_list:
        return

    new_ann_ids = [x["id"] for x in new_ann_list]
    if not ids:
        set_ann_new_ids(new_ann_ids)
        logger.info("[终末地公告] 初始成功, 将在下个轮询中更新.")
        return

    new_ann_need_send = []
    for ann_id in new_ann_ids:
        if ann_id not in ids:
            new_ann_need_send.append(ann_id)

    if not new_ann_need_send:
        logger.info("[终末地公告] 没有最新公告")
        return

    logger.info(f"[终末地公告] 更新公告id: {new_ann_need_send}")
    save_ids = sorted(ids, reverse=True) + new_ann_ids
    set_ann_new_ids(list(set(save_ids)))

    for ann_id in new_ann_need_send:
        try:
            img = await ann_detail_card(ann_id, is_check_time=True)
            if isinstance(img, str):
                continue
            for subscribe in datas:
                await subscribe.send(img)
                await asyncio.sleep(random.uniform(1, 3))
        except Exception as e:
            logger.exception(e)

    logger.info("[终末地公告] 推送完毕")


# ===================== 缓存清理 =====================

def clean_old_cache_files(directory: Path, days: int) -> tuple[int, float]:
    """清理超过指定天数的缓存文件"""
    if not directory.exists():
        logger.debug(f"目录不存在: {directory}")
        return 0, 0.0

    current_time = time.time()
    cutoff_time = current_time - (days * 86400)

    deleted_count = 0
    freed_space = 0.0

    try:
        for file_path in directory.iterdir():
            if not file_path.is_file():
                continue

            file_ctime = file_path.stat().st_ctime

            if file_ctime < cutoff_time:
                try:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_count += 1
                    freed_space += file_size
                    logger.debug(f"删除过期缓存文件: {file_path.name}")
                except Exception as e:
                    logger.error(f"删除文件失败 {file_path.name}: {e}")
    except Exception as e:
        logger.error(f"清理目录失败 {directory}: {e}")

    freed_space_mb = freed_space / (1024 * 1024)
    return deleted_count, freed_space_mb


async def clean_cache_directories(days: int) -> str:
    """清理公告缓存目录"""
    total_count = 0
    total_space = 0.0

    ann_count, ann_space = clean_old_cache_files(ANN_CACHE_PATH, days)
    if ann_count > 0:
        total_count += ann_count
        total_space += ann_space

    r_count, r_space = clean_old_cache_files(ANN_RENDER_CACHE_PATH, days)
    if r_count > 0:
        total_count += r_count
        total_space += r_space

    if total_count == 0:
        return f"[终末地] 没有找到需要清理的缓存文件(保留{days}天内的文件)"

    return f"[终末地] 清理完成！共删除{total_count}个文件，释放{total_space:.2f}MB"


@sv_ann_clear_cache.on_fullmatch(("end清理缓存", "end删除缓存"), block=True)
async def end_clean_cache_(bot: Bot, ev: Event):
    """手动清理缓存指令"""
    logger.info(f"[EndUID][缓存清理] 手动触发清理，保留{CACHE_DAYS_TO_KEEP}天内的文件")

    result = await clean_cache_directories(CACHE_DAYS_TO_KEEP)
    await bot.send(result)


@scheduler.scheduled_job("cron", hour=3, minute=30)
async def end_auto_clean_cache_daily():
    """每天凌晨3:30自动清理终末地缓存"""
    logger.info(f"[EndUID][缓存清理] 定时任务: 开始清理缓存，保留{CACHE_DAYS_TO_KEEP}天内的文件")

    result = await clean_cache_directories(CACHE_DAYS_TO_KEEP)
    logger.info(f"[EndUID][缓存清理] {result}")


@scheduler.scheduled_job("date")
async def end_clean_cache_on_startup():
    """启动时清理一次终末地缓存"""
    await asyncio.sleep(10)

    logger.info(f"[EndUID][缓存清理] 启动时清理，保留{CACHE_DAYS_TO_KEEP}天内的文件")

    result = await clean_cache_directories(CACHE_DAYS_TO_KEEP)
    logger.info(f"[EndUID][缓存清理] {result}")
