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


def _extract_leading_emojis(message: str) -> Tuple[List[str], str]:
    """提取消息开头连续的 emoji，并返回剩余文本。"""
    emojis = []
    i = 0
    while i < len(message):
        ch = message[i]
        if ch == "\ufe0f":  # VS16
            i += 1
            continue
        if unicodedata.category(ch) in ("So", "Sk"):
            emojis.append(ch)
            if i + 1 < len(message) and message[i + 1] == "\ufe0f":
                i += 2
            else:
                i += 1
        else:
            break
    return emojis, message[i:].lstrip()


# 模块导入时缓存 git 日志
_CACHED_LOGS = _get_git_logs()


async def draw_update_log_img() -> Union[bytes, str]:
    if not _CACHED_LOGS:
        return "获取失败"

    icon_b64 = image_to_base64(ICON_PATH)

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
