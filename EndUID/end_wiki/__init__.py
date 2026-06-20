from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.segment import MessageSegment

from ..utils import CHAR_NAME_PATTERN
from ..utils.alias_map import (
    resolve_admin_gender,
    resolve_alias_entry,
    resolve_weapon_alias,
)
from .fetch import ensure_list_data, get_char_wiki, get_weapon_wiki
from .draw_wiki import (
    draw_char_wiki,
    draw_weapon_wiki,
    draw_char_list,
    draw_weapon_list,
)
from .models import CharWiki

sv_wiki = SV("End图鉴")


async def _send_char_wiki(bot: Bot, wiki: CharWiki):
    """Send rendered wiki card, then skill GIFs as a follow-up message."""
    result = await draw_char_wiki(wiki)
    await bot.send(result)

    # 每个技能合成一个节点: 文字 + GIF 同节点(合并转发)
    nodes: list = []
    for skill in wiki.skills:
        if skill.gif_url:
            label = skill.skill_type or "技能"
            nodes.append(
                MessageSegment.node([f"{label}  {skill.name}", skill.gif_url])
            )

    if nodes:
        await bot.send(nodes)


@sv_wiki.on_regex(
    rf"^(?P<name>{CHAR_NAME_PATTERN})(?P<keyword>图鉴|介绍|技能|天赋|潜能|专武)$",
    block=True,
    to_ai="""查询终末地（明日方舟：终末地）某个角色或武器的官方资料：图鉴 / 介绍 / 技能 / 天赋 / 潜能 / 专武。

当用户问「<角色>图鉴 / <角色>技能 / <角色>专武 / <角色>潜能」时调用。
不需要绑定 UID，返回 wiki 数据。

Args:
    raw_text: 形如 "<角色>图鉴" / "<角色>专武" / "<角色>技能"。
""",
)
async def wiki_handler(bot: Bot, ev: Event):
    name = (ev.regex_dict or {}).get("name", "").strip()
    keyword = (ev.regex_dict or {}).get("keyword", "图鉴")

    if not name:
        return

    logger.info(f"[ENDUID·百科] 查询: {name} {keyword}")

    admin_gender = resolve_admin_gender(name)

    # Check for weapon alias pattern: "{角色名}专武"
    if keyword == "专武":
        if admin_gender:
            char_real = "管理员"
        else:
            char_resolved = resolve_alias_entry(name)
            char_real = char_resolved[0] if char_resolved else name
        weapon_name = resolve_weapon_alias(f"{char_real}专武")
        if weapon_name:
            logger.info(
                f"[ENDUID·百科] 武器别名: {name} -> {char_real}专武"
                f" -> {weapon_name}"
            )
            weapon_wiki = await get_weapon_wiki(weapon_name)
            if weapon_wiki:
                result = await draw_weapon_wiki(weapon_wiki)
                return await bot.send(result)
        # Also try direct weapon name lookup
        weapon_wiki = await get_weapon_wiki(char_real)
        if weapon_wiki:
            result = await draw_weapon_wiki(weapon_wiki)
            return await bot.send(result)
        return await bot.send(
            f"未找到【{weapon_name or char_real}】的武器图鉴"
        )

    # Alias resolution
    if admin_gender:
        real_name = admin_gender
        logger.info(f"[ENDUID·百科] 管理员性别别名: {name} -> {real_name}")
    else:
        resolved = resolve_alias_entry(name)
        if resolved:
            real_name = resolved[0]
            logger.info(f"[ENDUID·百科] 别名解析: {name} -> {real_name}")
        else:
            real_name = name

    # Try character
    char_wiki = await get_char_wiki(real_name)
    if char_wiki:
        return await _send_char_wiki(bot, char_wiki)

    # Try weapon
    weapon_wiki = await get_weapon_wiki(real_name)
    if weapon_wiki:
        result = await draw_weapon_wiki(weapon_wiki)
        return await bot.send(result)

    # Try weapon alias
    weapon_resolved = resolve_weapon_alias(real_name)
    if weapon_resolved and weapon_resolved != real_name:
        weapon_wiki = await get_weapon_wiki(weapon_resolved)
        if weapon_wiki:
            result = await draw_weapon_wiki(weapon_wiki)
            return await bot.send(result)

    # Retry with original name
    if real_name != name:
        char_wiki = await get_char_wiki(name)
        if char_wiki:
            return await _send_char_wiki(bot, char_wiki)

        weapon_wiki = await get_weapon_wiki(name)
        if weapon_wiki:
            result = await draw_weapon_wiki(weapon_wiki)
            return await bot.send(result)

    return await bot.send("未找到相关图鉴信息")


