"""抽卡记录获取、存储、合并、导出、删除"""
import asyncio
import json
import shutil
from datetime import datetime
from typing import Optional

import aiofiles
from gsuid_core.logger import logger

from ..utils.api.requests import end_api
from ..utils.path import PLAYER_PATH


CHAR_POOL_TYPE_MAP = {
    "E_CharacterGachaPoolType_Special": "特许寻访",
    "E_CharacterGachaPoolType_Standard": "基础寻访",
    "E_CharacterGachaPoolType_Beginner": "启程寻访",
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


def _seq_id_sort_key(record: dict) -> tuple:
    """按 seqId 降序排序键 (兼容纯数字和字符串 seqId)"""
    sid = record.get("seqId", "")
    try:
        return (1, int(sid))
    except (ValueError, TypeError):
        return (0, sid)


def _merge_records(old_list: list, new_list: list) -> list:
    """合并记录列表，按 seqId 去重，按 seqId 降序排序"""
    existing_ids = {r.get("seqId") for r in old_list if r.get("seqId")}
    unique_new = [r for r in new_list if r.get("seqId") and r["seqId"] not in existing_ids]

    if not unique_new:
        return old_list

    merged = old_list + unique_new
    merged.sort(key=_seq_id_sort_key, reverse=True)
    return merged


async def get_new_gachalog(
    uid: str,
    u8_token: str,
    server_id: str = "1",
) -> tuple[bool, str, dict]:
    """拉取全部抽卡记录并与本地合并

    Returns:
        (成功, 消息, 合并后数据)
    """
    old_data = await load_gachalogs(uid) or {}
    old_pool_data = old_data.get("data", {})

    new_pool_data = {}
    total_new = 0
    first_error = ""

    for pool_type, pool_name in CHAR_POOL_TYPE_MAP.items():
        logger.info(f"[EndUID][Gacha] 拉取 {pool_name} (pool_type={pool_type})")
        records = []
        seq_id = None

        for page in range(100):
            res = await end_api.get_gacha_char_record(
                u8_token=u8_token,
                server_id=server_id,
                pool_type=pool_type,
                seq_id=seq_id,
            )
            if not res:
                logger.warning(f"[EndUID][Gacha] {pool_name} 请求失败")
                break

            code = res.get("code")
            if code is not None and code != 0:
                msg = res.get("msg") or res.get("message") or "未知错误"
                if not first_error:
                    first_error = f"{pool_name}: {msg} (code={code})"
                logger.warning(f"[EndUID][Gacha] {pool_name} 错误: {msg}")
                break

            data = res.get("data", {})
            data_list = data.get("list", [])
            if not data_list:
                break

            records.extend(data_list)
            logger.debug(
                f"[EndUID][Gacha] {pool_name} 第{page+1}页: {len(data_list)}条"
            )

            if not data.get("hasMore", False):
                break

            seq_id = data_list[-1].get("seqId")
            if not seq_id:
                break

            await asyncio.sleep(0.2)  # 避免请求过快

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

    weapon_pools_res = await end_api.get_gacha_weapon_pools(
        u8_token=u8_token,
        server_id=server_id,
    )

    weapon_pool_list = []
    if weapon_pools_res and weapon_pools_res.get("code", 0) == 0:
        wp_data = weapon_pools_res.get("data")
        if isinstance(wp_data, list):
            weapon_pool_list = wp_data
        elif isinstance(wp_data, dict):
            weapon_pool_list = wp_data.get("list", [])

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
            )
            if not res:
                break

            code = res.get("code")
            if code is not None and code != 0:
                break

            data = res.get("data", {})
            data_list = data.get("list", [])
            if not data_list:
                break

            records.extend(data_list)

            if not data.get("hasMore", False):
                break

            seq_id = data_list[-1].get("seqId")
            if not seq_id:
                break

            await asyncio.sleep(0.5)

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

    for key, val in old_pool_data.items():
        if key not in new_pool_data:
            new_pool_data[key] = val

    result = {
        "uid": uid,
        "data_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": new_pool_data,
    }

    if not new_pool_data:
        err = first_error or "所有池均无数据"
        return False, f"请求失败: {err}", {}

    if total_new > 0:
        await save_gachalogs(uid, result)

    total_records = sum(len(v) for v in new_pool_data.values())
    msg = f"导入完成！新增 {total_new} 条，共 {total_records} 条记录"
    if first_error:
        msg += f"\n（部分池请求失败: {first_error}）"
    return True, msg, result


async def import_from_json(uid: str, raw_json: str) -> tuple[bool, str]:
    """从 JSON 字符串导入抽卡记录 (支持 gacha_logs.json 源文件格式)

    Returns:
        (成功, 消息)
    """
    try:
        incoming = json.loads(raw_json)
    except json.JSONDecodeError as e:
        return False, f"JSON 解析失败: {e}"

    if "data" in incoming and isinstance(incoming["data"], dict):
        import_pool_data = incoming["data"]
    elif all(isinstance(v, list) for v in incoming.values()):
        import_pool_data = incoming
    else:
        return False, "无法识别的 JSON 格式，需包含 data 字段或直接为池数据"

    if not import_pool_data:
        return False, "JSON 中无抽卡记录数据"

    old_data = await load_gachalogs(uid) or {}
    old_pool_data = old_data.get("data", {})

    total_new = 0
    merged_pool_data = dict(old_pool_data)

    for pool_name, records in import_pool_data.items():
        if not isinstance(records, list):
            continue
        old_list = merged_pool_data.get(pool_name, [])
        merged = _merge_records(old_list, records)
        new_count = len(merged) - len(old_list)
        total_new += max(0, new_count)
        merged_pool_data[pool_name] = merged

    if total_new > 0:
        result = {
            "uid": uid,
            "data_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data": merged_pool_data,
        }
        await save_gachalogs(uid, result)

    total_records = sum(len(v) for v in merged_pool_data.values())
    return True, f"导入完成！新增 {total_new} 条，共 {total_records} 条记录"


async def export_gachalogs(uid: str) -> Optional[dict]:
    """导出抽卡记录为文件并返回文件信息"""
    data = await load_gachalogs(uid)
    if not data:
        return None

    path = PLAYER_PATH / uid
    path.mkdir(parents=True, exist_ok=True)
    export_path = path / f"export_{uid}.json"

    async with aiofiles.open(export_path, "w", encoding="UTF-8") as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=2))

    return {
        "name": f"EndUID_gacha_{uid}.json",
        "url": str(export_path.absolute()),
    }


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
