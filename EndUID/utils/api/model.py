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


class Talent(BaseModel):
    """天赋节点（属性/战斗/养成）"""
    id: str = ""
    name: str = ""
    iconUrl: str = ""
    desc: str = ""
    descParams: Dict[str, Any] = Field(default_factory=dict)
    lockedIconUrl: str = ""


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
    abilityTalents: List[Talent] = Field(default_factory=list)
    combatTalents: List[Talent] = Field(default_factory=list)
    cultivationTalents: List[Talent] = Field(default_factory=list)


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


class GemData(BaseModel):
    """基质数据"""
    termId: str = ""
    name: str = ""
    icon: str = ""
    templateId: str = ""


class Gem(BaseModel):
    """基质信息"""
    id: str = ""
    icon: str = ""
    gemData: Optional[GemData] = Field(default_factory=GemData)


class Weapon(BaseModel):
    """武器信息"""
    weaponData: WeaponData = Field(default_factory=WeaponData)
    level: int = 0
    refineLevel: int = 0
    breakthroughLevel: int = 0
    gem: Optional[Gem] = None


class CharTalent(BaseModel):
    """角色天赋阵列已解锁节点集合"""
    latestBreakNode: str = ""
    attrNodes: List[str] = Field(default_factory=list)
    latestPassiveSkillNodes: List[str] = Field(default_factory=list)
    latestFactorySkillNodes: List[str] = Field(default_factory=list)
    latestSpaceshipSkillNodes: List[str] = Field(default_factory=list)


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
    gender: Optional[str] = ""
    ownTs: Optional[str] = ""
    talent: CharTalent = Field(default_factory=CharTalent)


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
    moneyMax: str = "0"
    exp: str = "0"
    expToLevelUp: str = "0"
    officerCharIds: str = ""
    officerCharAvatar: str = ""
    name: str = ""
    lastTickTime: str = ""


class Collection(BaseModel):
    """收藏品"""
    levelId: str = ""
    puzzleCount: int = 0
    trchestCount: int = 0
    pieceCount: int = 0
    blackboxCount: int = 0


class MoneyMgr(BaseModel):
    """据点资金信息"""
    total: str = ""
    count: str = ""


class CountTotal(BaseModel):
    """计数/总量"""
    count: int = 0
    total: int = 0


class Level(BaseModel):
    """地图区域探索数据"""
    levelId: str = ""
    name: str = ""
    puzzleCount: CountTotal = Field(default_factory=CountTotal)
    trchestCount: CountTotal = Field(default_factory=CountTotal)
    equipTrchestCount: CountTotal = Field(default_factory=CountTotal)
    pieceCount: CountTotal = Field(default_factory=CountTotal)
    blackboxCount: CountTotal = Field(default_factory=CountTotal)


class Domain(BaseModel):
    """据点信息"""
    domainId: str = ""
    level: int = 0
    settlements: List[Settlement] = Field(default_factory=list)
    moneyMgr: Optional[Union[str, MoneyMgr]] = ""
    collections: List[Collection] = Field(default_factory=list)
    levels: List[Level] = Field(default_factory=list)
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


class IndieHardEnemy(BaseModel):
    """影拓丰碑副本敌人"""
    id: str = ""
    name: str = ""
    desc: str = ""
    level: int = 0
    imageUrl: str = ""
    ability: str = ""


class BestRecordChar(BaseModel):
    """影拓丰碑最佳通关阵容角色"""
    charId: str = ""
    level: int = 0
    potentialLevel: int = 0
    avatarUrl: str = ""
    evolvePhase: int = 0
    property: KeyValuePair = Field(default_factory=KeyValuePair)
    rarity: KeyValuePair = Field(default_factory=KeyValuePair)


class DungeonBestRecord(BaseModel):
    """副本最佳通关记录"""
    chars: List[BestRecordChar] = Field(default_factory=list)
    passTs: str = ""
    ts: str = ""


