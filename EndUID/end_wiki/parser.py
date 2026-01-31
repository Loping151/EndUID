import re

from bs4 import BeautifulSoup, Tag

from gsuid_core.logger import logger

from .models import (
    BaseSkill,
    CharListEntry,
    CharStatRow,
    CharWiki,
    GachaBanner,
    Potential,
    SkillInfo,
    Talent,
    TalentEffect,
    WeaponListEntry,
    WeaponPassive,
    WeaponStatBonus,
    WeaponWiki,
    WikiListData,
)

RARITY_CHAR_MAP = {
    "6星.png": 6,
    "5星.png": 5,
    "4星.png": 4,
    "3星.png": 3,
}

RARITY_WEAPON_MAP = {
    "橙色.png": 6,
    "金色.png": 5,
    "紫色.png": 4,
    "蓝色.png": 3,
}


def _best_img_url(img: Tag) -> str:
    """Extract best resolution image URL from an <img> tag.

    Prefers srcset 2x > 1.5x > src.
    For thumb URLs smaller than 80px, upscales to 80px.
    """
    srcset = img.get("srcset", "")
    if srcset:
        best_url = ""
        best_scale = 0.0
        for part in srcset.split(","):
            part = part.strip()
            pieces = part.rsplit(" ", 1)
            if len(pieces) == 2:
                url = pieces[0].strip()
                scale_str = pieces[1].strip().rstrip("x")
                try:
                    scale = float(scale_str)
                    if scale > best_scale:
                        best_scale = scale
                        best_url = url
                except ValueError:
                    pass
        if best_url:
            return best_url

    src = img.get("src", "")
    if "/thumb/" in src:
        m = re.search(r"/(\d+)px-", src)
        if m and int(m.group(1)) < 120:
            src = re.sub(r"/\d+px-", "/120px-", src)
    return src


def _text(tag: Tag | None) -> str:
    if tag is None:
        return ""
    return tag.get_text(strip=True)


def _split_list(text: str) -> list[str]:
    """Split comma-separated Chinese text."""
    parts = re.split(r"[,，、]", text)
    return [p.strip() for p in parts if p.strip()]


def _safe_int(text: str, default: int = 0) -> int:
    text = text.strip().replace(",", "")
    try:
        return int(text)
    except (ValueError, TypeError):
        return default


def _find_table_with_header(
    tables: list[Tag], header_text: str
) -> Tag | None:
    """Find a wikitable whose first row TH contains header_text."""
    for table in tables:
        first_row = table.find("tr")
        if first_row:
            th = first_row.find("th")
            if th and header_text in _text(th):
                return table
    return None


def _parse_basic_info(table: Tag) -> dict:
    """Parse the first wikitable with basic character info."""
    info: dict = {}
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        i = 0
        while i < len(cells):
            cell = cells[i]
            if cell.name == "th":
                key = _text(cell)
                if i + 1 < len(cells) and cells[i + 1].name == "td":
                    val = _text(cells[i + 1])
                    info[key] = val
                    i += 2
                    continue
            i += 1
    return info


def _parse_rarity_char(soup: BeautifulSoup) -> int:
    """Extract character rarity from star image alt text."""
    output = soup.find("div", class_="mw-parser-output")
    if not output:
        return 0
    for img in output.find_all("img"):
        alt = img.get("alt", "")
        if alt in RARITY_CHAR_MAP:
            return RARITY_CHAR_MAP[alt]
    return 0


