import sys
from pathlib import Path
from gsuid_core.data_store import get_res_path

MAIN_PATH = get_res_path() / "EndUID"
sys.path.append(str(MAIN_PATH))

# 配置文件
CONFIG_PATH = MAIN_PATH / "config.json"
MAP_PATH = MAIN_PATH / "map.json"

CACHE_BASE = MAIN_PATH / "cache"
AVATAR_CACHE_PATH = CACHE_BASE / "avatar"
CHAR_CACHE_PATH = CACHE_BASE / "char"
SKILL_CACHE_PATH = CACHE_BASE / "skill"
EQUIP_CACHE_PATH = CACHE_BASE / "equip"
PILE_CACHE_PATH = CACHE_BASE / "pile"
ANN_CACHE_PATH = CACHE_BASE / "ann"
ANN_RENDER_CACHE_PATH = ANN_CACHE_PATH / "rendered"

PLAYER_PATH = MAIN_PATH / "players"

# 模板文件路径
TEMPLATE_MAP_PATH = Path(__file__).parent / "map.json"
TEMP_PATH = Path(__file__).parents[1] / "templates"


def init_dir():
    for p in [
        MAIN_PATH,
        CACHE_BASE,
        AVATAR_CACHE_PATH,
        CHAR_CACHE_PATH,
        SKILL_CACHE_PATH,
        EQUIP_CACHE_PATH,
        PILE_CACHE_PATH,
        ANN_CACHE_PATH,
        ANN_RENDER_CACHE_PATH,
        PLAYER_PATH,
    ]:
        p.mkdir(parents=True, exist_ok=True)


init_dir()