class IndieHardDungeon(BaseModel):
    """影拓丰碑单个副本"""
    id: str = ""
    name: str = ""
    isPass: bool = False
    recommendLevel: int = 0
    desc: str = ""
    feature: str = ""
    enemies: List[IndieHardEnemy] = Field(default_factory=list)
    bestRecord: Optional[DungeonBestRecord] = None


class IndieHardDungeonGroup(BaseModel):
    """影拓丰碑副本组（普通/苦难成对）"""
    normalDungeon: IndieHardDungeon = Field(default_factory=IndieHardDungeon)
    hardDungeon: IndieHardDungeon = Field(default_factory=IndieHardDungeon)


class IndieHardAchievementData(BaseModel):
    """期次勋章数据"""
    id: str = ""
    name: str = ""
    initIcon: str = ""
    reforge2Icon: str = ""
    reforge3Icon: str = ""
    platedIcon: str = ""
    cateName: str = ""
    canCertify: bool = False
    cate: str = ""
    initLevel: int = 0


class IndieHardAchieve(BaseModel):
    """期次勋章获得状态"""
    achievementData: IndieHardAchievementData = Field(default_factory=IndieHardAchievementData)
    level: int = 0
    isPlated: bool = False
    obtainTs: str = "0"


class IndieHardGroup(BaseModel):
    """影拓丰碑一期活动"""
    id: str = ""
    name: str = ""
    pic: str = ""
    dungeonGroups: List[IndieHardDungeonGroup] = Field(default_factory=list)
    activityStartTs: str = ""
    activityEndTs: str = ""
    activityName: str = ""
    isInActivity: bool = False
    achieve: Optional[IndieHardAchieve] = None


class IndieHard(BaseModel):
    """影拓丰碑（bossRush）"""
    indieHardGroups: List[IndieHardGroup] = Field(default_factory=list)


class IndieHardData(BaseModel):
    """indie-hard 接口 data 容器"""
    indieHard: IndieHard = Field(default_factory=IndieHard)


class IndieHardResponse(BaseModel):
    """indie-hard 接口响应"""
    code: int = 0
    message: str = ""
    timestamp: str = ""
    data: IndieHardData = Field(default_factory=IndieHardData)


class CrisisChar(BaseModel):
    """危机合约通关阵容角色"""
    charId: str = ""
    level: int = 0
    potentialLevel: int = 0
    avatarUrl: str = ""


class CrisisRecord(BaseModel):
    """危机合约单条记录"""
    id: str = ""
    chars: List[CrisisChar] = Field(default_factory=list)
    ts: str = ""
    passTs: str = ""
    isPass: bool = False
    indicatorCount: int = 0
    passWave: int = 0
    isBest: bool = False


class CrisisHistory(BaseModel):
    """危机合约历史记录"""
    records: List[CrisisRecord] = Field(default_factory=list)
    bestRecord: Optional[CrisisRecord] = None


class CrisisMissionCount(BaseModel):
    """危机合约任务进度"""
    count: int = 0
    total: int = 0


class CrisisStatus(BaseModel):
    """危机合约当期状态"""
    id: str = ""
    name: str = ""
    highest: int = 0
    challengeCount: int = 0
    kvImage: str = ""
    headerImage: str = ""
    weeklyMission: CrisisMissionCount = Field(default_factory=CrisisMissionCount)
    indicatorMission: CrisisMissionCount = Field(default_factory=CrisisMissionCount)
    stageMission: CrisisMissionCount = Field(default_factory=CrisisMissionCount)
    startAtTs: str = ""
    endAtTs: str = ""
    gameplayEndAtTs: str = ""
    achieve: Optional[IndieHardAchieve] = None


class CrisisIndicator(BaseModel):
    """危机合约指标"""
    id: str = ""
    icon: str = ""
    name: str = ""
    desc: str = ""
    descParams: Dict[str, Any] = Field(default_factory=dict)
    hasAward: bool = False
    type: int = 0
    depends: List[str] = Field(default_factory=list)
    openTs: str = "0"
    score: int = 0
    isUnlock: bool = False
    unlockScore: int = 0


