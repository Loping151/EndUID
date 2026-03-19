import subprocess
import unicodedata
from typing import List, Tuple, Union
from pathlib import Path

from gsuid_core.logger import logger

from ..utils.render_utils import render_html, image_to_base64

from jinja2 import Environment, FileSystemLoader

TEMPLATE_PATH = Path(__file__).parent.parent / "templates"
ICON_PATH = Path(__file__).parents[2] / "ICON.png"

end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))


def _get_git_logs() -> List[str]:
    try:
        process = subprocess.Popen(
            ["git", "log", "--pretty=format:%s", "-100"],
            cwd=str(Path(__file__).parents[2]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            logger.warning(f"Git log failed: {stderr.decode('utf-8', errors='ignore')}")
            return []
        commits = stdout.decode("utf-8", errors="ignore").split("\n")

        filtered_commits = []
        for commit in commits:
            if commit:
                emojis, _ = _extract_leading_emojis(commit)
                if emojis:
                    filtered_commits.append(commit)
                    if len(filtered_commits) >= 18:
                        break
        return filtered_commits
    except Exception as e:
        logger.warning(f"Get logs failed: {e}")
        return []


def _is_regional_indicator(ch: str) -> bool:
    return 0x1F1E6 <= ord(ch) <= 0x1F1FF


def _is_skin_tone(ch: str) -> bool:
    return 0x1F3FB <= ord(ch) <= 0x1F3FF


def _try_consume_emoji(message: str, i: int) -> Tuple[str, int]:
    """从位置 i 开始尝试消费一个完整的 emoji 序列。

    返回 (emoji_string, new_index)，如果不是 emoji 则返回 ("", i)。
    """
    n = len(message)
    ch = message[i]

    # 旗帜: 两个连续的 regional indicator
    if _is_regional_indicator(ch) and i + 1 < n and _is_regional_indicator(message[i + 1]):
        return message[i : i + 2], i + 2

    # keycap 序列: [0-9#*] + VS16? + U+20E3
    if ch in "0123456789#*":
        j = i + 1
        if j < n and message[j] == "\ufe0f":
            j += 1
        if j < n and message[j] == "\u20e3":
            j += 1
            return message[i:j], j
        # 单独的数字/符号不算 emoji
        return "", i

    # 标准 emoji (So/Sk)
    cat = unicodedata.category(ch)
    if cat not in ("So", "Sk"):
        return "", i

    j = i + 1
    # 消费 VS16
    if j < n and message[j] == "\ufe0f":
        j += 1
    # 消费肤色修饰符
    if j < n and _is_skin_tone(message[j]):
        j += 1
    # 消费 ZWJ 序列 (如 👨‍💻)
    while j < n and message[j] == "\u200d":
        if j + 1 >= n:
            break
        nxt = message[j + 1]
        nxt_cat = unicodedata.category(nxt)
        if nxt_cat not in ("So", "Sk"):
            break
        j += 2  # 跳过 ZWJ + emoji
        # ZWJ 后的组件也可能带 VS16 / 肤色
        if j < n and message[j] == "\ufe0f":
            j += 1
        if j < n and _is_skin_tone(message[j]):
            j += 1

    return message[i:j], j


def _extract_leading_emojis(message: str) -> Tuple[List[str], str]:
    """提取消息开头连续的 emoji，并返回剩余文本。

    支持复合 emoji 序列:
    - ZWJ 序列 (👨‍💻)
    - 肤色修饰 (👍🏽)
    - keycap 序列 (#️⃣, 1️⃣)
    - 旗帜 (🇨🇳)
    - VS16 变体 (🕊️)
    """
    emojis = []
    i = 0
    while i < len(message):
        # 跳过 emoji 之间可能出现的 VS16
        if message[i] == "\ufe0f":
            i += 1
            continue
        emoji_str, new_i = _try_consume_emoji(message, i)
        if not emoji_str:
            break
        emojis.append(emoji_str)
        i = new_i
    return emojis, message[i:].lstrip()


# 模块导入时缓存 git 日志
_CACHED_LOGS = _get_git_logs()


async def draw_update_log_img() -> Union[bytes, str]:
    if not _CACHED_LOGS:
        return "获取失败"

    icon_b64 = image_to_base64(ICON_PATH, quality=75)

    logs = []
    for index, raw_log in enumerate(_CACHED_LOGS):
        emojis, text = _extract_leading_emojis(raw_log)
        if not emojis:
            continue

        if ")" in text:
            text = text.split(")")[0] + ")"
        text = text.replace("`", "")

        logs.append({
            "emoji": "".join(emojis[:4]),
            "text": text,
            "index": index + 1,
        })

    context = {
        "icon_b64": icon_b64,
        "logs": logs,
    }

    img_bytes = await render_html(end_templates, "update_log.html", context)

    if img_bytes:
        return img_bytes
    return "渲染更新记录失败"
