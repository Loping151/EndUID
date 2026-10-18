"""Parse Skland wiki JSON document format into CharWiki / WeaponWiki models."""
import re

from gsuid_core.logger import logger

from .constants import (
    ATTR_ID_MAP,
    PROF_ID_MAP,
    RARITY_ID_MAP,
    WEAPON_TYPE_ID_MAP,
)
from .models import (
    BaseSkill,
    CharWiki,
    ChronicleImage,
    ChronicleTab,
    MaterialEntry,
    Postcard,
    Potential,
    SkillInfo,
    SkillStatRow,
    Talent,
    TalentEffect,
    WeaponBreakthrough,
    WeaponPassive,
    WeaponSkillRank,
    WeaponStatBonus,
    WeaponWiki,
)


# ==================== Document block helpers ====================


def _extract_text(doc: dict, block_id: str) -> str:
    """Extract plain text from a text block."""
    block = doc.get("blockMap", {}).get(block_id, {})
    if block.get("kind") != "text":
        return ""
    parts: list[str] = []
    for elem in block.get("text", {}).get("inlineElements", []):
        if elem.get("kind") == "text":
            parts.append(elem["text"]["text"])
    return "".join(parts)


def _extract_doc_text(doc: dict) -> str:
    """Extract all text from a document (joining blocks with newlines)."""
    lines: list[str] = []
    for block_id in doc.get("blockIds", []):
        text = _extract_text(doc, block_id)
        if text.strip():
            lines.append(text.strip())
    return "\n".join(lines)


def _extract_text_kind(doc: dict, block_id: str) -> str:
    """Get the text kind (heading3, body, etc.) of a block."""
    block = doc.get("blockMap", {}).get(block_id, {})
    if block.get("kind") != "text":
        return ""
    return block.get("text", {}).get("kind", "")


def _parse_table_block(
    doc: dict, block_id: str, sep: str = ""
) -> list[list[str]]:
    """Parse a table block into a 2D list of cell texts (paragraphs joined by sep)."""
    block = doc.get("blockMap", {}).get(block_id, {})
    if block.get("kind") != "table":
        return []

    table = block.get("table", {})
    row_ids = table.get("rowIds", [])
    col_ids = table.get("columnIds", [])
    cell_map = table.get("cellMap", {})
    block_map = doc.get("blockMap", {})

    rows: list[list[str]] = []
    for row_id in row_ids:
        row: list[str] = []
        for col_id in col_ids:
            cell_key = f"{row_id}_{col_id}"
            cell = cell_map.get(cell_key, {})
            cell_texts: list[str] = []
            for child_id in cell.get("childIds", []):
                child = block_map.get(child_id, {})
                if child.get("kind") != "text":
                    continue
                elems = child.get("text", {}).get("inlineElements", [])
                cell_texts.append("".join(
                    e["text"]["text"] for e in elems if e.get("kind") == "text"
                ))
            row.append(sep.join(cell_texts))
        rows.append(row)
    return rows


# ==================== Skland wiki item -> CharWiki ====================


def _find_widget(
    chapter_group: list, widget_common_map: dict, title: str
) -> tuple[str, dict]:
    """Find a widget by its title in chapterGroup."""
    for group in chapter_group:
        for w in group.get("widgets", []):
            if w.get("title") == title:
                wid = w["id"]
                return wid, widget_common_map.get(wid, {})
    return "", {}


