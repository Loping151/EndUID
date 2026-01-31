"""EndUID API 数据模型

基于森空岛 API 响应结构定义
"""
from typing import Dict, List, Union, Literal, Optional, Any

from pydantic import Field, BaseModel



class KeyValuePair(BaseModel):
    """键值对模型（用于枚举类型）"""
    key: str = ""
    value: str = ""



class MainMission(BaseModel):
    """主线任务"""
    id: str = ""
    description: str = ""


class PlayerBase(BaseModel):
    """玩家基础信息"""
    serverName: str = ""
    roleId: str = ""
    name: str = ""
    createTime: str = ""
    saveTime: str = ""
    lastLoginTime: str = ""
    exp: int = 0
    level: int = 0
    worldLevel: int = 0
    gender: int = 0
    avatarUrl: str = ""
    mainMission: MainMission = Field(default_factory=MainMission)
    charNum: int = 0
    weaponNum: int = 0
    docNum: int = 0


class SkillDescLevelParams(BaseModel):
    """技能等级参数"""
    level: str = ""
    params: Dict[str, str] = Field(default_factory=dict)


class Skill(BaseModel):
    """技能信息"""
    id: str = ""
    name: str = ""
    type: KeyValuePair = Field(default_factory=KeyValuePair)
    property: KeyValuePair = Field(default_factory=KeyValuePair)
    iconUrl: str = ""
    desc: str = ""
    descParams: Dict[str, Any] = Field(default_factory=dict)
    descLevelParams: Dict[str, SkillDescLevelParams] = Field(default_factory=dict)


class CharData(BaseModel):
    """角色基础数据"""
    id: str = ""
    name: str = ""
    avatarSqUrl: str = ""
    avatarRtUrl: str = ""
    rarity: KeyValuePair = Field(default_factory=KeyValuePair)
    profession: KeyValuePair = Field(default_factory=KeyValuePair)
    property: KeyValuePair = Field(default_factory=KeyValuePair)
    weaponType: KeyValuePair = Field(default_factory=KeyValuePair)
    skills: List[Skill] = Field(default_factory=list)
    labelType: str = ""
    illustrationUrl: str = ""
    tags: List[str] = Field(default_factory=list)


class UserSkill(BaseModel):
    """用户技能信息"""
    level: int = 0
    unlockTs: str = ""


class EquipSuit(BaseModel):
    """套组效果"""
    id: str = ""
    name: str = ""
    skillId: str = ""
    skillDesc: str = ""
    skillDescParams: Dict[str, str] = Field(default_factory=dict)


class EquipData(BaseModel):
    """装备数据"""
    id: str = ""
    name: str = ""
    iconUrl: str = ""
    rarity: KeyValuePair = Field(default_factory=KeyValuePair)
    type: KeyValuePair = Field(default_factory=KeyValuePair)
    level: KeyValuePair = Field(default_factory=KeyValuePair)
    properties: List[str] = Field(default_factory=list)
    isAccessory: bool = False
    suit: Optional["EquipSuit"] = None
    function: str = ""
    pkg: str = ""
    mainEntry: KeyValuePair = Field(default_factory=KeyValuePair)
    mainEntryValue: str = ""
    subEntries: List[Dict[str, Any]] = Field(default_factory=list)


class BodyEquip(BaseModel):
    """身体装备"""
    equipId: str = ""
    equipData: EquipData = Field(default_factory=EquipData)


class TacticalItemData(BaseModel):
    """战术道具数据"""
    id: str = ""
    name: str = ""
    iconUrl: str = ""
    rarity: KeyValuePair = Field(default_factory=KeyValuePair)
    activeEffectType: KeyValuePair = Field(default_factory=KeyValuePair)
    activeEffect: str = ""
    passiveEffect: str = ""


class TacticalItem(BaseModel):
    """战术道具"""
    tacticalItemId: str = ""
    tacticalItemData: TacticalItemData = Field(default_factory=TacticalItemData)


class WeaponData(BaseModel):
    """武器数据"""
    id: str = ""
    name: str = ""
    iconUrl: str = ""
    rarity: KeyValuePair = Field(default_factory=KeyValuePair)
    weaponType: KeyValuePair = Field(default_factory=KeyValuePair)
    attrType: KeyValuePair = Field(default_factory=KeyValuePair)
    desc: str = ""


class Weapon(BaseModel):
    """武器信息"""
    weaponData: WeaponData = Field(default_factory=WeaponData)
    level: int = 0
    refineLevel: int = 0
    breakthroughLevel: int = 0
    gem: Optional[Any] = None


