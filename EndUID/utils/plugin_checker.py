"""插件执行流追踪

通过调用栈检查当前执行的插件
"""
import inspect
from typing import Optional


def get_current_plugin() -> Optional[str]:
    """通过检查调用栈获取当前执行的插件

    Returns:
        插件名称，如 "EndUID"
    """
    frame = inspect.currentframe()
    all_plugins = []

    while frame:
        file_path = inspect.getframeinfo(frame).filename

        # 检查是否在 /plugins/ 目录
        if "/plugins/" in file_path:
            parts = file_path.split("/plugins/")
            if len(parts) >= 2:
                plugin_name = parts[1].split("/")[0]
                all_plugins.append(plugin_name)

        frame = frame.f_back

    # 返回离 hook 调用最近的插件名
    return all_plugins[-1] if all_plugins else None


def is_from_plugin(plugin_name: str) -> bool:
    """检查是否来自指定插件

    Args:
        plugin_name: 插件名称，如 "EndUID"

    Returns:
        True 如果当前执行来自该插件
    """
    current = get_current_plugin()
    return current == plugin_name


def is_from_end_plugin() -> bool:
    """检查是否来自 EndUID 插件"""
    return is_from_plugin("EndUID")