def _parse_skills(
    widget: dict, document_map: dict
) -> list[SkillInfo]:
    """Parse 战斗技能 widget into SkillInfo list."""
    skills: list[SkillInfo] = []
    tab_list = widget.get("tabList", [])
    tab_data_map = widget.get("tabDataMap", {})

    for tab in tab_list:
        tab_id = tab.get("tabId", "")
        tab_data = tab_data_map.get(tab_id, {})
        intro = tab_data.get("intro")
        if not intro:
            continue

        name = intro.get("name", "")
        skill_type = intro.get("type", "")
        gif_url = intro.get("imgUrl", "")
        icon_url = tab.get("icon", "")

        # Description from intro.description -> documentMap
        desc_doc_id = intro.get("description", "")
        description = ""
        if desc_doc_id and desc_doc_id in document_map:
            description = _extract_doc_text(document_map[desc_doc_id])

        # Stats table from content -> documentMap
        content_doc_id = tab_data.get("content", "")
        stats_header: list[str] = []
        stats_table: list[SkillStatRow] = []

        if content_doc_id and content_doc_id in document_map:
            doc = document_map[content_doc_id]
            # Find the first table block after "技能数据" heading
            found_data_heading = False
            for block_id in doc.get("blockIds", []):
                text = _extract_text(doc, block_id)
                kind = _extract_text_kind(doc, block_id)
                if kind == "heading3" and "技能数据" in text:
                    found_data_heading = True
                    continue
                if kind == "heading3" and found_data_heading:
                    break  # Next section
                if found_data_heading:
                    block = doc.get("blockMap", {}).get(block_id, {})
                    if block.get("kind") == "table":
                        rows = _parse_table_block(doc, block_id)
                        if rows:
                            stats_header = rows[0][1:]  # Skip "技能等级"
                            for row in rows[1:]:
                                if row and row[0]:
                                    stats_table.append(
                                        SkillStatRow(
                                            label=row[0],
                                            values=row[1:],
                                        )
                                    )
                        break

        skills.append(
            SkillInfo(
                name=name,
                description=description,
                skill_type=skill_type,
                icon_url=icon_url,
                gif_url=gif_url,
                stats_table=stats_table,
                stats_header=stats_header,
            )
        )

    return skills


def _parse_talents(
    widget: dict, document_map: dict
) -> tuple[list[Talent], list[BaseSkill]]:
    """Parse 天赋阵列 widget into Talent and BaseSkill lists."""
    talents: list[Talent] = []
    base_skills: list[BaseSkill] = []
    tab_list = widget.get("tabList", [])
    tab_data_map = widget.get("tabDataMap", {})

    for tab in tab_list:
        tab_id = tab.get("tabId", "")
        tab_data = tab_data_map.get(tab_id, {})
        content_doc_id = tab_data.get("content", "")
        icon_url = tab.get("icon", "")

        if not content_doc_id or content_doc_id not in document_map:
            continue

        doc = document_map[content_doc_id]

        # Extract name and category from text blocks
        name = ""
        category = ""
        for block_id in doc.get("blockIds", []):
            kind = _extract_text_kind(doc, block_id)
            text = _extract_text(doc, block_id)
            if kind == "heading3" and not name:
                name = text.strip()
            elif kind == "body" and not category:
                category = text.strip()

        if not name:
            continue

        # Check if there's a table with talent phases
        effects: list[TalentEffect] = []
        for block_id in doc.get("blockIds", []):
            block = doc.get("blockMap", {}).get(block_id, {})
            if block.get("kind") == "table":
                rows = _parse_table_block(doc, block_id)
                for row in rows[1:]:  # Skip header
                    if len(row) >= 2:
                        phase = row[0]
                        desc = row[1]
                        if phase and desc:
                            effects.append(
                                TalentEffect(
                                    phase=phase, description=desc
                                )
                            )

        if category in ("后勤技能",):
            # Extract description from effects or text
            desc = effects[0].description if effects else category
            base_skills.append(BaseSkill(name=name, description=desc))
        elif (
            category in ("能力值提升", "装备适配")
            or name in ("能力值提升", "装备适配")
        ):
            # These are stat bonuses, not displayed as talents
            pass
        else:
            talents.append(
                Talent(
                    name=name,
                    effects=effects,
                    icon_url=icon_url,
                    category=category,
                )
            )

    return talents, base_skills


def _parse_potentials(
    widget: dict, document_map: dict
) -> list[Potential]:
    """Parse 干员潜能 widget into Potential list."""
    potentials: list[Potential] = []
    tab_list = widget.get("tabList", [])
    tab_data_map = widget.get("tabDataMap", {})

    for i, tab in enumerate(tab_list):
        tab_id = tab.get("tabId", "")
        tab_data = tab_data_map.get(tab_id, {})
        content_doc_id = tab_data.get("content", "")
        icon_url = tab.get("icon", "")

        if not content_doc_id or content_doc_id not in document_map:
            continue

        doc = document_map[content_doc_id]

        name = ""
        desc = ""
        for block_id in doc.get("blockIds", []):
            kind = _extract_text_kind(doc, block_id)
            text = _extract_text(doc, block_id)
            if kind == "heading3" and not name:
                name = text.strip()
            elif kind == "body" and not desc:
                desc = text.strip()

        if name:
            potentials.append(
                Potential(
                    rank=i + 1,
                    name=name,
                    description=desc,
                    icon_url=icon_url,
                )
            )

    return potentials


