"""终末地养成计算：官方计算器接口 + 前端同款本地计算

数据全部来自 zonai web/v1 calculate 接口（material-list / rules / user-game-data），
服务端不返回计算结果，按官方前端规则本地累加：
- 等级消耗按 [当前, 目标) 累加 charLevelRules，经验按等级段折算经验材料并向上取整
- 突破节点按 latestBreakNode 之后的节点累加（含装备限制节点）
- 技能按 targetLevel > 当前等级累加；天赋按未激活节点累加
- 金币计入 GOLD 材料；结果按 priorities 顺序显示；库存差值 = 仓库 - 消耗
"""
import json
import time
from collections import Counter
from typing import Dict, List, Optional, Tuple

from gsuid_core.logger import logger

from ..utils.api.requests import end_api
from ..utils.cache import TimedCache
from ..utils.path import CULTIVATE_CACHE_PATH

STATIC_TTL = 6 * 3600
_static_cache = TimedCache(timeout=STATIC_TTL, maxsize=4)
_rules_cache = TimedCache(timeout=STATIC_TTL, maxsize=64)

CHARS_DISK = CULTIVATE_CACHE_PATH / "search_chars.json"
MATERIALS_DISK = CULTIVATE_CACHE_PATH / "material_list.json"

MAX_SKILL_LEVEL = 12


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def skill_level_label(level: int) -> str:
    return f"RANK {level}" if level <= 9 else f"专精{level - 9}"


# ===================== 数据获取 =====================

