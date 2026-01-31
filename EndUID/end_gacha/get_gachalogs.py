"""抽卡记录获取、存储、合并、导出、删除"""
import json
import shutil
from datetime import datetime
from typing import Optional

import aiofiles
from gsuid_core.logger import logger

from ..utils.api.requests import end_api
from ..utils.path import PLAYER_PATH


# 角色池类型映射: pool_type -> 显示名
CHAR_POOL_TYPE_MAP = {
    0: "特许寻访",
    1: "基础寻访",
    2: "启程寻访",
}


async def load_gachalogs(uid: str) -> Optional[dict]:
    """读取已保存的抽卡记录"""
    path = PLAYER_PATH / uid / "gacha_logs.json"
    if not path.exists():
        return None
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            raw = await f.read()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"[EndUID][Gacha] 读取抽卡记录失败: {e}")
        return None


async def save_gachalogs(uid: str, gacha_data: dict):
    """保存抽卡记录"""
    player_dir = PLAYER_PATH / uid
    player_dir.mkdir(parents=True, exist_ok=True)
    path = player_dir / "gacha_logs.json"
    try:
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(gacha_data, ensure_ascii=False, indent=2))
        logger.info(f"[EndUID][Gacha] 保存抽卡记录成功: uid={uid}")
    except Exception as e:
        logger.error(f"[EndUID][Gacha] 保存抽卡记录失败: {e}")


def _merge_records(old_list: list, new_list: list) -> list:
    """合并记录列表，按 seqId 去重，按 gachaTs 降序排序"""
    seen = set()
    merged = []
    for record in old_list + new_list:
        seq_id = record.get("seqId", "")
        if seq_id and seq_id in seen:
            continue
        if seq_id:
            seen.add(seq_id)
        merged.append(record)

    merged.sort(key=lambda x: x.get("gachaTs", ""), reverse=True)
    return merged


async def get_new_gachalog(
    uid: str,
    u8_token: str,
    server_id: str = "1",
    channel: str = "1",
    sub_channel: str = "1",
) -> tuple[bool, str, dict]:
    """拉取全部抽卡记录并与本地合并

    Returns:
        (成功, 消息, 合并后数据)
    """
    old_data = await load_gachalogs(uid) or {}
    old_pool_data = old_data.get("data", {})

    new_pool_data = {}
    total_new = 0

    # 1. 拉取角色池（特许/基础/启程）
    for pool_type, pool_name in CHAR_POOL_TYPE_MAP.items():
        logger.info(f"[EndUID][Gacha] 拉取 {pool_name} (poolType={pool_type})")
        records = []
        seq_id = None

        for page in range(100):  # 安全上限
            res = await end_api.get_gacha_char_record(
                u8_token=u8_token,
                server_id=server_id,
                pool_type=pool_type,
                seq_id=seq_id,
                channel=channel,
                sub_channel=sub_channel,
            )
            if not res:
                logger.warning(f"[EndUID][Gacha] {pool_name} 请求失败")
                break

            code = res.get("code")
            if code is not None and code != 0:
                msg = res.get("msg") or res.get("message") or "未知错误"
                if page == 0:
                    return False, f"请求失败: {msg} (code={code})", {}
                break

            data_list = res.get("data", {}).get("list", [])
            if not data_list:
                break

            records.extend(data_list)
            logger.debug(
                f"[EndUID][Gacha] {pool_name} 第{page+1}页: {len(data_list)}条"
            )

            # 分页: 取最后一条的 seqId
            seq_id = data_list[-1].get("seqId")
            if not seq_id:
                break

        if records:
            old_list = old_pool_data.get(pool_name, [])
            merged = _merge_records(old_list, records)
            new_count = len(merged) - len(old_list)
            total_new += max(0, new_count)
            new_pool_data[pool_name] = merged
            logger.info(
                f"[EndUID][Gacha] {pool_name}: 新增{max(0, new_count)}条，"
                f"合计{len(merged)}条"
            )
        elif pool_name in old_pool_data:
            new_pool_data[pool_name] = old_pool_data[pool_name]

    # 2. 拉取武器池
    weapon_pools_res = await end_api.get_gacha_weapon_pools(
        u8_token=u8_token,
        server_id=server_id,
        channel=channel,
        sub_channel=sub_channel,
    )

    weapon_pool_list = []
    if weapon_pools_res and weapon_pools_res.get("code", 0) == 0:
        weapon_pool_list = weapon_pools_res.get("data", {}).get("list", [])

    for pool_info in weapon_pool_list:
        pool_id = pool_info.get("poolId", "")
        pool_name = pool_info.get("poolName", pool_id)
        display_name = f"武器寻访-{pool_name}"

        logger.info(f"[EndUID][Gacha] 拉取 {display_name} (poolId={pool_id})")
        records = []
        seq_id = None

        for page in range(100):
            res = await end_api.get_gacha_weapon_record(
                u8_token=u8_token,
                server_id=server_id,
                pool_id=pool_id,
                seq_id=seq_id,
                channel=channel,
                sub_channel=sub_channel,
            )
            if not res:
                break

            code = res.get("code")
            if code is not None and code != 0:
                break

            data_list = res.get("data", {}).get("list", [])
            if not data_list:
                break

            records.extend(data_list)
            seq_id = data_list[-1].get("seqId")
            if not seq_id:
                break

        if records:
            old_list = old_pool_data.get(display_name, [])
            merged = _merge_records(old_list, records)
            new_count = len(merged) - len(old_list)
            total_new += max(0, new_count)
            new_pool_data[display_name] = merged
            logger.info(
                f"[EndUID][Gacha] {display_name}: 新增{max(0, new_count)}条，"
                f"合计{len(merged)}条"
            )
        elif display_name in old_pool_data:
            new_pool_data[display_name] = old_pool_data[display_name]

    # 保留旧数据中存在但本次未拉到的池
    for key, val in old_pool_data.items():
        if key not in new_pool_data:
            new_pool_data[key] = val

    result = {
        "uid": uid,
        "data_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": new_pool_data,
    }

    await save_gachalogs(uid, result)

    total_records = sum(len(v) for v in new_pool_data.values())
    msg = f"导入完成！新增 {total_new} 条，共 {total_records} 条记录"
    return True, msg, result


async def export_gachalogs(uid: str) -> Optional[str]:
    """导出抽卡记录为 JSON 字符串"""
    data = await load_gachalogs(uid)
    if not data:
        return None
    return json.dumps(data, ensure_ascii=False, indent=2)


async def delete_gachalogs(uid: str) -> bool:
    """删除抽卡记录（备份后删除）"""
    path = PLAYER_PATH / uid / "gacha_logs.json"
    if not path.exists():
        return False

    try:
        backup_path = path.with_suffix(".json.bak")
        shutil.copy2(str(path), str(backup_path))
        path.unlink()
        logger.info(f"[EndUID][Gacha] 已删除抽卡记录: uid={uid}（已备份）")
        return True
    except Exception as e:
        logger.error(f"[EndUID][Gacha] 删除抽卡记录失败: {e}")
        return False
