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


def _parse_table_block(doc: dict, block_id: str) -> list[list[str]]:
    """Parse a table block into a 2D list of cell texts."""
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
                if child.get("kind") == "text":
                    for elem in child.get("text", {}).get(
                        "inlineElements", []
                    ):
                        if elem.get("kind") == "text":
                            cell_texts.append(elem["text"]["text"])
            row.append("".join(cell_texts))
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
            birthday=birthday,
            wiki_item_id=int(item.get("itemId", 0)),
            illustration_url=illustration_url,
        )
    except Exception as e:
        logger.error(
            f"[EndWiki] Failed to parse Skland wiki item: {e}"
        )
        return None


# ==================== Weapon wiki parsing ====================


def _parse_weapon_tab(
    intro: dict, content_id: str, document_map: dict
) -> tuple[int, list[WeaponStatBonus], WeaponPassive | None]:
    """Parse one weapon tab (level 1 or max) from intro + content doc.

    Returns (base_attack, stat_bonuses, passive).
    """

    # Base attack from intro.description doc
    base_attack = 0
    desc_id = intro.get("description", "")
    if desc_id and desc_id in document_map:
        doc = document_map[desc_id]
        for bid in doc.get("blockIds", []):
            text = _extract_text(doc, bid)
            m = re.search(r"基础攻击力\s*(\d+)", text)
            if m:
                base_attack = int(m.group(1))
                break

    # Stats and passive from content doc
    bonuses: list[WeaponStatBonus] = []
    passive: WeaponPassive | None = None

    if not content_id or content_id not in document_map:
        return base_attack, bonuses, passive

    doc = document_map[content_id]
    blocks = doc.get("blockIds", [])

    i = 0
    while i < len(blocks):
        bid = blocks[i]
        kind = _extract_text_kind(doc, bid)
        text = _extract_text(doc, bid)

        if kind == "body" and text:
            # Stat bonus name line, e.g. "敏捷提升·大 1/3"
            # Next block(s) (heading3) have the value(s)
            bonus_name = re.sub(r"\s*\d+/\d+\s*$", "", text.strip())
            if i + 1 < len(blocks):
                next_text = _extract_text(doc, blocks[i + 1])
                next_kind = _extract_text_kind(doc, blocks[i + 1])
                if next_kind == "heading3" and next_text:
                    # Count consecutive heading3 blocks
                    h3_lines = [next_text.strip()]
                    j = i + 2
                    while j < len(blocks):
                        jk = _extract_text_kind(doc, blocks[j])
                        jt = _extract_text(doc, blocks[j])
                        if jk == "heading3" and jt:
                            h3_lines.append(jt.strip())
                            j += 1
                        else:
                            break

                    if len(h3_lines) == 1:
                        # Single heading3 → stat bonus
                        bonuses.append(
                            WeaponStatBonus(
                                name=bonus_name,
                                value=h3_lines[0].rstrip("。."),
                            )
                        )
                    else:
                        # Multiple heading3 → passive skill
                        passive = WeaponPassive(
                            name=bonus_name,
                            description="\n".join(h3_lines),
                        )
                    i = j
                    continue
        i += 1

    return base_attack, bonuses, passive


def _extract_entry_id_from_table(
    doc: dict, table_block_id: str
) -> str:
    """Extract the first entry ID from a table block's cells."""
    block = doc.get("blockMap", {}).get(table_block_id, {})
    if block.get("kind") != "table":
        return ""
    tbl = block.get("table", {})
    block_map = doc.get("blockMap", {})
    for rid in tbl.get("rowIds", []):
        for cid in tbl.get("columnIds", []):
            cell = tbl.get("cellMap", {}).get(f"{rid}_{cid}", {})
            for child_id in cell.get("childIds", []):
                child = block_map.get(child_id, {})
                if child.get("kind") == "text":
                    for elem in child.get("text", {}).get(
                        "inlineElements", []
                    ):
                        if elem.get("kind") == "entry":
                            return elem["entry"].get("id", "")
    return ""


def _parse_weapon_skill_ranks(
    widget: dict, document_map: dict
) -> list[WeaponSkillRank]:
    """Parse 武器技能和基质 widget → per-skill RANK 1-9 values + gem."""
    ranks: list[WeaponSkillRank] = []
    tab_list = widget.get("tabList", [])
    tab_data_map = widget.get("tabDataMap", {})

    for tab in tab_list:
        tab_id = tab.get("tabId", "")
        skill_name = tab.get("title", "")
        td = tab_data_map.get(tab_id, {})
        content_id = td.get("content", "")

        if not content_id or content_id not in document_map:
            continue

        doc = document_map[content_id]
        header: list[str] = []
        values: list[str] = []
        gem_id = ""
        table_idx = 0

        for bid in doc.get("blockIds", []):
            block = doc.get("blockMap", {}).get(bid, {})
            if block.get("kind") != "table":
                continue
            table_idx += 1
            if table_idx == 1:
                # 武器技能数值
                rows = _parse_table_block(doc, bid)
                if rows and len(rows) >= 2:
                    header = rows[0]
                    values = rows[1]
            elif table_idx == 2:
                # 基质推荐
                gem_id = _extract_entry_id_from_table(doc, bid)
                break

        if header:
            ranks.append(
                WeaponSkillRank(
                    name=skill_name,
                    header=header,
                    values=values,
                    recommended_gem_id=gem_id,
                )
            )

    return ranks