def _parse_stats_and_talents(table: Tag) -> tuple[
    list[CharStatRow], list[Talent]
]:
    """Parse the combined stats + talents table."""
    stats: list[CharStatRow] = []
    talents: list[Talent] = []

    rows = table.find_all("tr")
    section = None
    current_talent: Talent | None = None

    for row in rows:
        cells = row.find_all(["th", "td"])
        if not cells:
            continue

        first_cell = cells[0]
        first_text = _text(first_cell)

        # Section headers
        if first_cell.name == "th" and len(cells) == 1:
            if "能力值" in first_text:
                section = "stats"
                continue
            elif "天赋" in first_text:
                section = "talents"
                continue

        if section == "stats":
            # Skip the header row (等级, 力量, ...)
            if first_cell.name == "th" and "等级" in first_text:
                continue
            # Skip non-level rows like 满信赖加成
            if first_cell.name == "td" and "级" in first_text:
                if len(cells) >= 8:
                    stats.append(
                        CharStatRow(
                            level=first_text,
                            strength=_safe_int(_text(cells[1])),
                            agility=_safe_int(_text(cells[2])),
                            intelligence=_safe_int(_text(cells[3])),
                            will=_safe_int(_text(cells[4])),
                            base_attack=_safe_int(_text(cells[5])),
                            base_hp=_safe_int(_text(cells[6])),
                            base_defense=_safe_int(_text(cells[7])),
                        )
                    )

        elif section == "talents":
            # Talent rows have: [talent_name (rowspan), phase, description]
            # or continuation rows: [phase, description]
            if len(cells) >= 3 and first_cell.get("rowspan"):
                # New talent
                talent_name = first_text
                # Extract name from image alt if text is from image
                img = first_cell.find("img")
                if img:
                    alt = img.get("alt", "")
                    name_from_alt = alt.replace(".png", "")
                    if name_from_alt:
                        talent_name = name_from_alt

                current_talent = Talent(name=talent_name, effects=[])
                talents.append(current_talent)

                phase = _text(cells[1])
                desc = _text(cells[2])
                if phase and desc:
                    current_talent.effects.append(
                        TalentEffect(phase=phase, description=desc)
                    )
            elif len(cells) >= 2 and current_talent is not None:
                phase = _text(cells[0])
                desc = _text(cells[1])
                if phase and ("阶效果" in phase or "阶" in phase):
                    current_talent.effects.append(
                        TalentEffect(phase=phase, description=desc)
                    )

    return stats, talents


def _parse_skills(soup: BeautifulSoup) -> list[SkillInfo]:
    """Parse skills from d-tab section."""
    skills: list[SkillInfo] = []
    output = soup.find("div", class_="mw-parser-output")
    if not output:
        return skills

    # Skills are in the first d-tab (titles are skill names)
    dtabs = output.find_all("div", class_="d-tab")
    for dtab in dtabs:
        titles_div = dtab.find("div", class_="d-tab-titles")
        if not titles_div:
            continue

        title_elems = titles_div.find_all("div", class_="d-tab-title")
        title_texts = [_text(t) for t in title_elems]

        # Check if this is a skill tab (not 档案 tab)
        if not title_texts:
            continue
        # Skip tabs that look like archive/document tabs
        if any("档案" in t for t in title_texts):
            continue

        contents = dtab.find_all("div", class_="tab-content")
        for i, content in enumerate(contents):
            name = title_texts[i] if i < len(title_texts) else f"技能{i + 1}"

            # Get description text, but filter out 文件: lines and GIF refs
            text = content.get_text("\n", strip=True)
            lines = []
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("文件:") or line.endswith(".gif"):
                    continue
                lines.append(line)

            desc = "\n".join(lines)
            if desc:
                skills.append(SkillInfo(name=name, description=desc))

        if skills:
            break

    return skills


def _parse_base_skills(table: Tag) -> list[BaseSkill]:
    """Parse base skills (后勤技能) table."""
    base_skills: list[BaseSkill] = []
    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all(["th", "td"])
        # Skip header row
        if any(c.name == "th" for c in cells):
            continue
        if len(cells) >= 2:
            name = _text(cells[0])
            desc = _text(cells[1])
            if name and desc:
                base_skills.append(BaseSkill(name=name, description=desc))
    return base_skills


def _parse_potentials(table: Tag) -> list[Potential]:
    """Parse potentials (潜能) table."""
    potentials: list[Potential] = []
    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all(["th", "td"])
        # Skip header row
        if any(c.name == "th" for c in cells):
            continue
        if len(cells) >= 3:
            rank_text = _text(cells[0])
            match = re.search(r"(\d+)", rank_text)
            rank = int(match.group(1)) if match else 0
            name = _text(cells[1])
            desc = _text(cells[2])
            if rank and name:
                potentials.append(
                    Potential(rank=rank, name=name, description=desc)
                )
    return potentials


