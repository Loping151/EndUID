from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger

from ..utils import CHAR_NAME_PATTERN
from ..utils.alias_map import resolve_alias_entry, resolve_weapon_alias
from .fetch import ensure_list_data, get_char_wiki, get_weapon_wiki
from .draw_wiki import (
    draw_char_wiki,
    draw_weapon_wiki,
    draw_char_list,
    draw_weapon_list,
    draw_gacha,
)

sv_wiki = SV("End图鉴")


@sv_wiki.on_regex(
    rf"^(?P<name>{CHAR_NAME_PATTERN})(?P<keyword>图鉴|介绍|技能|天赋|潜能|专武)$",
    block=True,
)
async def wiki_handler(bot: Bot, ev: Event):
    name = (ev.regex_dict or {}).get("name", "").strip()
    keyword = (ev.regex_dict or {}).get("keyword", "图鉴")

    if not name:
        return

    logger.info(f"[EndWiki] 查询: {name} {keyword}")

    # Check for weapon alias pattern: "{角色名}专武" or "{角色名}武器"
    for suffix in ("专武", "武器"):
        if name.endswith(suffix) or keyword == suffix:
            char_part = name[: -len(suffix)] if name.endswith(suffix) else name
            if not char_part:
                continue
            # Resolve char alias: "42姐" → "莱万汀"
            char_resolved = resolve_alias_entry(char_part)
            char_real = char_resolved[0] if char_resolved else char_part
            # Build weapon alias and resolve: "莱万汀专武" → "熔铸火焰"
            weapon_name = resolve_weapon_alias(f"{char_real}专武")
            if weapon_name:
                logger.info(
                    f"[EndWiki] 武器别名: {name} -> {char_real}专武"
                    f" -> {weapon_name}"
                )
                weapon_wiki = await get_weapon_wiki(weapon_name)
                if weapon_wiki:
                    result = await draw_weapon_wiki(weapon_wiki)
                    return await bot.send(result)
            break

    # Try alias resolution for the full name
    resolved = resolve_alias_entry(name)
    if resolved:
        real_name = resolved[0]
        logger.info(f"[EndWiki] 别名解析: {name} -> {real_name}")
    else:
        real_name = name

    # Try character first
    char_wiki = await get_char_wiki(real_name)
    if char_wiki:
        result = await draw_char_wiki(char_wiki)
        return await bot.send(result)

    # Try weapon (direct name or alias)
    weapon_wiki = await get_weapon_wiki(real_name)
    if weapon_wiki:
        result = await draw_weapon_wiki(weapon_wiki)
        return await bot.send(result)

    # Try weapon alias map directly
    weapon_resolved = resolve_weapon_alias(real_name)
    if weapon_resolved and weapon_resolved != real_name:
        logger.info(
            f"[EndWiki] 武器别名: {real_name} -> {weapon_resolved}"
        )
        weapon_wiki = await get_weapon_wiki(weapon_resolved)
        if weapon_wiki:
            result = await draw_weapon_wiki(weapon_wiki)
            return await bot.send(result)

    # Also try original name if alias resolved differently
    if real_name != name:
        char_wiki = await get_char_wiki(name)
        if char_wiki:
            result = await draw_char_wiki(char_wiki)
            return await bot.send(result)

        weapon_wiki = await get_weapon_wiki(name)
        if weapon_wiki:
            result = await draw_weapon_wiki(weapon_wiki)
            return await bot.send(result)

    return


@sv_wiki.on_fullmatch("角色列表", block=True)
async def char_list_handler(bot: Bot, ev: Event):
    logger.info("[EndWiki] 查询角色列表")
    data = await ensure_list_data()
    if not data or not data.characters:
        return await bot.send("暂无角色列表数据")

    result = await draw_char_list(data)
    return await bot.send(result)


@sv_wiki.on_fullmatch("武器列表", block=True)
async def weapon_list_handler(bot: Bot, ev: Event):
    logger.info("[EndWiki] 查询武器列表")
    data = await ensure_list_data()
    if not data or not data.weapons:
        return await bot.send("暂无武器列表数据")

    result = await draw_weapon_list(data)
    return await bot.send(result)


@sv_wiki.on_fullmatch("卡池", block=True)
async def gacha_handler(bot: Bot, ev: Event):
    logger.info("[EndWiki] 查询卡池信息")
    data = await ensure_list_data()
    if not data or not data.gacha:
        return await bot.send("暂无卡池信息")

    result = await draw_gacha(data)
    return await bot.send(result)