@sv_wiki.on_fullmatch(
    "角色列表",
    block=True,
    to_ai="""列出终末地（明日方舟：终末地）当前已上线的全部角色总览图。

当用户问「终末地角色列表 / end 角色一览 / 终末地有哪些角色」时调用。

Args:
    text: 无需参数。
""",
)
async def char_list_handler(bot: Bot, ev: Event):
    logger.info("[ENDUID·百科] 查询角色列表")
    data = await ensure_list_data()
    if not data or not data.characters:
        return await bot.send("暂无角色列表数据")

    result = await draw_char_list(data)
    return await bot.send(result)


@sv_wiki.on_fullmatch(
    "武器列表",
    block=True,
    to_ai="""列出终末地（明日方舟：终末地）当前已上线的全部武器总览图。

当用户问「终末地武器列表 / end 武器一览 / 终末地有哪些武器」时调用。

Args:
    text: 无需参数。
""",
)
async def weapon_list_handler(bot: Bot, ev: Event):
    logger.info("[ENDUID·百科] 查询武器列表")
    data = await ensure_list_data()
    if not data or not data.weapons:
        return await bot.send("暂无武器列表数据")

    result = await draw_weapon_list(data)
    return await bot.send(result)


# ==================== 明信片 ====================


@sv_wiki.on_regex(
    rf"^(?P<name>{CHAR_NAME_PATTERN})(?:明信片|潜能明信片)$",
    block=True,
    to_ai="""查询终末地某角色的明信片 / 潜能明信片图像。

当用户问「<角色>明信片 / <角色>潜能明信片」时调用。

Args:
    raw_text: 形如 "<角色>明信片" / "<角色>潜能明信片"。
""",
)
async def postcard_handler(bot: Bot, ev: Event):
    name = (ev.regex_dict or {}).get("name", "").strip()
    if not name:
        return

    admin_gender = resolve_admin_gender(name)
    if admin_gender:
        real_name = admin_gender
    else:
        resolved = resolve_alias_entry(name)
        real_name = resolved[0] if resolved else name

    logger.info(f"[ENDUID·百科] 查询明信片: {real_name}")

    char_wiki = await get_char_wiki(real_name)
    if not char_wiki and real_name != name:
        char_wiki = await get_char_wiki(name)
    if not char_wiki or not char_wiki.postcards:
        return

    msgs: list = []
    for pc in char_wiki.postcards:
        label = pc.title
        if pc.description:
            label += f"：{pc.description}"
        msgs.append(label)
        msgs.append(pc.image_url)

    await bot.send(msgs)


# ==================== 蓝图搜索 ====================

sv_blueprint = SV("End蓝图")


@sv_blueprint.on_regex(
    r"^(?:搜索蓝图|查询蓝图|蓝图)\s*(?P<query>.+)$",
    block=True,
    to_ai="""按关键词搜索终末地蓝图（武器/物品蓝图）。

当用户问「搜索蓝图 <关键词> / 查询蓝图 <关键词> / 蓝图 <角色或物品>」时调用。

Args:
    raw_text: 形如 "搜索蓝图 xxx" / "蓝图 xxx"，关键词部分必填。
""",
)
async def blueprint_handler(bot: Bot, ev: Event):
    query = (ev.regex_dict or {}).get("query", "").strip()
    if not query:
        return

    # Alias resolution
    resolved = resolve_alias_entry(query)
    if resolved:
        real_query = resolved[0]
        logger.info(f"[ENDUID·百科] 蓝图别名解析: {query} -> {real_query}")
    else:
        real_query = query

    logger.info(f"[ENDUID·百科] 搜索蓝图: {real_query}")

    from .blueprint import handle_blueprint_search

    await handle_blueprint_search(bot, ev, real_query)
