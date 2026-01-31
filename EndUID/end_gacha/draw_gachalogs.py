"""抽卡记录渲染上下文构建"""
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Union

import aiofiles
from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.database.models import EndBind
from ..utils.api.model import CardDetailResponse
from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..end_config import PREFIX
from ..utils.path import (
    AVATAR_CACHE_PATH,
    CHAR_CACHE_PATH,
    EQUIP_CACHE_PATH,
    PLAYER_PATH,
)
from .get_gachalogs import load_gachalogs


TEXTURE_PATH = Path(__file__).parent.parent / "end_char" / "texture2d"
TEMPLATE_PATH = Path(__file__).parent.parent / "templates"

end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

# 运气等级
LUCK_LEVELS = ["非到极致", "运气不好", "平稳保底", "小欧一把", "欧皇在此"]

# 角色池保底
CHAR_PITY = 80

# 常驻角色 ID（不算 UP）
STANDARD_CHAR_IDS = {
    "chr_0025_ardelia",
    "chr_0015_lifeng",
    "chr_0009_azrila",
}

# 常驻武器 ID（不算 UP）
STANDARD_WEAPON_IDS = {
    "wpn_pistol_0009",
    "wpn_pistol_0008",
    "wpn_claym_0006",
    "wpn_sword_0014",
}


def _format_gacha_ts(ts: str) -> str:
    """将 gachaTs 转换为可读日期 (支持 Unix 时间戳和 ISO 格式)"""
    if not ts:
        return ""
    try:
        ts_num = int(ts)
        if ts_num > 1e12:  # 毫秒
            ts_num = ts_num // 1000
        return datetime.fromtimestamp(ts_num).strftime("%Y.%m.%d")
    except (ValueError, OSError):
        pass
    return ts[:10].replace("-", ".")


def _calc_pool_stats(pool_name: str, records: list) -> dict:
    """计算单个池的统计数据

    Args:
        pool_name: 池名称
        records: 该池的记录列表（最新在前）

    Returns:
        池统计字典
    """
    is_weapon = pool_name.startswith("武器寻访")
    pool_type = "weapon" if is_weapon else "char"
    is_special = pool_name == "特许寻访"

    if not records:
        return {
            "pool_name": pool_name,
            "pool_type": pool_type,
            "total": 0,
            "six_star_count": 0,
            "avg_pulls": 0,
            "remain": 0,
            "time_range": "",
            "level": 2,
            "level_tag": LUCK_LEVELS[2],
            "six_star_items": [],
        }

    # 从旧到新排列以便计算
    sorted_records = list(reversed(records))

    total = len(sorted_records)
    six_star_items = []
    pull_counter = 0
    six_star_pull_counts = []

    for record in sorted_records:
        rarity = record.get("rarity", 0)
        is_free = record.get("isFree", False)

        # 特许寻访中免费抽不计入保底
        if is_special and is_free:
            continue

        pull_counter += 1

        if rarity == 6:
            six_star_pull_counts.append(pull_counter)

            if is_weapon:
                name = record.get("weaponName", "???")
                item_id = record.get("weaponId", "")
                is_up = item_id not in STANDARD_WEAPON_IDS
            else:
                name = record.get("charName", "???")
                item_id = record.get("charId", "")
                is_up = item_id not in STANDARD_CHAR_IDS

            six_star_items.append({
                "name": name,
                "pull_count": pull_counter,
                "type": pool_type,
                "item_id": item_id,
                "avatar": "",
                "is_up": is_up,
            })
            pull_counter = 0

    # 距离上次 UP 的抽数（跨过中间的常驻六星）
    remain = pull_counter
    for item in reversed(six_star_items):
        if item["is_up"]:
            break
        remain += item["pull_count"]

    # 六星平均抽数
    six_star_count = len(six_star_pull_counts)
    avg_pulls = (
        round(sum(six_star_pull_counts) / six_star_count, 1)
        if six_star_count > 0
        else 0
    )

    # 运气等级
    if six_star_count == 0:
        level = 2
    elif avg_pulls <= 30:
        level = 4
    elif avg_pulls <= 45:
        level = 3
    elif avg_pulls <= 60:
        level = 2
    elif avg_pulls <= 70:
        level = 1
    else:
        level = 0

    level_tag = LUCK_LEVELS[level]

    # 时间范围
    timestamps = [r.get("gachaTs", "") for r in records if r.get("gachaTs")]
    if timestamps:
        timestamps.sort()
        earliest = _format_gacha_ts(timestamps[0])
        latest = _format_gacha_ts(timestamps[-1])
        time_range = f"{earliest} - {latest}"
    else:
        time_range = ""

    # UP 角色/武器的颜色抽数: 累加前面连续常驻的抽数
    for i, item in enumerate(six_star_items):
        if item["is_up"]:
            color_pulls = item["pull_count"]
            j = i - 1
            while j >= 0 and not six_star_items[j]["is_up"]:
                color_pulls += six_star_items[j]["pull_count"]
                j -= 1
            item["color_pulls"] = color_pulls
        else:
            item["color_pulls"] = item["pull_count"]

    # 六星列表反转，最新的在前
    six_star_items.reverse()

    return {
        "pool_name": pool_name,
        "pool_type": pool_type,
        "total": total,
        "six_star_count": six_star_count,
        "avg_pulls": avg_pulls,
        "remain": remain,
        "time_range": time_range,
        "level": level,
        "level_tag": level_tag,
        "six_star_items": six_star_items,
    }


