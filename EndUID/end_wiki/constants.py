"""Skland wiki tag ID → display name mappings.

These come from the catalog filterTagTree and are stable across API calls.
"""

# subTypeId=10000 (星级) value → int rarity
RARITY_ID_MAP: dict[str, int] = {
    "10001": 1, "10002": 2, "10003": 3,
    "10004": 4, "10005": 5, "10006": 6,
}

# subTypeId=10100 (属性) value → display name
ATTR_ID_MAP: dict[str, str] = {
    "10101": "灼热",
    "10102": "电磁",
    "10103": "寒冷",
    "10104": "自然",
    "10105": "物理",
}

# subTypeId=10200 (干员职业) value → display name
PROF_ID_MAP: dict[str, str] = {
    "10201": "近卫",
    "10202": "术师",
    "10203": "突击",
    "10204": "先锋",
    "10205": "重装",
    "10206": "辅助",
}

# subTypeId=10223 (武器类型) value → display name
WEAPON_TYPE_ID_MAP: dict[str, str] = {
    "10224": "手铳",
    "10225": "双手剑",
    "10226": "单手剑",
    "10227": "施术单元",
    "10228": "长柄武器",
}
