"""EndUID 签到处理逻辑"""
import asyncio
import random
from typing import Optional, Dict, List, Tuple
from datetime import datetime

from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.segment import MessageSegment

from ..utils.api.requests import end_api
from ..utils.api.request_util import RespCode
from ..utils.constants import ARKNIGHTS_GAME_ID, ENDFIELD_GAME_ID
from ..utils.database.models import EndBind, EndUser, EndSignRecord, EndSubscribe
from ..utils.status_store import record_fail, record_success
from ..end_config import EndConfig, PREFIX


async def end_sign_handler(bot: Bot, ev: Event) -> str:
    """用户签到处理（签到该用户绑定的所有游戏 UID）"""
    users = await EndUser.select_data_list(user_id=ev.user_id, bot_id=ev.bot_id)
    users = [u for u in users if u.cookie]
    if not users:
        return f"未绑定账号，请先使用「{PREFIX}登录」"

    GAME_NAMES = {ENDFIELD_GAME_ID: "终末地", ARKNIGHTS_GAME_ID: "明日方舟"}
    results = []
    for user in users:
        game_name = GAME_NAMES.get(user.game_id, "")
        nickname = user.nickname or user.uid
        display = f"{game_name} {nickname}" if game_name else nickname
        result = await do_sign_in(
            user.uid, user.cookie, display,
            game_id=user.game_id,
            user_id=user.user_id, bot_id=user.bot_id,
        )
        results.append(result)

    return "\n".join(results)


async def do_sign_in(
    uid: str,
    cred: str,
    nickname: str,
    game_id: int = ENDFIELD_GAME_ID,
    user_id: str = "",
    bot_id: str = "",
) -> str:
    """执行签到操作

    Args:
        uid: 游戏 UID
        cred: 森空岛 Cred
        nickname: 游戏昵称
        game_id: 游戏 ID
        user_id: QQ 用户 ID（凭证失效时用于 mark_invalid，留空则跳过）
        bot_id: bot 平台 ID（同上）

    Returns:
        签到结果消息
    """
    if game_id == ARKNIGHTS_GAME_ID:
        res = await end_api.ark_attendance(cred, uid)
    else:
        res = await end_api.attendance(cred, uid)

    if res is None:
        record_fail()
        return f"❌ [{nickname}] 签到请求失败"

    code = res.get("code")

    # 签到成功
    if code == 0:
        record_success()
        data = res.get("data", {})
        awards = _extract_awards(data)

        msg = f"✅ [{nickname}] 签到完成！此次签到获得了:"

        if awards:
            for resource_name, count in awards:
                msg += f"\n  • {resource_name} × {count}"
        else:
            msg += "\n  • (暂无奖励信息)"

        return msg

    # 今日已签到
    elif code == 10001:
        return f"ℹ️ [{nickname}] 今天已经签到过了"

    # 凭证失效
    elif code in (RespCode.CRED_INVALID, RespCode.TOKEN_INVALID, RespCode.LOGIN_EXPIRED):
        record_fail()
        logger.warning(f"[ENDUID·签到] {nickname} 凭证失效（code={code}），标记为无效")
        if user_id and bot_id:
            await EndUser.mark_invalid(uid, user_id, bot_id, game_id)
        return f"❌ [{nickname}] 签到失败（凭证失效，请重新登录）"

    # 其他错误
    else:
        record_fail()
        message = res.get("message", "未知错误")
        logger.warning(f"[ENDUID·签到] 签到失败: {res}")
        return f"❌ [{nickname}] 签到失败: {message}"


