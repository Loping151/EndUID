"""签到状态文件管理模块

用于记录和恢复签到任务状态，支持重启后继续执行
"""
import json
from typing import Optional, Literal
from datetime import datetime

from gsuid_core.logger import logger

from ..utils.path import MAIN_PATH

STATE_FILE = MAIN_PATH / "signing_state.json"

SignType = Literal["auto", "manual"]


class SigningState:
    """签到状态管理类"""

    @staticmethod
    def is_signing() -> bool:
        """检查是否正在签到"""
        return STATE_FILE.exists()

    @staticmethod
    def get_state() -> Optional[dict]:
        if not STATE_FILE.exists():
            return None
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[EndUID][SignState] 读取状态文件失败: {e}")
            return None

    @staticmethod
    def set_state(
        sign_type: SignType,
        total: Optional[int] = None,
        completed: int = 0,
    ):
        state = {
            "type": sign_type,
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if total is not None:
            state["total"] = total
            state["completed"] = completed

        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            logger.info(
                f"[EndUID][SignState] 创建状态文件: type={sign_type}, total={total}"
            )
        except Exception as e:
            logger.error(f"[EndUID][SignState] 创建状态文件失败: {e}")

    @staticmethod
    def update_progress(completed: int):
        state = SigningState.get_state()
        if not state:
            return
        state["completed"] = completed
        state["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[EndUID][SignState] 更新进度失败: {e}")

    @staticmethod
    def clear_state():
        if STATE_FILE.exists():
            try:
                STATE_FILE.unlink()
                logger.info("[EndUID][SignState] 删除状态文件（签到已完成）")
            except Exception as e:
                logger.error(f"[EndUID][SignState] 删除状态文件失败: {e}")

    @staticmethod
    def should_resume() -> bool:
        if not STATE_FILE.exists():
            return False

        state = SigningState.get_state()
        if not state:
            return False

        try:
            start_time = datetime.strptime(
                state["start_time"], "%Y-%m-%d %H:%M:%S"
            )
            elapsed = (datetime.now() - start_time).total_seconds()

            if elapsed > 86400:
                logger.warning(
                    f"[EndUID][SignState] 状态文件已过期（{elapsed / 3600:.1f}小时），清除"
                )
                SigningState.clear_state()
                return False

            logger.info(
                f"[EndUID][SignState] 发现未完成的签到任务: "
                f"type={state['type']}, elapsed={elapsed / 60:.1f}分钟"
            )
            return True
        except Exception as e:
            logger.error(f"[EndUID][SignState] 检查状态文件时出错: {e}")
            return False


signing_state = SigningState()