async def draw_gacha_card(ev: Event) -> Union[bytes, str]:
    """绘制抽卡记录卡片"""
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return f"未绑定终末地账号，请先使用「{PREFIX}绑定」"

    gacha_data = await load_gachalogs(uid)
    if not gacha_data:
        return f"未找到抽卡记录，请先使用「{PREFIX}导入抽卡记录」导入"

    pool_data = gacha_data.get("data", {})
    if not pool_data:
        return "抽卡记录为空"

    # 读取玩家基础信息 + UP 角色立绘 + 角色/武器头像映射
    name = uid
    level = 0
    avatar_b64 = ""
    illustration_b64 = ""
    # name -> avatarUrl 映射（角色和武器）
    char_avatar_map: dict[str, str] = {}
    weapon_icon_map: dict[str, str] = {}

    card_path = PLAYER_PATH / uid / "card_detail.json"
    if card_path.exists():
        try:
            async with aiofiles.open(card_path, "r", encoding="utf-8") as f:
                raw = await f.read()
            card_res = json.loads(raw)
            if card_res.get("code") == 0:
                detail = CardDetailResponse.model_validate(card_res).data.detail
                base = detail.base
                if base:
                    name = base.name or uid
                    level = base.level
                    if base.avatarUrl:
                        avatar_b64 = await get_image_b64_with_cache(
                            base.avatarUrl, AVATAR_CACHE_PATH
                        )

                # 查找最后一个 UP 角色的立绘 + 构建头像映射
                last_up_illustration = ""
                for char in detail.chars:
                    cd = char.charData
                    if cd:
                        if cd.name and cd.avatarSqUrl:
                            char_avatar_map[cd.name] = cd.avatarSqUrl
                        if cd.labelType == "label_type_up" and cd.illustrationUrl:
                            last_up_illustration = cd.illustrationUrl

                    # 武器头像映射
                    wd = char.weapon.weaponData if char.weapon else None
                    if wd and wd.name and wd.iconUrl:
                        weapon_icon_map[wd.name] = wd.iconUrl

                if last_up_illustration:
                    illustration_b64 = await get_image_b64_with_cache(
                        last_up_illustration, CHAR_CACHE_PATH
                    )
        except Exception as e:
            logger.warning(f"[EndUID][Gacha] 读取卡片详情失败: {e}")

    # 池显示顺序
    pool_order = ["特许寻访", "基础寻访", "启程寻访"]
    pools = []

    for pn in pool_order:
        if pn in pool_data:
            pools.append(_calc_pool_stats(pn, pool_data[pn]))

    # 武器池
    for pn in sorted(pool_data.keys()):
        if pn.startswith("武器寻访") and pn not in [p["pool_name"] for p in pools]:
            pools.append(_calc_pool_stats(pn, pool_data[pn]))

    # 其他未归类
    for pn in pool_data:
        if pn not in [p["pool_name"] for p in pools]:
            pools.append(_calc_pool_stats(pn, pool_data[pn]))

    # 为六星角色/武器解析头像
    for pool in pools:
        for item in pool.get("six_star_items", []):
            item_name = item.get("name", "")
            url = ""
            if item.get("type") == "weapon":
                url = weapon_icon_map.get(
                    item_name,
                    f"https://imgheybox.max-c.com/endfield/icon/{item_name}.png",
                )
            else:
                url = char_avatar_map.get(item_name, "")

            if url:
                try:
                    cache_path = (
                        EQUIP_CACHE_PATH
                        if item.get("type") == "weapon"
                        else AVATAR_CACHE_PATH
                    )
                    item["avatar"] = await get_image_b64_with_cache(
                        url, cache_path
                    )
                except Exception:
                    pass

    context = {
        "name": name,
        "uid": uid,
        "avatar": avatar_b64,
        "level": level,
        "pools": pools,
        "data_time": gacha_data.get("data_time", ""),
        "illustration": illustration_b64,
        "bg": image_to_base64(TEXTURE_PATH / "bg.png"),
        "end_logo": image_to_base64(TEXTURE_PATH / "end.png"),
        "up_tag": image_to_base64(TEXTURE_PATH / "up_tag.png"),
    }

    img_bytes = await render_html(end_templates, "end_gacha_card.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))

    return "HTML 渲染失败"


async def draw_gacha_help() -> Union[bytes, str]:
    """绘制抽卡帮助页"""
    context = {
        "prefix": PREFIX,
        "bg": image_to_base64(TEXTURE_PATH / "bg.png"),
        "end_logo": image_to_base64(TEXTURE_PATH / "end.png"),
    }

    img_bytes = await render_html(end_templates, "end_gacha_help.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))

    return "HTML 渲染失败"