async def _get_static(key: str, fetch, disk_path) -> Optional[dict]:
    cached = _static_cache.get(key)
    if cached:
        return cached
    res = await fetch()
    if res and res.get("code") == 0 and res.get("data"):
        data = res["data"]
        _static_cache.set(key, data)
        try:
            disk_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[ENDUID·养成] {key} 落盘失败: {e}")
        return data
    if disk_path.exists():
        try:
            logger.warning(f"[ENDUID·养成] {key} 接口不可用，使用本地缓存")
            return json.loads(disk_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


async def get_search_chars(cred: str) -> Optional[List[dict]]:
    data = await _get_static(
        "chars", lambda: end_api.get_calc_search_chars(cred), CHARS_DISK
    )
    return data.get("chars") if data else None


async def get_material_list(cred: str) -> Optional[dict]:
    return await _get_static(
        "materials", lambda: end_api.get_calc_material_list(cred), MATERIALS_DISK
    )


async def get_char_rules(cred: str, char_id: str) -> Optional[dict]:
    cached = _rules_cache.get(char_id)
    if cached:
        return cached
    res = await end_api.get_calc_rules(cred, char_id)
    if res and res.get("code") == 0 and res.get("data"):
        data = res["data"]
        char_rule = next(
            (c for c in data.get("chars", []) if c.get("id") == char_id), None
        )
        if not char_rule:
            return None
        result = {
            "char": char_rule,
            "level_rules": data.get("charLevelRules", []),
        }
        _rules_cache.set(char_id, result)
        return result
    return None


async def get_user_game_data(cred: str) -> Optional[dict]:
    res = await end_api.get_calc_user_game_data(cred)
    if res and res.get("code") == 0 and res.get("data"):
        return (res["data"] or {}).get("userGameData")
    if res and res.get("code") != 0:
        logger.info(f"[ENDUID·养成] 练度同步不可用: {res.get('message')}")
    return None


# ===================== 干员解析 =====================

def find_char(text: str, chars: List[dict], alias_id: str = "") -> Optional[dict]:
    """先按 alias_map 解析出的 id 精确匹配，再按名称精确/子串匹配"""
    if alias_id:
        for c in chars:
            if c.get("id") == alias_id:
                return c

    base = text.split(" ")[0].strip()
    for key in (text, base):
        for c in chars:
            if c.get("name") == key:
                return c

    lowered = base.lower()
    partial = [
        c for c in chars
        if lowered and (lowered in c.get("name", "").lower()
                        or c.get("name", "").lower() in lowered)
    ]
    if partial:
        return min(partial, key=lambda c: len(c.get("name", "")))
    return None


# ===================== 本地计算 =====================

def _exp_families(exp_materials: Dict[str, dict]) -> List[dict]:
    """经验材料按等级段分组，段内按单张经验值降序"""
    families: Dict[Tuple[int, int], List[dict]] = {}
    for m in exp_materials.values():
        seg = (_to_int(m.get("startLevel"), 1), _to_int(m.get("maxLevel"), 90))
        families.setdefault(seg, []).append(m)
    result = []
    for (start, end), mats in families.items():
        mats.sort(key=lambda m: -_to_int(m.get("exp")))
        result.append({"start": start, "end": end, "materials": mats})
    return result


def build_end_result(
    char: dict,
    materials: dict,
    char_rule: dict,
    level_rules: List[dict],
    user_char: Optional[dict],
    item_count: Optional[Dict[str, int]],
) -> dict:
    gold_id = next(
        (s["id"] for s in materials.get("materialSpecials", []) if s.get("type") == "GOLD"),
        "",
    )
    owned = bool(user_char and user_char.get("owned"))
    talent_state = (user_char.get("talent") or {}) if owned else {}

    # 1. 等级：金币逐级累加，经验按段汇总
    max_level = max((_to_int(r.get("level")) for r in level_rules), default=90)
    cur_level = min(max(_to_int(user_char.get("level"), 1), 1), max_level) if owned else 1
    rule_by_level = {_to_int(r.get("level")): r for r in level_rules}
    families = _exp_families(materials.get("charExpMaterials", {}))

    level_counter: Counter = Counter()
    seg_exp: Dict[int, int] = {}
    for lv in range(cur_level, max_level):
        rule = rule_by_level.get(lv)
        if not rule:
            continue
        gold = _to_int(rule.get("gold"))
        exp = _to_int(rule.get("exp"))
        if gold < 0 or exp < 0:
            continue
        level_counter[gold_id] += gold
        for fi, fam in enumerate(families):
            if fam["start"] <= lv < fam["end"]:
                seg_exp[fi] = seg_exp.get(fi, 0) + exp
                break

    # 经验折算为该段最高优先材料，向上取整
    exp_high_ids = set()
    for fi, exp in seg_exp.items():
        if exp <= 0:
            continue
        high = families[fi]["materials"][0]
        unit = _to_int(high.get("exp"), 1) or 1
        level_counter[str(high["id"])] += -(-exp // unit)
        exp_high_ids.add(str(high["id"]))

    # 2. 突破（含装备限制节点），并入等级分类
    nodes = char_rule.get("breakthroughs", [])
    done_idx = -1
    if owned:
        node_ids = [n.get("nodeId") for n in nodes]
        latest = talent_state.get("latestBreakNode") or ""
        if latest in node_ids:
            done_idx = node_ids.index(latest)
    for node in nodes[done_idx + 1:]:
        level_counter[gold_id] += _to_int(node.get("gold"))
        for m in node.get("materials", []):
            level_counter[str(m.get("resourceId"))] += _to_int(m.get("count"))

    # 3. 技能
    skill_names = {s.get("id"): s.get("name", "") for s in char.get("skills", [])}
    user_skills = (user_char.get("userSkills") or {}) if owned else {}
    skill_counter: Counter = Counter()
    skill_plans = []
    for sk in char_rule.get("skills", []):
        skill_id = sk.get("skillId", "")
        cur = max(1, _to_int((user_skills.get(skill_id) or {}).get("level"), 1))
        for lv in sk.get("levels", []):
            if _to_int(lv.get("targetLevel")) > cur:
                skill_counter[gold_id] += _to_int(lv.get("gold"))
                for m in lv.get("materials", []):
                    skill_counter[str(m.get("resourceId"))] += _to_int(m.get("count"))
        skill_plans.append({
            "name": skill_names.get(skill_id) or "技能",
            "from_label": skill_level_label(cur),
            "done": cur >= MAX_SKILL_LEVEL,
        })

    # 4. 天赋：attrNodes 为全量，latest* 链按序号展开
    activated = set(talent_state.get("attrNodes") or [])
    for key in (
        "latestPassiveSkillNodes",
        "latestFactorySkillNodes",
        "latestSpaceshipSkillNodes",
    ):
        for node in talent_state.get(key) or []:
            chain, _, idx = node.rpartition("_")
            if chain and idx.isdigit():
                for i in range(1, int(idx) + 1):
                    activated.add(f"{chain}_{i}")
            else:
                activated.add(node)

    talent_names = {}
    for key in ("abilityTalents", "combatTalents", "cultivationTalents"):
        for t in char.get(key) or []:
            if t.get("id"):
                talent_names[t["id"]] = t.get("name", "")

    talent_counter: Counter = Counter()
    talent_total = len(char_rule.get("talents", []))
    talent_remain = 0
    for talent in char_rule.get("talents", []):
        if talent.get("talentId") in activated:
            continue
        talent_remain += 1
        rule = talent.get("activateRule") or {}
        talent_counter[gold_id] += _to_int(rule.get("gold"))
        for m in rule.get("materials", []):
            talent_counter[str(m.get("resourceId"))] += _to_int(m.get("count"))

    total_counter = level_counter + skill_counter + talent_counter

    # 5. 排序（priorities）与材料信息
    order: Dict[str, int] = {}
    for group in materials.get("priorities", []):
        for mid in group.get("ids", []):
            order.setdefault(str(mid), len(order))

    def material_meta(item_id: str) -> dict:
        m = (
            materials.get("materials", {}).get(item_id)
            or materials.get("charExpMaterials", {}).get(item_id)
            or materials.get("weaponExpMaterials", {}).get(item_id)
            or {}
        )
        rarity = m.get("rarity")
        if isinstance(rarity, dict):
            rarity = rarity.get("value")
        return {
            "name": m.get("name", "") or f"材料{item_id[:6]}",
            "icon_url": m.get("icon", ""),
            "rarity": _to_int(rarity),
            "exp": _to_int(m.get("exp")),
        }

    def family_inventory_units(item_id: str) -> Optional[int]:
        """经验材料库存：低阶按经验值折入该段最高优先材料"""
        if item_count is None or item_id not in exp_high_ids:
            return None
        for fam in families:
            mats = fam["materials"]
            if mats and str(mats[0]["id"]) == item_id:
                total_exp = sum(
                    _to_int(item_count.get(str(m["id"]))) * _to_int(m.get("exp"))
                    for m in mats
                )
                unit = _to_int(mats[0].get("exp"), 1) or 1
                return total_exp // unit
        return None

    def counter_to_items(counter: Counter, with_left: bool) -> List[dict]:
        rows = []
        for item_id, count in counter.items():
            if count <= 0:
                continue
            meta = material_meta(item_id)
            row = {
                "id": item_id,
                "count": count,
                "order": order.get(item_id, 10**6),
                **meta,
            }
            if with_left and item_count is not None:
                inv = family_inventory_units(item_id)
                if inv is None:
                    inv = _to_int(item_count.get(item_id))
                row["inventory"] = inv
                row["left"] = inv - count
            rows.append(row)
        rows.sort(key=lambda r: r["order"])
        return rows

    synced = owned and item_count is not None
    sections = []
    for title, counter in (
        ("等级与突破", level_counter),
        ("技能升级", skill_counter),
        ("天赋激活", talent_counter),
    ):
        items = counter_to_items(counter, with_left=False)
        if items:
            sections.append({"title": title, "items": items})

    return {
        "star": _to_int((char.get("rarity") or {}).get("value")),
        "profession": (char.get("profession") or {}).get("value", ""),
        "property": (char.get("property") or {}).get("value", ""),
        "owned": owned,
        "synced": synced,
        "cur_level": cur_level,
        "max_level": max_level,
        "break_done": done_idx + 1,
        "break_total": len(nodes),
        "skill_plans": skill_plans,
        "talent_total": talent_total,
        "talent_remain": talent_remain,
        "summary": counter_to_items(total_counter, with_left=True),
        "sections": sections,
    }


def parse_item_count(user_game_data: Optional[dict]) -> Optional[Dict[str, int]]:
    if not user_game_data:
        return None
    return {
        str(k): _to_int(v)
        for k, v in (user_game_data.get("itemCount") or {}).items()
    }