class Character(BaseModel):
    """角色完整信息"""
    charData: CharData = Field(default_factory=CharData)
    id: str = ""
    level: int = 0
    userSkills: Dict[str, UserSkill] = Field(default_factory=dict)
    bodyEquip: Optional[BodyEquip] = None
    armEquip: Optional[BodyEquip] = None
    firstAccessory: Optional[BodyEquip] = None
    secondAccessory: Optional[BodyEquip] = None
    tacticalItem: Optional[TacticalItem] = None
    evolvePhase: int = 0
    potentialLevel: int = 0
    weapon: Weapon = Field(default_factory=Weapon)
    gender: str = ""
    ownTs: str = ""


class AchieveDisplay(BaseModel):
    """成就展示"""
    type: int = 0
    achieveMedalId: str = ""


class Achieve(BaseModel):
    """成就信息"""
    achieveMedals: List[Any] = Field(default_factory=list)
    display: AchieveDisplay = Field(default_factory=AchieveDisplay)
    count: int = 0


class RoomReports(BaseModel):
    """房间报告"""
    pass


class Room(BaseModel):
    """飞船房间"""
    id: str = ""
    type: int = 0
    level: int = 0
    chars: List[Any] = Field(default_factory=list)
    reports: RoomReports = Field(default_factory=RoomReports)


class SpaceShip(BaseModel):
    """飞船信息"""
    rooms: List[Room] = Field(default_factory=list)


class Settlement(BaseModel):
    """据点"""
    id: str = ""
    level: int = 0
    remainMoney: str = "0"
    officerCharIds: str = ""
    name: str = ""


class Collection(BaseModel):
    """收藏品"""
    levelId: str = ""
    puzzleCount: int = 0
    trchestCount: int = 0
    pieceCount: int = 0
    blackboxCount: int = 0


class Domain(BaseModel):
    """据点信息"""
    domainId: str = ""
    level: int = 0
    settlements: List[Settlement] = Field(default_factory=list)
    moneyMgr: str = ""
    collections: List[Collection] = Field(default_factory=list)
    factory: Optional[Any] = None
    name: str = ""


class Dungeon(BaseModel):
    """体力"""
    curStamina: str = ""
    maxTs: str = ""
    maxStamina: str = ""


class BpSystem(BaseModel):
    """大月卡"""
    curLevel: int = 0
    maxLevel: int = 0


class DailyMission(BaseModel):
    """每日任务"""
    dailyActivation: int = 0
    maxDailyActivation: int = 0


class UserConfig(BaseModel):
    """用户配置"""
    charSwitch: bool = False
    charIds: List[str] = Field(default_factory=list)


class QuickAccess(BaseModel):
    """快速访问"""
    name: str = ""
    icon: str = ""
    link: str = ""


class CardDetail(BaseModel):
    """卡片详情数据"""
    base: PlayerBase = Field(default_factory=PlayerBase)
    chars: List[Character] = Field(default_factory=list)
    achieve: Achieve = Field(default_factory=Achieve)
    spaceShip: SpaceShip = Field(default_factory=SpaceShip)
    domain: List[Domain] = Field(default_factory=list)
    dungeon: Dungeon = Field(default_factory=Dungeon)
    bpSystem: BpSystem = Field(default_factory=BpSystem)
    dailyMission: DailyMission = Field(default_factory=DailyMission)
    config: UserConfig = Field(default_factory=UserConfig)
    currentTs: str = ""
    quickaccess: List[QuickAccess] = Field(default_factory=list)


class CardDetailData(BaseModel):
    """卡片详情数据容器"""
    detail: CardDetail = Field(default_factory=CardDetail)


class CardDetailResponse(BaseModel):
    """卡片详情 API 响应"""
    code: int = 0
    message: str = ""
    timestamp: str = ""
    data: CardDetailData = Field(default_factory=CardDetailData)



class AttendanceResource(BaseModel):
    """签到奖励资源"""
    id: str = ""
    name: str = ""
    type: str = ""
    rarity: str = ""


class AttendanceAward(BaseModel):
    """签到奖励"""
    resource: AttendanceResource = Field(default_factory=AttendanceResource)
    count: int = 0
    type: str = ""


class AttendanceData(BaseModel):
    """签到数据"""
    awards: List[AttendanceAward] = Field(default_factory=list)


class AttendanceResponse(BaseModel):
    """签到 API 响应"""
    code: int = 0
    message: str = ""
    timestamp: str = ""
    data: AttendanceData = Field(default_factory=AttendanceData)



class BindingRole(BaseModel):
    """绑定的角色"""
    roleId: str = ""
    roleName: str = ""
    nickname: str = ""