def parse_char_wiki(html: str, char_name: str) -> CharWiki | None:
    """Parse character wiki page HTML into CharWiki model."""
    try:
        soup = BeautifulSoup(html, "lxml")
        output = soup.find("div", class_="mw-parser-output")
        if not output:
            logger.warning(f"[EndWiki] 未找到角色页面内容: {char_name}")
            return None

        tables = output.find_all("table", class_="wikitable")
        if not tables:
            logger.warning(f"[EndWiki] 未找到角色信息表格: {char_name}")
            return None

        # Basic info from first table
        basic_info = _parse_basic_info(tables[0])

        # Rarity
        rarity = _parse_rarity_char(soup)

        # Stats + talents from the table with "能力值" header
        stats: list[CharStatRow] = []
        talents: list[Talent] = []
        stats_table = _find_table_with_header(tables, "能力值")
        if stats_table:
            stats, talents = _parse_stats_and_talents(stats_table)

        # Skills
        skills = _parse_skills(soup)

        # Base skills
        base_skills: list[BaseSkill] = []
        base_skill_table = _find_table_with_header(tables, "后勤技能")
        if base_skill_table:
            base_skills = _parse_base_skills(base_skill_table)

        # Potentials
        potentials: list[Potential] = []
        potential_table = _find_table_with_header(tables, "潜能")
        if potential_table:
            potentials = _parse_potentials(potential_table)

        return CharWiki(
            name=char_name,
            rarity=rarity,
            profession=basic_info.get("职业", ""),
            attribute=basic_info.get("属性", ""),
            tags=_split_list(basic_info.get("TAG", "")),
            faction=basic_info.get("阵营", ""),
            race=basic_info.get("种族", ""),
            specialties=_split_list(basic_info.get("专长", "")),
            hobbies=_split_list(basic_info.get("爱好", "")),
            operator_preference=basic_info.get("干员偏好", ""),
            release_date=basic_info.get("实装日期", ""),
            stats=stats,
            talents=talents,
            skills=skills,
            base_skills=base_skills,
            potentials=potentials,
        )
    except Exception as e:
        logger.error(f"[EndWiki] 解析角色页面失败 {char_name}: {e}")
        return None


def _parse_weapon_tab_content(
    table: Tag,
) -> tuple[int, list[WeaponStatBonus], WeaponPassive | None]:
    """Parse a single tab-content table for weapon stats."""
    base_attack = 0
    bonuses: list[WeaponStatBonus] = []
    passive: WeaponPassive | None = None

    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue

        th_text = _text(cells[0])
        td_text = _text(cells[1])

        if "基础攻击力" in th_text:
            base_attack = _safe_int(td_text)
        elif "附术" in th_text:
            passive = WeaponPassive(name=th_text, description=td_text)
        else:
            # Stat bonus rows may have 2 or 4 cells (2 bonuses per row)
            if cells[0].name == "th" and th_text:
                bonuses.append(
                    WeaponStatBonus(name=th_text, value=td_text)
                )
            if len(cells) >= 4:
                th2 = _text(cells[2])
                td2 = _text(cells[3])
                if cells[2].name == "th" and th2 and "附术" not in th2:
                    bonuses.append(
                        WeaponStatBonus(name=th2, value=td2)
                    )

    return base_attack, bonuses, passive


# ==================== 首页解析 ====================

STAR_RARITY_MAP = {
    "6星": 6, "5星": 5, "4星": 4, "3星": 3,
}

STAR_IMG_RARITY_MAP = {
    "居中6星.png": 6, "居中5星.png": 5, "居中4星.png": 4, "居中3星.png": 3,
}