def _parse_postcards(
    widget: dict, document_map: dict
) -> list[Postcard]:
    """Parse 潜能明信片 widget into Postcard list."""
    postcards: list[Postcard] = []
    tab_list = widget.get("tabList", [])
    tab_data_map = widget.get("tabDataMap", {})

    for tab in tab_list:
        tab_id = tab.get("tabId", "")
        tab_data = tab_data_map.get(tab_id, {})
        content_doc_id = tab_data.get("content", "")
        title = tab.get("title", "")

        if not content_doc_id or content_doc_id not in document_map:
            continue

        doc = document_map[content_doc_id]
        image_url = ""
        desc = ""

        for block_id in doc.get("blockIds", []):
            block = doc.get("blockMap", {}).get(block_id, {})
            if block.get("kind") == "image" and not image_url:
                image_url = block.get("image", {}).get("url", "")
            elif block.get("kind") == "text":
                text = _extract_text(doc, block_id)
                if text.strip() and not desc:
                    desc = text.strip()

        if image_url:
            postcards.append(
                Postcard(
                    title=title,
                    image_url=image_url,
                    description=desc,
                )
            )

    return postcards


def _collect_images(doc: dict, block_id: str) -> list[ChronicleImage]:
    """Collect images (with caption) from a block, recursing into tables."""
    block = doc.get("blockMap", {}).get(block_id, {})
    kind = block.get("kind")
    images: list[ChronicleImage] = []
    if kind == "image":
        img = block.get("image", {})
        url = img.get("url", "")
        if url:
            images.append(
                ChronicleImage(
                    image_url=url, caption=img.get("description", "")
                )
            )
    elif kind == "table":
        table = block.get("table", {})
        cell_map = table.get("cellMap", {})
        for row_id in table.get("rowIds", []):
            for col_id in table.get("columnIds", []):
                cell = cell_map.get(f"{row_id}_{col_id}", {})
                for child_id in cell.get("childIds", []):
                    images.extend(_collect_images(doc, child_id))
    return images


def _parse_chronicles(
    widget: dict, document_map: dict
) -> list[ChronicleTab]:
    """Parse 塔卫二记事社 widget into ChronicleTab list (auto over tabList)."""
    tabs: list[ChronicleTab] = []
    tab_data_map = widget.get("tabDataMap", {})

    for tab in widget.get("tabList", []):
        tab_id = tab.get("tabId", "")
        title = tab.get("title", "")
        content_doc_id = tab_data_map.get(tab_id, {}).get("content", "")
        if not content_doc_id or content_doc_id not in document_map:
            continue

        doc = document_map[content_doc_id]
        images: list[ChronicleImage] = []
        for block_id in doc.get("blockIds", []):
            images.extend(_collect_images(doc, block_id))

        if images:
            tabs.append(ChronicleTab(title=title, images=images))

    return tabs


def _resolve_tag_value(
    catalog: dict | None,
    tag_value: str,
    fallback_map: dict,
) -> str:
    """Resolve a tag value (e.g. 'rarity_6') to display name using
    the catalog filter tree, with a fallback static map."""
    # Fast path: check static map
    if tag_value in fallback_map:
        return str(fallback_map[tag_value])

    if not catalog:
        return tag_value

    # Search catalog filterTagTree
    for cat in catalog.get("catalog", []):
        for sub in cat.get("typeSub", []):
            for tree in sub.get("filterTagTree", []):
                for child in tree.get("children", []):
                    if child.get("value") == tag_value:
                        return child.get("name", tag_value)

    return tag_value


