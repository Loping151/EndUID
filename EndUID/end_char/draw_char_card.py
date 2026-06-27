import io
import re
import base64
from pathlib import Path
from typing import Optional, Union

from PIL import Image
from jinja2 import Environment, FileSystemLoader

from gsuid_core.utils.image.convert import convert_img
from gsuid_core.models import Event
from gsuid_core.logger import logger

from ..utils.alias_map import resolve_alias_entry, update_alias_map_from_chars
from ..utils.util import get_hide_uid_pref, hide_uid
from ..utils.database.models import EndBind
from ..utils.api.model import CardDetailResponse
from ..utils.render_utils import (
    render_html,
    image_to_base64,
    get_image_b64_with_cache,
)
from ..end_config import PREFIX
from ..utils.tips import TIP_NOT_BOUND, TIP_NO_LOCAL_CARD
from ..utils.resources import attr_icon_b64, potential_b64, evolve_b64
from ..utils.path import (
    AVATAR_CACHE_PATH,
    CHAR_CACHE_PATH,
    SKILL_CACHE_PATH,
    EQUIP_CACHE_PATH,
    PLAYER_PATH,
)
from ..utils.player_store import read_player_json, player_json_exists

# 资源路径
TEXTURE_PATH = Path(__file__).parent / "texture2d"
TEMPLATE_PATH = Path(__file__).parent.parent / "templates"

# Jinja2 环境
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))

async def _composite_gem_icon(icon_url: str, rarity: int) -> str:
    """Download gem icon and composite it on top of gem_X.png background."""
    try:
        from ..utils.image import pic_download_from_url

        # Download the gem icon
        await pic_download_from_url(EQUIP_CACHE_PATH, icon_url)
        filename = icon_url.split("/")[-1]
        local_path = EQUIP_CACHE_PATH / filename
        webp_path = local_path.with_suffix(".webp")
        if webp_path.exists():
            local_path = webp_path
        elif not local_path.exists():
            return ""

        icon_img = Image.open(local_path).convert("RGBA")
        icon_size = icon_img.size

        # Load rarity background and resize to match icon
        bg_path = TEXTURE_PATH / f"gem_{rarity}.png"
        if not bg_path.exists():
            # Fallback: return plain icon
            return await get_image_b64_with_cache(icon_url, EQUIP_CACHE_PATH)

        bg_img = Image.open(bg_path).convert("RGBA")
        bg_img = bg_img.resize(icon_size, Image.LANCZOS)

        # Composite: bg on bottom, icon on top
        composite = bg_img.copy()
        composite.paste(icon_img, (0, 0), icon_img)

        # Convert to base64
        buf = io.BytesIO()
        composite.save(buf, "PNG")
        buf.seek(0)
        data = buf.read()
        return f"data:image/png;base64,{base64.b64encode(data).decode('utf-8')}"
    except Exception as e:
        logger.warning(f"[ENDUID·角色面板] Gem icon composite failed: {e}")
        return ""