def parse_homepage(html: str) -> WikiListData | None:
    """Parse homepage HTML into WikiListData."""
    try:
        soup = BeautifulSoup(html, "lxml")
        output = soup.find("div", class_="mw-parser-output")
        if not output:
            logger.warning("[EndWiki] 首页未找到 .mw-parser-output")
            return None

        characters = _parse_homepage_characters(output)
        weapons = _parse_homepage_weapons(output)
        gacha = _parse_homepage_gacha(output)

        return WikiListData(
            characters=characters,
            weapons=weapons,
            gacha=gacha,
        )
    except Exception as e:
        logger.error(f"[EndWiki] 解析首页失败: {e}")
        return None


def _parse_homepage_characters(
    output: Tag,
) -> dict[str, list[CharListEntry]]:
    """Parse character list from homepage d-tab.shouyeGanyuan.

    Groups characters by their data-param3 attribute (attribute name).
    Each entry is a div.divsort with:
      data-param1: "6星"/"5星"/... (rarity)
      data-param2: "重装"/"突击"/... (profession)
      data-param3: "灼热"/"寒冷"/... (attribute)
    """
    char_tab = output.find(
        "div", class_=re.compile(r"d-tab.*shouyeGanyuan")
    )
    if not char_tab:
        return {}

    result: dict[str, list[CharListEntry]] = {}

    for div in char_tab.find_all("div", class_="divsort"):
        rarity_str = div.get("data-param1", "")
        profession = div.get("data-param2", "")
        attribute = div.get("data-param3", "")

        rarity = STAR_RARITY_MAP.get(rarity_str, 0)

        link = div.find("a")
        name = link.get("title", "") if link else ""
        if not name:
            continue

        avatar_url = ""
        img = div.find("img")
        if img:
            avatar_url = _best_img_url(img)

        entry = CharListEntry(
            name=name,
            rarity=rarity,
            profession=profession,
            attribute=attribute,
            avatar_url=avatar_url,
        )

        if attribute not in result:
            result[attribute] = []
        result[attribute].append(entry)

    return result


def _parse_homepage_weapons(
    output: Tag,
) -> dict[str, list[WeaponListEntry]]:
    """Parse weapon list from homepage d-tab.shouyeWuqi.

    Groups weapons by their data-param1 attribute (weapon type).
    Each entry is a div.divsort with:
      data-param1: "单手剑"/"双手剑"/... (weapon type)
    Rarity is inferred from "居中X星.png" image alt.
    """
    weapon_tab = output.find(
        "div", class_=re.compile(r"d-tab.*shouyeWuqi")
    )
    if not weapon_tab:
        return {}

    result: dict[str, list[WeaponListEntry]] = {}

    for div in weapon_tab.find_all("div", class_="divsort"):
        weapon_type = div.get("data-param1", "")

        link = div.find("a")
        name = link.get("title", "") if link else ""
        if not name:
            continue

        # Icon URL from the first non-star img
        icon_url = ""
        for img in div.find_all("img"):
            alt = img.get("alt", "")
            if alt not in STAR_IMG_RARITY_MAP:
                icon_url = _best_img_url(img)
                break

        # Rarity from "居中X星.png" image
        rarity = 0
        for img in div.find_all("img"):
            alt = img.get("alt", "")
            if alt in STAR_IMG_RARITY_MAP:
                rarity = STAR_IMG_RARITY_MAP[alt]
                break

        entry = WeaponListEntry(
            name=name,
            rarity=rarity,
            weapon_type=weapon_type,
            icon_url=icon_url,
        )

        if weapon_type not in result:
            result[weapon_type] = []
        result[weapon_type].append(entry)

    return result