class BindingItem(BaseModel):
    """单个游戏绑定信息"""
    appCode: str = ""
    appName: str = ""
    channelName: str = ""
    bindingList: List[Dict[str, Any]] = Field(default_factory=list)


class BindingData(BaseModel):
    """绑定数据"""
    list: List[BindingItem] = Field(default_factory=list)


class BindingResponse(BaseModel):
    """绑定 API 响应"""
    code: int = 0
    message: str = ""
    data: BindingData = Field(default_factory=BindingData)



class UserScoreInfo(BaseModel):
    """用户积分信息"""
    gameId: int = 0
    level: int = 0
    iconUrl: str = ""
    checkedDays: int = 0
    score: int = 0
    gameName: str = ""
    levelUrl: str = ""


class UserInfo(BaseModel):
    """用户基础信息"""
    id: str = ""
    nickname: str = ""
    profile: str = ""
    avatarCode: int = 0
    avatar: str = ""
    backgroundCode: int = 0
    isCreator: bool = False
    status: int = 0
    operationStatus: int = 0
    identity: int = 0
    kind: int = 0
    latestIpLocation: str = ""
    moderatorStatus: int = 0
    moderatorChangeTime: int = 0
    gender: int = 0
    hgId: str = ""
    creatorIdentifiers: List[Any] = Field(default_factory=list)
    scoreInfoList: List[UserScoreInfo] = Field(default_factory=list)
    showId: str = ""


class UserRts(BaseModel):
    """用户互动统计"""
    liked: str = ""
    collect: str = ""
    comment: str = ""
    follow: str = ""
    fans: str = ""
    black: str = ""
    pub: str = ""


class UserRelation(BaseModel):
    """用户关系"""
    follow: bool = False
    fans: bool = False
    black: bool = False
    blacked: bool = False
    blocked: bool = False
    fansAtTs: int = 0


class UserModerator(BaseModel):
    """版主信息"""
    isModerator: bool = False


class UserInfoApply(BaseModel):
    """用户资料申请信息"""
    nickname: str = ""
    profile: str = ""


class UserTeenager(BaseModel):
    """未成年人限制"""
    userId: str = ""
    status: int = 0
    allow: bool = False
    popup: bool = False


class UserTeenagerMeta(BaseModel):
    """未成年人限制元数据"""
    duration: int = 0
    start: str = ""
    end: str = ""


class UserEntry(BaseModel):
    """用户入口信息"""
    title: str = ""
    subtitle: str = ""
    iconUrl: str = ""
    scheme: str = ""


class UserIm(BaseModel):
    """IM 信息"""
    imUid: str = ""
    noReminder: bool = False


class UserBackground(BaseModel):
    """用户背景"""
    id: int = 0
    url: str = ""
    resourceKind: int = 0


class UserShare(BaseModel):
    """分享信息"""
    link: str = ""


class UserInfoData(BaseModel):
    """用户信息数据容器"""
    user: UserInfo = Field(default_factory=UserInfo)
    userRts: UserRts = Field(default_factory=UserRts)
    relation: UserRelation = Field(default_factory=UserRelation)
    userSanctionList: List[Any] = Field(default_factory=list)
    moderator: UserModerator = Field(default_factory=UserModerator)
    userInfoApply: UserInfoApply = Field(default_factory=UserInfoApply)
    teenager: UserTeenager = Field(default_factory=UserTeenager)
    teenagerMeta: UserTeenagerMeta = Field(default_factory=UserTeenagerMeta)
    entries: List[UserEntry] = Field(default_factory=list)
    im: UserIm = Field(default_factory=UserIm)
    background: UserBackground = Field(default_factory=UserBackground)
    share: UserShare = Field(default_factory=UserShare)


class UserInfoResponse(BaseModel):
    """用户信息 API 响应"""
    code: int = 0
    message: str = ""
    timestamp: str = ""
    data: UserInfoData = Field(default_factory=UserInfoData)


# ===================== 抽卡记录模型 =====================


class GachaCharRecord(BaseModel):
    """角色寻访记录"""
    charId: str = ""
    charName: str = ""
    gachaTs: str = ""
    isFree: bool = False
    isNew: bool = False
    poolId: str = ""
    poolName: str = ""
    rarity: int = 0
    seqId: str = ""


class GachaWeaponRecord(BaseModel):
    """武器寻访记录"""
    poolId: str = ""
    poolName: str = ""
    weaponId: str = ""
    weaponName: str = ""
    weaponType: str = ""
    rarity: int = 0
    isNew: bool = False
    gachaTs: str = ""
    seqId: str = ""


class GachaWeaponPool(BaseModel):
    """武器寻访池"""
    poolId: str = ""
    poolName: str = ""
