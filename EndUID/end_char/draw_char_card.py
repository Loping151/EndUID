import io
import json
from pathlib import Path
from typing import Optional, Union

import aiofiles
from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.utils.image.convert import convert_img
from gsuid_core.models import Event
from gsuid_core.logger import logger

from ..utils.alias_map import resolve_alias_entry, update_alias_map_from_chars
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
    SKILL_CACHE_PATH,
    EQUIP_CACHE_PATH,
    PLAYER_PATH,
)

# 资源路径
TEXTURE_PATH = Path(__file__).parent / "texture2d"
TEMPLATE_PATH = Path(__file__).parent.parent / "templates"

# Jinja2 环境
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

async def draw_char_card(ev: Event, char_name: str) -> Union[bytes, str]:
    """绘制角色卡片"""
    
    # 1. 角色别名解析
    resolved = resolve_alias_entry(char_name)
    if not resolved:
        return f"❌ 未找到角色: {char_name}，请检查名称或稍后更新数据"
    
    real_name, entry = resolved
    char_id = entry.get("id")
    
    if not char_id:
         return f"❌ 角色 {real_name} 数据不完整 (缺少ID)"

    # 2. 获取用户绑定信息
    uid = await EndBind.get_bound_uid(ev.user_id, ev.bot_id)
    if not uid:
        return f"❌ 未绑定终末地账号，请先使用「{PREFIX}绑定」"

    # 3. 读取本地数据（由刷新指令写入）
    logger.info(f"[EndUID] 正在查询角色: {real_name} (ID: {char_id})")

    save_path = PLAYER_PATH / uid / "card_detail.json"
    if not save_path.exists():
        # 自动刷新一次
        logger.info(f"[EndUID] 未找到本地数据，自动刷新中...")
        from . import refresh_card_data
        success, error_msg = await refresh_card_data(ev.user_id, ev.bot_id)
        if not success:
            return error_msg

    try:
        async with aiofiles.open(save_path, "r", encoding="utf-8") as f:
            raw = await f.read()
        data_res = json.loads(raw)
    except Exception as e:
        logger.warning(f"[EndUID] 本地卡片数据读取失败: {e}")
        return f"❌ 本地卡片数据读取失败，请先发送「{PREFIX}刷新」"
         
    if data_res.get("code") != 0:
        msg = data_res.get("message", "未知错误")
        return f"❌ 查询失败: {msg}"
        
    try:
        detail = CardDetailResponse.model_validate(data_res).data.detail
    except Exception as e:
        logger.error(f"[EndUID] 卡片详情解析失败: {e}")
        return "❌ 角色数据解析失败"

    if detail.chars:
        update_alias_map_from_chars(detail.chars)

    target = None
    for char in detail.chars:
        if char.charData and str(char.charData.id) == str(char_id):
            target = char
            break
    if not target:
        for char in detail.chars:
            if char.charData and char.charData.name == real_name:
                target = char
                break

    if not target or not target.charData:
        return "❌ 未找到该角色数据"

    # 4. 数据处理与图片下载
    c_data = target.charData
    base_info = detail.base
        
    # 提取基础信息
    name = c_data.name or real_name
    
    # 异步下载并缓存图片
    raw_url = c_data.illustrationUrl or c_data.avatarRtUrl or c_data.avatarSqUrl
    char_url_b64 = ""
    if raw_url:
        char_url_b64 = await get_image_b64_with_cache(raw_url, CHAR_CACHE_PATH)

    # 属性映射
    rarity = c_data.rarity.value if c_data.rarity else "1"
    profession = c_data.profession.value if c_data.profession else "未知"
    property_val = c_data.property.value if c_data.property else "无"
    weapon_type = c_data.weaponType.value if c_data.weaponType else "未知"
    char_tags = c_data.tags or []

    # 技能
    skills_list = []
    user_skills = target.userSkills or {}
    raw_skills = c_data.skills or []
    
    for sk in raw_skills:
        sk_id = sk.id
        sk_level_data = user_skills.get(sk_id)
        sk_level = sk_level_data.level if sk_level_data else 1
        
        icon_url = sk.iconUrl
        icon_b64 = ""
        if icon_url:
             icon_b64 = await get_image_b64_with_cache(icon_url, SKILL_CACHE_PATH)

        skills_list.append({
            "name": sk.name,
            "icon": icon_b64,
            "level": sk_level
        })
        
    # 装备 - 武器
    weapon_info = None
    wp_data = target.weapon
    if wp_data and wp_data.weaponData and wp_data.weaponData.id:
        wp_detail = wp_data.weaponData
        if wp_detail:
            wp_icon_url = wp_detail.iconUrl
            wp_icon_b64 = ""
            if wp_icon_url:
                wp_icon_b64 = await get_image_b64_with_cache(wp_icon_url, EQUIP_CACHE_PATH)
            
            weapon_info = {
                "name": wp_detail.name,
                "icon": wp_icon_b64,
                "level": wp_data.level,
                "rarity": wp_detail.rarity.value if wp_detail.rarity else 1,
            }
            
    # 装备 - 防具
    body_equip_info = None
    be_data = target.bodyEquip
    if be_data and be_data.equipData and be_data.equipData.id:
        be_detail = be_data.equipData
        if be_detail:
             be_icon_url = be_detail.iconUrl
             be_icon_b64 = ""
             if be_icon_url:
                 be_icon_b64 = await get_image_b64_with_cache(be_icon_url, EQUIP_CACHE_PATH)
                 
             body_equip_info = {
                "name": be_detail.name,
                "icon": be_icon_b64,
                "level": be_detail.level.value if be_detail.level and be_detail.level.value else 1,
             }

    equip_slots = []

    async def _append_equip(slot_key: str, slot_name: str, equip: Optional[object]):
        if not equip or not getattr(equip, "equipData", None):
            return
        detail = equip.equipData
        if not detail or not detail.name:
            return
        level_val = detail.level.value if detail.level and detail.level.value else ""
        icon_b64 = ""
        if detail.iconUrl:
            icon_b64 = await get_image_b64_with_cache(detail.iconUrl, EQUIP_CACHE_PATH)
        equip_slots.append(
            {
                "slot": slot_key,
                "slot_name": slot_name,
                "name": detail.name,
                "icon": icon_b64,
                "level": level_val,
                "type": detail.type.value if detail.type else "",
                "rarity": detail.rarity.value if detail.rarity else "",
            }
        )

    await _append_equip("body", "护甲", target.bodyEquip)
    await _append_equip("arm", "护手", target.armEquip)
    await _append_equip("acc1", "配件1", target.firstAccessory)
    await _append_equip("acc2", "配件2", target.secondAccessory)

    if target.tacticalItem and target.tacticalItem.tacticalItemData:
        t_detail = target.tacticalItem.tacticalItemData
        icon_b64 = ""
        if t_detail.iconUrl:
            icon_b64 = await get_image_b64_with_cache(t_detail.iconUrl, EQUIP_CACHE_PATH)
        equip_slots.append(
            {
                "slot": "tactical",
                "slot_name": "战术道具",
                "name": t_detail.name,
                "icon": icon_b64,
                "level": "",
                "type": t_detail.activeEffectType.value if t_detail.activeEffectType else "",
                "rarity": t_detail.rarity.value if t_detail.rarity else "",
            }
        )

    bg_url_b64 = image_to_base64(TEXTURE_PATH / "bg.png")
    user_avatar = ""
    if base_info and base_info.avatarUrl:
        user_avatar = await get_image_b64_with_cache(base_info.avatarUrl, AVATAR_CACHE_PATH)

    # 加载属性和职业图标
    property_icon = ""
    property_icon_path = TEXTURE_PATH / f"{property_val}.png"
    if property_icon_path.exists():
        property_icon = image_to_base64(property_icon_path)

    profession_icon = ""
    profession_icon_path = TEXTURE_PATH / f"{profession}.png"
    if profession_icon_path.exists():
        profession_icon = image_to_base64(profession_icon_path)

    # 5. 渲染图片
    context = {
        "bg_url": bg_url_b64,
        "char_url": char_url_b64,
        "name": name,
        "uid": uid,
        "rarity": rarity,
        "profession": profession,
        "property": property_val,
        "weapon_type": weapon_type,
        "char_tags": char_tags,
        "level": target.level,
        "evolve_phase": target.evolvePhase,
        "potential": target.potentialLevel,
        "skills": skills_list,
        "weapon": weapon_info,
        "body_equip": body_equip_info,
        "equip_slots": equip_slots,

        # 图标
        "property_icon": property_icon,
        "profession_icon": profession_icon,

        # 用户信息
        "user_name": base_info.name if base_info and base_info.name else uid,
        "user_uid": base_info.roleId if base_info and base_info.roleId else uid,
        "user_level": base_info.level if base_info and base_info.level else 0,
        "world_level": base_info.worldLevel if base_info and base_info.worldLevel else 0,
        "user_avatar": user_avatar,
    }
    
    img_bytes = await render_html(end_templates, "end_char_card.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    
    return "❌ HTML 渲染失败"
