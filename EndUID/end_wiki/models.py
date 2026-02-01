from typing import Optional

from pydantic import BaseModel


# ==================== 首页列表模型 ====================

class CharListEntry(BaseModel):
    name: str
    rarity: int          # 6/5/4/3
    profession: str      # 重装/突击/术师/先锋/近卫/辅助
    attribute: str       # 灼热/寒冷/电磁/自然/物理
    avatar_url: str = ""


class WeaponListEntry(BaseModel):
    name: str
    rarity: int          # 6/5/4/3
    weapon_type: str     # 单手剑/双手剑/长柄武器/手铳/施术单元
    icon_url: str = ""


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


class SkillInfo(BaseModel):
    name: str
    description: str


class BaseSkill(BaseModel):
    name: str
    description: str


class Potential(BaseModel):
    rank: int
    name: str
    description: str


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
    fetch_time: float = 0


class CharWikiCache(BaseModel):
    """Wrapper for cached char detail with timestamp."""
    data: CharWiki
    fetch_time: float = 0


# ==================== 武器详情模型 ====================

class WeaponStatBonus(BaseModel):
    name: str
    value: str


class WeaponPassive(BaseModel):
    name: str
    description: str


class WeaponWiki(BaseModel):
    name: str
    weapon_type: str
    rarity: int
    description: str
    base_attack: int
    base_attack_max: int
    stat_bonuses: list[WeaponStatBonus]
    stat_bonuses_max: list[WeaponStatBonus]
    passive: Optional[WeaponPassive] = None
    passive_max: Optional[WeaponPassive] = None
    fetch_time: float = 0


class WeaponWikiCache(BaseModel):
    """Wrapper for cached weapon detail with timestamp."""
    data: WeaponWiki
    fetch_time: float = 0