class CrisisDungeon(BaseModel):
    """危机合约副本信息"""
    id: str = ""
    name: str = ""
    desc: str = ""
    feature: str = ""
    recommendLevel: int = 0
    enemies: List[IndieHardEnemy] = Field(default_factory=list)


class CrisisContract(BaseModel):
    """危机合约"""
    status: CrisisStatus = Field(default_factory=CrisisStatus)
    history: CrisisHistory = Field(default_factory=CrisisHistory)
    indicators: List[CrisisIndicator] = Field(default_factory=list)
    dungeon: CrisisDungeon = Field(default_factory=CrisisDungeon)


class CrisisContractData(BaseModel):
    """crisis-contract 接口 data 容器"""
    crisisContract: CrisisContract = Field(default_factory=CrisisContract)


class CrisisContractResponse(BaseModel):
    """crisis-contract 接口响应"""
    code: int = 0
    message: str = ""
    timestamp: str = ""
    data: CrisisContractData = Field(default_factory=CrisisContractData)


class CrisisWeapon(BaseModel):
    """危机合约详情-武器"""
    id: str = ""
    icon: str = ""
    level: int = 0
    refineLevel: int = 0
    weaponTerms: List[int] = Field(default_factory=list)
    rarity: KeyValuePair = Field(default_factory=KeyValuePair)


class CrisisEquip(BaseModel):
    """危机合约详情-单件装备"""
    id: str = ""
    icon: str = ""
    enhanceStatus: int = 0
    rarity: KeyValuePair = Field(default_factory=KeyValuePair)


class CrisisEquips(BaseModel):
    """危机合约详情-装备组"""
    bodyEquip: Optional[CrisisEquip] = None
    armEquip: Optional[CrisisEquip] = None
    firstAccessory: Optional[CrisisEquip] = None
    secondAccessory: Optional[CrisisEquip] = None


class CrisisDetailChar(BaseModel):
    """危机合约详情-角色"""
    charId: str = ""
    level: int = 0
    potentialLevel: int = 0
    avatarUrl: str = ""
    rarity: KeyValuePair = Field(default_factory=KeyValuePair)
    weapon: Optional[CrisisWeapon] = None
    equips: CrisisEquips = Field(default_factory=CrisisEquips)


class CrisisRecordDetail(BaseModel):
    """危机合约单条记录详情"""
    id: str = ""
    chars: List[CrisisDetailChar] = Field(default_factory=list)
    ts: str = ""
    passTs: str = ""
    isPass: bool = False
    indicatorCount: int = 0
    passWave: int = 0
    isBest: bool = False
    indicators: List[CrisisIndicator] = Field(default_factory=list)
    indicatorIds: List[str] = Field(default_factory=list)


class CrisisRecordData(BaseModel):
    """crisis-contract/record 接口 data 容器"""
    recordDetail: CrisisRecordDetail = Field(default_factory=CrisisRecordDetail)


class CrisisRecordResponse(BaseModel):
    """crisis-contract/record 接口响应"""
    code: int = 0
    message: str = ""
    timestamp: str = ""
    data: CrisisRecordData = Field(default_factory=CrisisRecordData)


class WeeklyMission(BaseModel):
    """周常任务"""
    score: int = 0
    total: int = 0


class SeekSuspicion(BaseModel):
    """悬念探寻进度"""
    count: int = 0
    total: int = 0


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
    weeklyMission: Optional[WeeklyMission] = None
    indieHard: Optional[IndieHard] = None
    seekSuspicion: Optional[SeekSuspicion] = None
    config: Optional[UserConfig] = Field(default_factory=UserConfig)
    currentTs: str = ""
    quickaccess: Optional[List[QuickAccess]] = Field(default_factory=list)


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
