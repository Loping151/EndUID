import json
from datetime import datetime, timedelta
from typing import Dict

from .path import MAIN_PATH

STATUS_PATH = MAIN_PATH / "status.json"


def _load_status() -> Dict[str, Dict[str, int]]:
    if not STATUS_PATH.exists():
        return {}
    try:
        with open(STATUS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_status(data: Dict[str, Dict[str, int]]) -> None:
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _yesterday_str() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _ensure_date(data: Dict[str, Dict[str, int]], date_str: str) -> None:
    if date_str not in data:
        data[date_str] = {"success": 0, "fail": 0}


def record_success(count: int = 1) -> None:
    if count <= 0:
        return
    data = _load_status()
    today = _today_str()
    _ensure_date(data, today)
    data[today]["success"] += count
    _save_status(data)


def record_fail(count: int = 1) -> None:
    if count <= 0:
        return
    data = _load_status()
    today = _today_str()
    _ensure_date(data, today)
    data[today]["fail"] += count
    _save_status(data)


def get_today_counts() -> Dict[str, int]:
    data = _load_status()
    today = _today_str()
    _ensure_date(data, today)
    return data[today]


def get_yesterday_counts() -> Dict[str, int]:
    data = _load_status()
    yesterday = _yesterday_str()
    _ensure_date(data, yesterday)
    return data[yesterday]