def _parse_homepage_gacha(output: Tag) -> list[GachaBanner]:
    """Parse gacha/banner info from homepage."""
    banners: list[GachaBanner] = []

    # Character banners: div.characterActivity
    for div in output.find_all("div", class_="characterActivity"):
        activity_list = div.find("div", class_="activityList")
        if not activity_list:
            continue

        text = _text(activity_list)
        banner_name = ""
        events: list[str] = []

        bm = re.search(r"(特许寻访·[^\s限]+)", text)
        if bm:
            banner_name = bm.group(1)

        for m in re.finditer(r"(限时签到·[^\s作]+|作战演练·\S+)", text):
            events.append(m.group(1))

        target_name = ""
        target_icon_url = ""
        img_div = div.find("div", class_="activityImage")
        if img_div:
            a = img_div.find("a")
            if a:
                target_name = a.get("title", "")
            img = img_div.find("img")
            if img:
                target_icon_url = _best_img_url(img)

        if banner_name or target_name:
            banners.append(
                GachaBanner(
                    banner_name=banner_name,
                    banner_type="character",
                    events=events,
                    target_name=target_name,
                    target_icon_url=target_icon_url,
                )
            )

    # Weapon banners: div.weaponActivity
    for div in output.find_all("div", class_="weaponActivity"):
        activity_list = div.find("div", class_="activityList")
        if not activity_list:
            continue

        text = _text(activity_list)
        # Remove MediaWiki:EventTimer noise
        text = re.sub(r"MediaWiki:EventTimer.*", "", text)

        banner_name = ""
        bm = re.search(r"(武库申领·[^\s距]+)", text)
        if bm:
            banner_name = bm.group(1)

        target_name = ""
        target_icon_url = ""
        img_div = div.find("div", class_="activityImage")
        if img_div:
            a = img_div.find("a")
            if a:
                target_name = a.get("title", "")
            img = img_div.find("img")
            if img:
                target_icon_url = _best_img_url(img)

        if banner_name or target_name:
            banners.append(
                GachaBanner(
                    banner_name=banner_name,
                    banner_type="weapon",
                    events=[],
                    target_name=target_name,
                    target_icon_url=target_icon_url,
                )
            )

    return banners


# ==================== 武器详情解析 ====================


def parse_weapon_wiki(html: str, weapon_name: str) -> WeaponWiki | None:
    """Parse weapon wiki page HTML into WeaponWiki model."""
    try:
        soup = BeautifulSoup(html, "lxml")
        output = soup.find("div", class_="mw-parser-output")
        if not output:
            logger.warning(f"[EndWiki] 未找到武器页面内容: {weapon_name}")
            return None

        # Main info table
        main_table = output.find("table", class_="wikitable")
        if not main_table:
            logger.warning(f"[EndWiki] 未找到武器信息表格: {weapon_name}")
            return None

        basic_info = _parse_basic_info(main_table)

        # Rarity from image
        rarity = 0
        for img in main_table.find_all("img"):
            alt = img.get("alt", "")
            if alt in RARITY_WEAPON_MAP:
                rarity = RARITY_WEAPON_MAP[alt]
                break

        # Description
        description = basic_info.get("描述", "")

        # Acquisition
        acquisition = basic_info.get("获取方式", "")

        # Parse d-tab.shuxing for initial and max stats
        base_attack = 0
        base_attack_max = 0
        stat_bonuses: list[WeaponStatBonus] = []
        stat_bonuses_max: list[WeaponStatBonus] = []
        passive: WeaponPassive | None = None
        passive_max: WeaponPassive | None = None

        dtab = output.find("div", class_="d-tab")
        if dtab:
            tab_contents = dtab.find_all("div", class_="tab-content")
            for i, content in enumerate(tab_contents):
                inner_table = content.find("table", class_="wikitable")
                if not inner_table:
                    continue

                atk, bonuses, pas = _parse_weapon_tab_content(inner_table)

                if i == 0:  # Initial
                    base_attack = atk
                    stat_bonuses = bonuses
                    passive = pas
                elif i == 1:  # Max level
                    base_attack_max = atk
                    stat_bonuses_max = bonuses
                    passive_max = pas

        return WeaponWiki(
            name=weapon_name,
            weapon_type=basic_info.get("武器种类", ""),
            rarity=rarity,
            description=description,
            acquisition=acquisition,
            base_attack=base_attack,
            base_attack_max=base_attack_max,
            stat_bonuses=stat_bonuses,
            stat_bonuses_max=stat_bonuses_max,
            passive=passive,
            passive_max=passive_max,
        )
    except Exception as e:
        logger.error(f"[EndWiki] 解析武器页面失败 {weapon_name}: {e}")
        return None
