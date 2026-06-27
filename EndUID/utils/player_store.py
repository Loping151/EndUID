import os
import time
import gzip
import json
import asyncio
from pathlib import Path
from typing import Any, Optional, Union

from gsuid_core.logger import logger

# 逐用户大文件 gzip 落盘,读兼容旧明文
_GZIP_NAMES = {
    "card_detail.json",
    "gacha_logs.json",
    "crisis_contract.json",
    "indie_hard.json",
}

PathLike = Union[str, Path]


def _is_gzip(name: str) -> bool:
    return name in _GZIP_NAMES


def resolve_player_path(path: PathLike) -> Optional[Path]:
    """实际落盘路径：.gz 优先,回退明文;都不存在返回 None。move/unlink 用它。"""
    p = Path(path)
    if _is_gzip(p.name):
        gp = p.with_name(p.name + ".gz")
        if gp.exists():
            return gp
    return p if p.exists() else None


def player_json_exists(path: PathLike) -> bool:
    return resolve_player_path(path) is not None


def remove_player_json(path: PathLike) -> bool:
    """删除明文与 .gz 两种副本,返回是否删了东西。"""
    p = Path(path)
    removed = False
    for cand in (p.with_name(p.name + ".gz"), p):
        try:
            cand.unlink()
            removed = True
        except FileNotFoundError:
            pass
    return removed


def _read_one(p: Path) -> Any:
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def _gzip_dump(path: Path, obj: Any) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    with open(path, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, filename="", mtime=0) as f:
            f.write(data)


def read_player_json_sync(path: PathLike) -> Any:
    p = resolve_player_path(path)
    if p is None:
        return None
    try:
        return _read_one(p)
    except Exception as e:
        plain = Path(path)
        if p.suffix == ".gz" and plain.exists():  # .gz 损坏回退旧明文,下次写自动重建
            try:
                return _read_one(plain)
            except Exception:
                pass
        logger.warning(f"[player_store] 读取失败 {p}: {e}")
        return None


def write_player_json_sync(path: PathLike, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    uniq = f".tmp.{os.getpid()}.{time.monotonic_ns()}"
    if _is_gzip(p.name):
        gp = p.with_name(p.name + ".gz")
        tmp = gp.with_name(gp.name + uniq)
        try:
            _gzip_dump(tmp, obj)
            tmp.replace(gp)
        finally:
            tmp.unlink(missing_ok=True)
        p.unlink(missing_ok=True)
        return
    tmp = p.with_name(p.name + uniq)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        tmp.replace(p)
    finally:
        tmp.unlink(missing_ok=True)


async def read_player_json(path: PathLike) -> Any:
    return await asyncio.to_thread(read_player_json_sync, path)


async def write_player_json(path: PathLike, obj: Any) -> None:
    await asyncio.to_thread(write_player_json_sync, path, obj)


def compress_all_sync(player_path: PathLike) -> dict:
    """把 player_path 下所有白名单明文转 gz；返回各文件名的转换数与前后字节。"""
    per_name = {n: {"count": 0, "before": 0, "after": 0} for n in _GZIP_NAMES}
    fail = 0
    for uid_dir in Path(player_path).iterdir():
        if not uid_dir.is_dir():
            continue
        for name in _GZIP_NAMES:
            plain = uid_dir / name
            if not plain.is_file():
                continue
            gp = plain.with_name(name + ".gz")
            if gp.exists():
                try:
                    _read_one(gp)  # .gz 完好,明文是残留旧副本,删掉
                except Exception:
                    pass  # .gz 损坏,落到下面用明文重建
                else:
                    plain.unlink(missing_ok=True)
                    continue
            try:
                before = plain.stat().st_size
                obj = _read_one(plain)
                write_player_json_sync(plain, obj)
                after = gp.stat().st_size
            except FileNotFoundError:
                continue  # 明文被并发任务移走,跳过
            except Exception:
                fail += 1
                continue
            per_name[name]["count"] += 1
            per_name[name]["before"] += before
            per_name[name]["after"] += after
    return {"per_name": per_name, "fail": fail}


async def compress_all(player_path: PathLike) -> dict:
    return await asyncio.to_thread(compress_all_sync, player_path)
