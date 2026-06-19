from pathlib import Path

from .render_utils import image_to_base64

# 跨子模块共用素材根目录
RESOURCE_PATH = Path(__file__).parent.parent / "resources"
ATTR_PATH = RESOURCE_PATH / "attr"
POTENTIAL_PATH = RESOURCE_PATH / "potential"
EVOLVE_PATH = RESOURCE_PATH / "evolve"


def attr_icon_b64(name: str) -> str:
    """属性/职业图标，找不到静默返回 ''（来源 end_wiki/constants.py ATTR_ID_MAP / PROF_ID_MAP）"""
    if not name:
        return ""
    path = ATTR_PATH / f"{name}.png"
    return image_to_base64(path) if path.exists() else ""


def potential_b64(level: int) -> str:
    """潜能/谐振图标，官方金色一套(0-5)；越界返回 ''"""
    if level is None or not (0 <= level <= 5):
        return ""
    return image_to_base64(POTENTIAL_PATH / f"potential_{level}.png")


def evolve_b64(phase: int) -> str:
    """精英化程度图标(phase 0-4)；越界返回 ''"""
    if phase is None or not (0 <= phase <= 4):
        return ""
    return image_to_base64(EVOLVE_PATH / f"phase_{phase}.png")


def res_b64(filename: str, quality: int = 0) -> str:
    return image_to_base64(RESOURCE_PATH / filename, quality=quality)