async def draw_char_card(ev: Event, char_name: str) -> Union[bytes, str]:
    """绘制角色卡片"""
    
    # 1. 角色别名解析
    resolved = resolve_alias_entry(char_name)
    if not resolved:
        return f"❌ 未找到角色，请检查名称或尝试「{PREFIX}更新」"
    
    real_name, entry = resolved
    char_id = entry.get("id")
    
    if not char_id:
        logger.warning(f"[ENDUID·角色面板] 角色 {real_name} 的数据条目缺少 ID")
        return f"❌ {real_name} 暂无角色数据，可尝试「{PREFIX}刷新」"

    # 2. 获取用户绑定信息
    from ..utils.at_help import ruser_id
    target_user_id = ruser_id(ev)

    uid = await EndBind.get_bound_uid(target_user_id, ev.bot_id)
    if not uid:
        return TIP_NOT_BOUND
    user_pref = await get_hide_uid_pref(uid, target_user_id, ev.bot_id)

    # 3. 读取本地数据（由刷新指令写入）
    logger.info(f"[ENDUID·角色面板] 正在查询角色: {real_name} (ID: {char_id})")

    save_path = PLAYER_PATH / uid / "card_detail.json"
    if not player_json_exists(save_path):
        # 自动刷新一次
        logger.info(f"[ENDUID·角色面板] 未找到本地数据，自动刷新中...")
        from . import refresh_card_data
        success, error_msg = await refresh_card_data(
            target_user_id, ev.bot_id, do_upload=target_user_id == ev.user_id
        )
        if not success:
            return error_msg

    data_res = await read_player_json(save_path)
    if data_res is None:
        return TIP_NO_LOCAL_CARD

    if data_res.get("code") != 0:
        msg = data_res.get("message", "未知错误")
        return f"❌ 查询失败: {msg}"
        
    try:
        detail = CardDetailResponse.model_validate(data_res).data.detail
    except Exception as e:
        logger.error(f"[ENDUID·角色面板] 卡片详情解析失败: {e}")
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

    # 天赋阵列（属性 / 战斗 / 养成），按 talent 解锁集合判定是否点亮
    tinfo = target.talent

    def _talent_unlocked(node_id: str) -> bool:
        if node_id in tinfo.attrNodes:
            return True
        m = re.match(r"^(.*)_(\d+)_(\d+)$", node_id)
        if not m:
            return False
        base, branch, lvl = m.group(1), m.group(2), int(m.group(3))
        for latest in (
            tinfo.latestPassiveSkillNodes,
            tinfo.latestFactorySkillNodes,
            tinfo.latestSpaceshipSkillNodes,
        ):
            for nid in latest:
                mm = re.match(r"^(.*)_(\d+)_(\d+)$", nid)
                if mm and mm.group(1) == base and mm.group(2) == branch and int(mm.group(3)) >= lvl:
                    return True
        return False

    def _natural_key(node_id: str):
        """JSON 节点无序，按 id 末尾数字升序（skill 为 分支_等级，属性为 等级）"""
        m = re.match(r"^.*_(\d+)_(\d+)$", node_id)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        m2 = re.match(r"^.*_(\d+)$", node_id)
        if m2:
            return (int(m2.group(1)), 0)
        return (0, 0)

    async def _bake_talents(items):
        items = items or []
        # 图标相同视为同一天赋线（含 β/γ 同图不同名），按图标分组、组内按节点升序
        groups_map: dict = {}
        for t in items:
            groups_map.setdefault(t.iconUrl or t.id, []).append(t)
        groups = []
        for gitems in groups_map.values():
            gitems = sorted(gitems, key=lambda t: _natural_key(t.id))
            total = len(gitems)
            baked = []
            for pos, t in enumerate(gitems):
                ic = ""
                if t.iconUrl:
                    try:
                        ic = await get_image_b64_with_cache(t.iconUrl, SKILL_CACHE_PATH)
                    except Exception as e:
                        logger.debug(f"[ENDUID·角色面板] 天赋图标下载失败 {t.id}: {e}")
                baked.append({
                    "icon": ic,
                    "unlocked": _talent_unlocked(t.id),
                    "seg_index": pos + 1,
                    "seg_total": total,
                })
            groups.append({"items": baked, "key": _natural_key(gitems[0].id)})
        groups.sort(key=lambda g: g["key"])
        return [g["items"] for g in groups]

    talents = {
        "ability": await _bake_talents(c_data.abilityTalents),
        "combat": await _bake_talents(c_data.combatTalents),
        "cultivation": await _bake_talents(c_data.cultivationTalents),
    }

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
            
            # 基质信息
            gem_info = None
            if wp_data.gem and wp_data.gem.gemData and wp_data.gem.gemData.name:
                gem_data = wp_data.gem.gemData
                gem_icon_b64 = ""
                # Extract rarity from templateId like "item_gem_rarity_5"
                gem_rarity = 3
                if gem_data.templateId:
                    parts = gem_data.templateId.split("_")
                    if parts and parts[-1].isdigit():
                        gem_rarity = int(parts[-1])
                gem_icon_url = gem_data.icon
                if gem_icon_url:
                    gem_icon_b64 = await _composite_gem_icon(
                        gem_icon_url, gem_rarity
                    )
                # Rarity color for bottom bar
                gem_rarity_colors = {
                    2: "#4a9eff",
                    3: "#4a9eff",
                    4: "#c084fc",
                    5: "#ff9d3a",
                }
                gem_info = {
                    "name": gem_data.name,
                    "icon": gem_icon_b64,
                    "rarity": gem_rarity,
                    "rarity_color": gem_rarity_colors.get(gem_rarity, "#888"),
                }

            weapon_info = {
                "name": wp_detail.name,
                "icon": wp_icon_b64,
                "level": wp_data.level,
                "rarity": wp_detail.rarity.value if wp_detail.rarity else 1,
                "refineLevel": wp_data.refineLevel,
                "refine_icon": potential_b64(wp_data.refineLevel),
                "gem": gem_info,
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

    bg_url_b64 = image_to_base64(TEXTURE_PATH / "bg.png", quality=75)
    from ..utils.at_help import get_query_avatar_b64
    user_avatar = await get_query_avatar_b64(ev, base_info.avatarUrl if base_info else "")

    # 加载属性和职业图标
    property_icon = attr_icon_b64(property_val)
    profession_icon = attr_icon_b64(profession)

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
        "evolve_icon": evolve_b64(target.evolvePhase),
        "potential_icon": potential_b64(target.potentialLevel),
        "skills": skills_list,
        "talents": talents,
        "weapon": weapon_info,
        "body_equip": body_equip_info,
        "equip_slots": equip_slots,

        # 图标
        "property_icon": property_icon,
        "profession_icon": profession_icon,

        # 用户信息
        "user_name": base_info.name if base_info and base_info.name else hide_uid(
            uid,
            user_pref=user_pref,
        ),
        "user_uid": hide_uid(
            base_info.roleId if base_info and base_info.roleId else uid,
            user_pref=user_pref,
        ),
        "user_level": base_info.level if base_info and base_info.level else 0,
        "world_level": base_info.worldLevel if base_info and base_info.worldLevel else 0,
        "user_avatar": user_avatar,
    }
    
    img_bytes = await render_html(end_templates, "end_char_card.html", context)
    if img_bytes:
        return await convert_img(Image.open(io.BytesIO(img_bytes)))
    
    return "❌ HTML 渲染失败"