def _parse_weapon_breakthroughs(
    widget: dict, document_map: dict
) -> list[WeaponBreakthrough]:
    """Parse 突破材料 widget → material entries per level."""
    results: list[WeaponBreakthrough] = []
    tab_list = widget.get("tabList", [])
    tab_data_map = widget.get("tabDataMap", {})

    for tab in tab_list:
        tab_id = tab.get("tabId", "")
        level_name = tab.get("title", "")
        td = tab_data_map.get(tab_id, {})
        content_id = td.get("content", "")

        if not content_id or content_id not in document_map:
            continue

        doc = document_map[content_id]
        materials: list[MaterialEntry] = []

        for bid in doc.get("blockIds", []):
            block = doc.get("blockMap", {}).get(bid, {})
            if block.get("kind") != "table":
                continue
            tbl = block.get("table", {})
            block_map = doc.get("blockMap", {})

            # Material entries are in row index 1
            if len(tbl.get("rowIds", [])) < 2:
                break
            mat_row_id = tbl["rowIds"][1]
            for col_id in tbl.get("columnIds", []):
                cell = tbl.get("cellMap", {}).get(
                    f"{mat_row_id}_{col_id}", {}
                )
                for child_id in cell.get("childIds", []):
                    child = block_map.get(child_id, {})
                    if child.get("kind") == "text":
                        for elem in child.get("text", {}).get(
                            "inlineElements", []
                        ):
                            if elem.get("kind") == "entry":
                                e = elem["entry"]
                                materials.append(
                                    MaterialEntry(
                                        item_id=e.get("id", ""),
                                        count=e.get("count", "0"),
                                    )
                                )
            break  # Only first table per tab

        if materials:
            results.append(
                WeaponBreakthrough(
                    level=level_name,
                    materials=materials,
                )
            )

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
        chapter_group = document.get("chapterGroup", [])
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

        # Cover image from brief
        cover_url = brief.get("cover", "")

        # Find 基本信息 widget (first widget with tabs)
        info_widget: dict = {}
        for group in chapter_group:
            for w in group.get("widgets", []):
                wid = w["id"]
                wdata = widget_common_map.get(wid, {})
                if wdata.get("tabList"):
                    info_widget = wdata
                    break
            if info_widget:
                break

        tab_list = info_widget.get("tabList", [])
        tab_data_map = info_widget.get("tabDataMap", {})

        # Weapon type from intro (fallback)
        if not weapon_type and tab_list:
            first_tab = tab_data_map.get(
                tab_list[0].get("tabId", ""), {}
            )
            intro = first_tab.get("intro", {})
            if intro:
                weapon_type = intro.get("type", "")

        # Tab 0 = initial stats, Tab 1 = max stats
        base_attack = 0
        base_attack_max = 0
        stat_bonuses: list[WeaponStatBonus] = []
        stat_bonuses_max: list[WeaponStatBonus] = []
        passive: WeaponPassive | None = None
        passive_max: WeaponPassive | None = None

        for i, tab in enumerate(tab_list[:2]):
            tid = tab.get("tabId", "")
            td = tab_data_map.get(tid, {})
            intro = td.get("intro", {})
            content_id = td.get("content", "")

            if not intro:
                continue

            atk, bonuses, pas = _parse_weapon_tab(
                intro, content_id, document_map
            )

            if i == 0:
                base_attack = atk
                stat_bonuses = bonuses
                passive = pas
            elif i == 1:
                base_attack_max = atk
                stat_bonuses_max = bonuses
                passive_max = pas

        # Skill rank tables from 武器技能和基质 widget
        _, skill_widget = _find_widget(
            chapter_group, widget_common_map, "技能详情"
        )
        skill_ranks = _parse_weapon_skill_ranks(
            skill_widget, document_map
        )

        # Breakthroughs from 突破材料 → 材料一览 widget
        _, bt_widget = _find_widget(
            chapter_group, widget_common_map, "材料一览"
        )
        breakthroughs = _parse_weapon_breakthroughs(
            bt_widget, document_map
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
            f"[EndWiki] Failed to parse Skland weapon wiki: {e}"
        )
        return None