async def end_auto_sign() -> str:
    """自动签到任务"""
    logger.info("[ENDUID·签到] 自动签到任务开始")

    # 获取所有用户
    all_users = await EndUser.get_all_data()

    # 筛选启用了签到的用户
    candidate_users = [
        user for user in all_users
        if user.cookie and user.cookie_status != "无效" and (user.bbs_sign_switch == "on" or EndConfig.get_config("SigninMaster").data)
    ]

    if not candidate_users:
        logger.info("[ENDUID·签到] 没有需要签到的用户")
        return "[EndUID] 没有需要签到的用户"

    # 跳过今日已签到的用户
    sign_users = []
    skipped_count = 0
    for user in candidate_users:
        record = await EndSignRecord.get_sign_record(user.uid)
        if record and record.sign_status == 1:
            skipped_count += 1
            continue
        sign_users.append(user)

    if skipped_count > 0:
        logger.info(f"[ENDUID·签到] 跳过 {skipped_count} 个今日已签到的用户")

    if not sign_users:
        logger.info("[ENDUID·签到] 所有用户今日已签到，无需执行")
        return f"[EndUID] 所有 {len(candidate_users)} 个用户今日已签到"

    logger.info(f"[ENDUID·签到] 开始为 {len(sign_users)} 个用户签到")

    # 签到结果统计
    success_count = 0
    signed_count = 0
    fail_count = 0
    failed_users: List[EndUser] = []

    # 获取配置
    concurrent_num = EndConfig.get_config("SigninConcurrentNum").data
    interval_config = EndConfig.get_config("SigninConcurrentNumInterval").data
    min_interval = int(interval_config[0])
    max_interval = int(interval_config[1])

    # 分批签到
    for i in range(0, len(sign_users), concurrent_num):
        batch = sign_users[i:i + concurrent_num]
        tasks = []

        for user in batch:
            task = do_sign_in_with_result(user)
            tasks.append(task)

        # 并发执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计结果
        for user, result in zip(batch, results):
            if isinstance(result, Exception):
                fail_count += 1
                failed_users.append(user)
                logger.error(f"[ENDUID·签到] 签到异常: {result}")
            elif isinstance(result, dict):
                if result["status"] == "success":
                    success_count += 1
                elif result["status"] == "signed":
                    signed_count += 1
                else:
                    fail_count += 1
                    failed_users.append(user)

        # 批次间隔
        if i + concurrent_num < len(sign_users):
            sleep_time = random.uniform(min_interval, max_interval)
            await asyncio.sleep(sleep_time)

    # 记录结果
    total = len(sign_users)
    summary = (
        f"[EndUID] 签到完成: 共 {total} 人 | "
        f"成功 {success_count} | 已签 {signed_count} | 失败 {fail_count}"
    )
    if skipped_count > 0:
        summary += f" | 跳过 {skipped_count}"

    logger.info(summary)

    record_success(success_count)
    record_fail(fail_count)

    # 构建推送消息
    private_msgs, group_msgs = await build_sign_report_msgs(
        sign_users, success_count, signed_count, fail_count, failed_users
    )

    # 发送推送
    await send_sign_report(private_msgs, group_msgs)

    return summary