def parse_skland_char_wiki(
    item: dict,
    catalog: dict | None = None,
) -> CharWiki | None:
    """Parse a Skland wiki item JSON into CharWiki model."""
    try:
        name = item.get("name", "")
        brief = item.get("brief", {})
        document = item.get("document", {})
        document_map = document.get("documentMap", {})
        chapter_group = document.get("chapterGroup", [])
        widget_common_map = document.get("widgetCommonMap", {})
        extra_info = document.get("extraInfo", {})

        # Resolve rarity/attribute/profession from subTypeList
        sub_type_list = brief.get("subTypeList", [])
        rarity = 0
        attribute = ""
        profession = ""
        for st in sub_type_list:
            sid = st.get("subTypeId", "")
            val = st.get("value", "")
            if sid == "10000":  # 星级
                rarity = RARITY_ID_MAP.get(val, 0)
            elif sid == "10100":  # 属性
                attribute = ATTR_ID_MAP.get(val, val)
            elif sid == "10200":  # 职业
                profession = PROF_ID_MAP.get(val, val)

        # Basic info from tableList in 干员资料 widget
        _, info_widget = _find_widget(
            chapter_group, widget_common_map, "干员资料"
        )
        table_list = info_widget.get("tableList", [])
        info_map: dict[str, str] = {}
        for entry in table_list:
            info_map[entry.get("label", "")] = entry.get("value", "")

        faction = info_map.get("身份认证", "")
        race = info_map.get("种族", "")
        birthday = info_map.get("生日", "")
        tags_str = info_map.get("词缀", "")
        tags = [t.strip() for t in tags_str.split("；") if t.strip()] if tags_str else []
        release_date = info_map.get("上线时间", "")

        # Skills
        _, skill_widget = _find_widget(
            chapter_group, widget_common_map, "战斗技能"
        )
        skills = _parse_skills(skill_widget, document_map)

        # Talents + base skills
        _, talent_widget = _find_widget(
            chapter_group, widget_common_map, "天赋阵列"
        )
        talents, base_skills = _parse_talents(talent_widget, document_map)

        # Potentials
        _, potential_widget = _find_widget(
            chapter_group, widget_common_map, "干员潜能"
        )
        potentials = _parse_potentials(potential_widget, document_map)

        # Postcards
        _, postcard_widget = _find_widget(
            chapter_group, widget_common_map, "潜能明信片"
        )
        postcards = _parse_postcards(postcard_widget, document_map)

        # Chronicles (塔卫二记事社)
        _, chronicle_widget = _find_widget(
            chapter_group, widget_common_map, "塔卫二记事社"
        )
        chronicles = _parse_chronicles(chronicle_widget, document_map)

        # Illustration
        illustration_url = extra_info.get("illustration", "")

        return CharWiki(
            name=name,
            rarity=rarity,
            profession=profession,
            attribute=attribute,
            tags=tags,
            faction=faction,
            race=race,
            specialties=[],
            hobbies=[],
            operator_preference="",
            release_date=release_date,
            stats=[],
            talents=talents,
            skills=skills,
            base_skills=base_skills,
            potentials=potentials,
            postcards=postcards,
            chronicles=chronicles,
            birthday=birthday,
            wiki_item_id=int(item.get("itemId", 0)),
            illustration_url=illustration_url,
        )
    except Exception as e:
        logger.error(
            f"[ENDUID·百科] Failed to parse Skland wiki item: {e}"
        )
        return None


# ==================== Weapon wiki parsing ====================


def _table_entries(doc: dict, block_id: str) -> list[list[list[dict]]]:
    """Collect entry references (item links) per cell of a table block."""
    table = doc.get("blockMap", {}).get(block_id, {}).get("table", {})
    cell_map = table.get("cellMap", {})
    block_map = doc.get("blockMap", {})

    rows: list[list[list[dict]]] = []
    for row_id in table.get("rowIds", []):
        row: list[list[dict]] = []
        for col_id in table.get("columnIds", []):
            cell = cell_map.get(f"{row_id}_{col_id}", {})
            entries: list[dict] = []
            for child_id in cell.get("childIds", []):
                child = block_map.get(child_id, {})
                if child.get("kind") != "text":
                    continue
                for elem in child.get("text", {}).get("inlineElements", []):
                    if elem.get("kind") == "entry":
                        entries.append(elem["entry"])
            row.append(entries)
        rows.append(row)
    return rows


def _parse_weapon_breakthroughs(
    doc: dict, block_id: str, rows: list[list[str]]
) -> list[WeaponBreakthrough]:
    """Parse 突破总览 table: 材料消耗 row, one column per stage."""
    first_col = [row[0] for row in rows]
    level_row = rows[first_col.index("武器等级")] if "武器等级" in first_col else []
    mat_row = _table_entries(doc, block_id)[first_col.index("材料消耗")]

    results: list[WeaponBreakthrough] = []
    for col, entries in enumerate(mat_row[1:], start=1):
        materials = [
            MaterialEntry(item_id=e["id"], count=e.get("count", "0"))
            for e in entries
            if e.get("id")
        ]
        if not materials:
            continue
        # "20级（突破后）-40级" -> "20级突破"
        m = re.match(r"(\d+)级", level_row[col]) if col < len(level_row) else None
        level = f"{m.group(1)}级突破" if m else rows[0][col]
        results.append(WeaponBreakthrough(level=level, materials=materials))
    return results


