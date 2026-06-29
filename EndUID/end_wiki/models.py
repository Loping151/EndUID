from typing import Optional

from pydantic import BaseModel


# ==================== 首页列表模型 ====================

class CharListEntry(BaseModel):
    name: str
    rarity: int          # 6/5/4/3
    profession: str      # 重装/突击/术师/先锋/近卫/辅助
    attribute: str       # 灼热/寒冷/电磁/自然/物理
    avatar_url: str = ""
    wiki_item_id: int = 0


class WeaponListEntry(BaseModel):
    name: str
    rarity: int          # 6/5/4/3
    weapon_type: str     # 单手剑/双手剑/长柄武器/手铳/施术单元
    icon_url: str = ""
    wiki_item_id: int = 0


class GachaBanner(BaseModel):
    banner_name: str     # "特许寻访·熔火灼痕" 或 "武库申领·熔铸申领"
    banner_type: str     # "character" 或 "weapon"
    events: list[str]    # ["限时签到·行火留烬", "作战演练·莱万汀"]
    target_name: str     # 角色名 或 武器名
    target_icon_url: str = ""
    start_timestamp: float = 0  # unix timestamp, 0=未知
    end_timestamp: float = 0    # unix timestamp, 0=未知


class WikiListData(BaseModel):
    characters: dict[str, list[CharListEntry]]   # 按属性分组
    weapons: dict[str, list[WeaponListEntry]]    # 按武器类型分组
    gacha: list[GachaBanner]
    fetch_time: float = 0  # unix timestamp


# ==================== 角色详情模型 ====================

class CharStatRow(BaseModel):
    level: str
    strength: int
    agility: int
    intelligence: int
    will: int
    base_attack: int
    base_hp: int
    base_defense: int


class TalentEffect(BaseModel):
    phase: str
    description: str


class Talent(BaseModel):
    name: str
    effects: list[TalentEffect]
    icon_url: str = ""
    category: str = ""  # 能力值提升/干员天赋/后勤技能/装备适配


class SkillStatRow(BaseModel):
    """A row in the skill stats table (e.g. '普攻第一段倍率')."""
    label: str
    values: list[str]  # RANK 1-9, 专精1-3


class SkillInfo(BaseModel):
    name: str
    description: str
    skill_type: str = ""       # 普通攻击/战技/连携技/终结技
    icon_url: str = ""         # Skill tab icon
    gif_url: str = ""          # Skill demo GIF
    stats_table: list[SkillStatRow] = []
    stats_header: list[str] = []  # Column headers (RANK 1, ..., 专精3)


class BaseSkill(BaseModel):
    name: str
    description: str


class Potential(BaseModel):
    rank: int
    name: str
    description: str
    icon_url: str = ""


class Postcard(BaseModel):
    title: str
    image_url: str
    description: str = ""


class ChronicleImage(BaseModel):
    image_url: str
    caption: str = ""


class ChronicleTab(BaseModel):
    title: str
    images: list[ChronicleImage] = []


class CharWiki(BaseModel):
    name: str
    rarity: int
    profession: str
    attribute: str
    tags: list[str]
    faction: str
    race: str
    specialties: list[str]
    hobbies: list[str]
    operator_preference: str
    release_date: str
    stats: list[CharStatRow]
    talents: list[Talent]
    skills: list[SkillInfo]
    base_skills: list[BaseSkill]
    potentials: list[Potential]
    postcards: list[Postcard] = []
    chronicles: list[ChronicleTab] = []
    birthday: str = ""
    fetch_time: float = 0
    wiki_item_id: int = 0
    illustration_url: str = ""  # From Skland wiki extraInfo



# ==================== 武器详情模型 ====================

class WeaponStatBonus(BaseModel):
    name: str       # "敏捷提升·大 1/3"
    value: str      # "敏捷+20"


class WeaponPassive(BaseModel):
    name: str       # "切骨·群狼啃噬 1/4"
    description: str


class WeaponSkillRank(BaseModel):
    """One weapon skill with RANK 1-9 values."""
    name: str                   # "敏捷提升·大" / "切骨·群狼啃噬"
    header: list[str] = []      # ["RANK 1", ..., "RANK 9"]
    values: list[str] = []      # ["敏捷+20", "敏捷+36", ...]
    recommended_gem_id: str = ""    # 基质推荐 item ID (e.g. "473")
    recommended_gem_name: str = ""  # Resolved from catalog
    recommended_gem_cover: str = "" # Resolved from catalog


class MaterialEntry(BaseModel):
    """A material item reference (entry id + count)."""
    item_id: str
    count: str = "0"
    name: str = ""       # Resolved from catalog
    cover_url: str = ""  # Resolved from catalog


class WeaponBreakthrough(BaseModel):
    """One breakthrough level, e.g. '20级突破'."""
    level: str
    materials: list[MaterialEntry] = []


class WeaponWiki(BaseModel):
    name: str
    weapon_type: str
    rarity: int
    cover_url: str = ""         # From catalog brief.cover (static icon)
    base_attack: int = 0
    base_attack_max: int = 0
    stat_bonuses: list[WeaponStatBonus] = []
    stat_bonuses_max: list[WeaponStatBonus] = []
    passive: Optional[WeaponPassive] = None
    passive_max: Optional[WeaponPassive] = None
    skill_ranks: list[WeaponSkillRank] = []  # Per-rank skill values
    breakthroughs: list[WeaponBreakthrough] = []
    fetch_time: float = 0