async def do_sign_in_with_result(
    user: EndUser,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> Dict:
    """执行签到并返回结构化结果（失败自动重试）

    Args:
        user: 用户对象
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）

    Returns:
        签到结果字典: {"status": "success/signed/fail", "message": "..."}
    """
    display_uid = user.uid or user.nickname

    for attempt in range(1, max_retries + 1):
        try:
            if user.game_id == ARKNIGHTS_GAME_ID:
                res = await end_api.ark_attendance(user.cookie, user.uid)
            else:
                res = await end_api.attendance(user.cookie, user.uid)

            if res is None:
                if attempt < max_retries:
                    logger.warning(
                        f"[ENDUID·签到] {display_uid} 签到请求失败，第 {attempt}/{max_retries} 次重试"
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                return {"status": "fail", "message": f"[{display_uid}] 签到请求失败（已重试{max_retries}次）"}

            code = res.get("code")

            if code == 0:
                logger.info(f"[ENDUID·签到] {display_uid} 签到成功")
                await EndSignRecord.mark_signed(user.uid)
                return {"status": "success", "message": f"[{display_uid}] 签到成功"}
            elif code == 10001:
                logger.info(f"[ENDUID·签到] {display_uid} 今日已签到")
                await EndSignRecord.mark_signed(user.uid)
                return {"status": "signed", "message": f"[{display_uid}] 今日已签到"}
            elif code in (RespCode.CRED_INVALID, RespCode.TOKEN_INVALID, RespCode.LOGIN_EXPIRED):
                logger.warning(f"[ENDUID·签到] {display_uid} 凭证失效（code={code}），标记为无效")
                await EndUser.mark_invalid(user.uid, user.user_id, user.bot_id, user.game_id)
                return {"status": "fail", "message": f"[{display_uid}] 签到失败（凭证失效）"}
            else:
                if attempt < max_retries:
                    logger.warning(
                        f"[ENDUID·签到] {display_uid} 签到失败（code={code}），第 {attempt}/{max_retries} 次重试"
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                logger.warning(f"[ENDUID·签到] {display_uid} 签到失败（已重试{max_retries}次）: {res}")
                return {"status": "fail", "message": f"[{display_uid}] 签到失败"}

        except Exception as e:
            if attempt < max_retries:
                logger.warning(
                    f"[ENDUID·签到] {display_uid} 签到异常（第 {attempt}/{max_retries} 次重试）: {e}"
                )
                await asyncio.sleep(retry_delay)
                continue
            logger.error(f"[ENDUID·签到] {display_uid} 签到异常（已重试{max_retries}次）: {e}")
            return {"status": "fail", "message": f"[{display_uid}] 签到异常"}

    return {"status": "fail", "message": f"[{display_uid}] 签到失败"}


def _extract_awards(data: Dict) -> List[Tuple[str, int]]:
    """从签到返回数据中提取奖励信息"""
    awards: List[Tuple[str, int]] = []

    raw_awards = data.get("awards")
    if isinstance(raw_awards, list):
        for item in raw_awards:
            if not isinstance(item, dict):
                continue
            resource_info = item.get("resource") or {}
            resource_name = resource_info.get("name") or "未知物品"
            count = item.get("count") or 0
            awards.append((resource_name, int(count)))

    if awards:
        return awards

    award_ids = data.get("awardIds")
    resource_info_map = data.get("resourceInfoMap")
    if not isinstance(award_ids, list) or not isinstance(resource_info_map, dict):
        return awards

    for award_item in award_ids:
        award_id = None
        count = 0

        if isinstance(award_item, dict):
            award_id = award_item.get("id")
            count = award_item.get("count") or 0
        else:
            award_id = award_item

        if award_id is None:
            continue

        resource = resource_info_map.get(award_id)
        if resource is None:
            resource = resource_info_map.get(str(award_id))

        if isinstance(resource, dict):
            resource_name = resource.get("name") or "未知物品"
            if not count:
                count = resource.get("count") or resource.get("num") or 0
        else:
            resource_name = "未知物品"

        awards.append((resource_name, int(count)))

    return awards


async def build_sign_report_msgs(
    sign_users: List[EndUser],
    success_count: int,
    signed_count: int,
    fail_count: int,
    failed_users: Optional[List[EndUser]] = None,
) -> Tuple[Dict, Dict]:
    """构建签到报告消息

    Args:
        sign_users: 签到用户列表
        success_count: 成功数量
        signed_count: 已签数量
        fail_count: 失败数量
        failed_users: 签到失败的用户列表

    Returns:
        (私聊消息字典, 群消息字典)
    """
    private_msgs = {}
    group_msgs = {}

    if failed_users is None:
        failed_users = []

    failed_user_ids = {(u.user_id, u.bot_id) for u in failed_users}

    # 是否启用推送
    enable_private = EndConfig.get_config("PrivateSignReport").data
    enable_group = EndConfig.get_config("GroupSignReport").data

    if not enable_private and not enable_group:
        return private_msgs, group_msgs

    # 构建私聊消息
    if enable_private:
        for user in sign_users:
            user_id = user.user_id
            bot_id = user.bot_id

            msg = f"✅ 「终末地」 今日签到任务已完成"

            if user_id not in private_msgs:
                private_msgs[user_id] = {}

            if bot_id not in private_msgs[user_id]:
                private_msgs[user_id][bot_id] = []

            private_msgs[user_id][bot_id].append(msg)

    # 构建群消息
    if enable_group:
        # 按群组织用户
        group_users: Dict[str, List[EndUser]] = {}
        user_group_cache: Dict[tuple[str, str], list[str]] = {}

        for user in sign_users:
            key = (user.user_id, user.bot_id)
            if key not in user_group_cache:
                user_group_cache[key] = await EndBind.get_group_ids(user.user_id, user.bot_id)

            for group_id in user_group_cache[key]:
                if group_id not in group_users:
                    group_users[group_id] = []
                group_users[group_id].append(user)

        # 为每个群构建消息
        for group_id, users in group_users.items():
            if not users:
                continue

            # 统计本群用户
            group_success = sum(1 for u in users if u.cookie_status != "无效")

            title = (
                f"✅ 「终末地」 今日签到任务已完成！\n"
                f"本群共签到成功 {group_success} 人\n"
            )

            # 从群组绑定表获取 bot_self_id，如果没有则 fallback 到第一个 user 的 bot_id
            bot_id = await EndSubscribe.get_group_bot(group_id)
            if not bot_id:
                bot_id = users[0].bot_id
                logger.debug(f"[ENDUID·签到] 群 {group_id} 未在 EndSubscribe 中找到绑定，使用 fallback bot_id: {bot_id}")

            if group_id not in group_msgs:
                group_msgs[group_id] = {}

            if bot_id not in group_msgs[group_id]:
                group_msgs[group_id][bot_id] = []

            # 构建完整消息（标题 + at 失败成员）
            messages = [MessageSegment.text(title)]
            for user in users:
                if (user.user_id, user.bot_id) in failed_user_ids:
                    messages.extend([
                        MessageSegment.text("\n"),
                        MessageSegment.at(user.user_id),
                        MessageSegment.text(" 签到失败"),
                    ])
            group_msgs[group_id][bot_id].append(messages)

    return private_msgs, group_msgs


async def send_sign_report(private_msgs: Dict, group_msgs: Dict) -> None:
    """发送签到报告

    Args:
        private_msgs: 私聊消息字典 {user_id: {bot_id: [messages]}}
        group_msgs: 群消息字典 {group_id: {bot_id: [messages]}}
    """
    from gsuid_core.gss import gss

    for user_id, bot_data in private_msgs.items():
        for bot_id, messages in bot_data.items():
            for active_id in gss.active_bot:
                try:
                    for msg in messages:
                        await gss.active_bot[active_id].target_send(
                            msg, "direct", user_id, bot_id, "", ""
                        )
                        await asyncio.sleep(0.5 + random.uniform(1, 3))
                except Exception as e:
                    logger.error(f"[ENDUID·签到] 私聊推送失败 ({user_id}): {e}")

    for group_id, bot_data in group_msgs.items():
        for bot_id, messages in bot_data.items():
            for active_id in gss.active_bot:
                try:
                    for msg in messages:
                        await gss.active_bot[active_id].target_send(
                            msg, "group", group_id, bot_id, "", ""
                        )
                        await asyncio.sleep(0.5 + random.uniform(1, 3))
                except Exception as e:
                    logger.error(f"[ENDUID·签到] 群推送失败 ({group_id}): {e}")