def parse_skland_weapon_wiki(
    item: dict,
) -> WeaponWiki | None:
    """Parse a Skland wiki weapon item JSON into WeaponWiki model."""
    try:
        name = item.get("name", "")
        brief = item.get("brief", {})
        document = item.get("document", {})
        document_map = document.get("documentMap", {})
        widget_common_map = document.get("widgetCommonMap", {})

        # Rarity and weapon type from subTypeList
        sub_type_list = brief.get("subTypeList", [])
        rarity = 0
        weapon_type = ""
        for st in sub_type_list:
            sid = st.get("subTypeId", "")
            val = st.get("value", "")
            if sid == "10000":
                rarity = RARITY_ID_MAP.get(val, 0)
            elif sid == "10223":
                weapon_type = WEAPON_TYPE_ID_MAP.get(val, val)

        # Weapon type from 武器资料 tableList (fallback)
        if not weapon_type:
            for wdata in widget_common_map.values():
                for entry in wdata.get("tableList") or []:
                    if entry.get("label") == "类型":
                        weapon_type = entry.get("value", "")

        # Cover image from brief
        cover_url = brief.get("cover", "")

        base_attack = 0
        base_attack_max = 0
        skill_rows: list[list[str]] = []
        breakthroughs: list[WeaponBreakthrough] = []
        gem_id = ""

        for doc in document_map.values():
            for bid in doc.get("blockIds", []):
                rows = [
                    [cell.strip() for cell in row]
                    for row in _parse_table_block(doc, bid, sep="\n")
                ]
                if not rows or not rows[0]:
                    continue
                first_col = [row[0] for row in rows]

                if rows[0][0] == "技能详情" and not skill_rows:
                    skill_rows = rows
                elif "基础攻击力" in first_col and not base_attack:
                    atk_row = rows[first_col.index("基础攻击力")]
                    if atk_row[1].isdigit() and atk_row[-1].isdigit():
                        base_attack = int(atk_row[1])
                        base_attack_max = int(atk_row[-1])
                elif "材料消耗" in first_col and not breakthroughs:
                    breakthroughs = _parse_weapon_breakthroughs(
                        doc, bid, rows
                    )
                elif "推荐武器基质" in rows[0] and not gem_id:
                    col = rows[0].index("推荐武器基质")
                    entries = _table_entries(doc, bid)
                    if len(entries) > 1 and entries[1][col]:
                        gem_id = entries[1][col][0].get("id", "")

        # 技能详情: last column is the passive, the rest are stat bonuses
        skills: list[tuple[str, list[str]]] = [
            (skill_name, [row[col] for row in skill_rows[1:]])
            for col, skill_name in enumerate(skill_rows[0][1:], start=1)
            if skill_name
        ] if len(skill_rows) > 1 else []
        rank_header = [row[0].upper() for row in skill_rows[1:]]

        skill_ranks = [
            WeaponSkillRank(
                name=skill_name,
                header=rank_header,
                values=[v.replace("\n", "") for v in values],
                recommended_gem_id=gem_id,
            )
            for skill_name, values in skills
        ]
        stat_bonuses = [
            WeaponStatBonus(name=skill_name, value=values[0])
            for skill_name, values in skills[:-1]
        ]
        stat_bonuses_max = [
            WeaponStatBonus(name=skill_name, value=values[-1])
            for skill_name, values in skills[:-1]
        ]
        passive: WeaponPassive | None = None
        passive_max: WeaponPassive | None = None
        if skills:
            passive_name, passive_values = skills[-1]
            passive = WeaponPassive(
                name=passive_name, description=passive_values[0]
            )
            passive_max = WeaponPassive(
                name=passive_name, description=passive_values[-1]
            )

        return WeaponWiki(
            name=name,
            weapon_type=weapon_type,
            rarity=rarity,
            cover_url=cover_url,
            base_attack=base_attack,
            base_attack_max=base_attack_max,
            stat_bonuses=stat_bonuses,
            stat_bonuses_max=stat_bonuses_max,
            passive=passive,
            passive_max=passive_max,
            skill_ranks=skill_ranks,
            breakthroughs=breakthroughs,
        )
    except Exception as e:
        logger.error(
            f"[ENDUID·百科] Failed to parse Skland weapon wiki: {e}"
        )
        return None
