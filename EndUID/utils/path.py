import sys
from pathlib import Path
from gsuid_core.data_store import get_res_path

MAIN_PATH = get_res_path() / "EndUID"
sys.path.append(str(MAIN_PATH))

# 配置文件
CONFIG_PATH = MAIN_PATH / "config.json"
MAP_PATH = MAIN_PATH / "map.json"
AVATAR_CACHE_PATH = MAIN_PATH / "cache" / "avatar"

TEMP_PATH = Path(__file__).parents[1] / "templates"


def init_dir():
    for p in [
        MAIN_PATH,
        MAIN_PATH / "cache",
        AVATAR_CACHE_PATH,
    ]:
        p.mkdir(parents=True, exist_ok=True)


init_dir()
