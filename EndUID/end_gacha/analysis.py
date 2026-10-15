"""抽卡记录分析（图片与网页共用）

- 特许：80 保底跨期继承，每期 120 必出 UP，30 抽加急十连（不计保底/累计），60 情报书，240 信物
- 重构：80 保底重构间继承，120 / 加急 30·60·90 / 240 按系列累计
- 辉光庆典：保底独立，30 抽加急，120 抽自选
- 武库：40 抽必出 6 星，80 抽必出 UP，第 10/18 次申领起每 8 次交替送武库箱 / UP
"""
from collections import Counter
from datetime import datetime
from typing import Optional

CHAR_GROUPS = {
    # 池名: (分组键, 保底链, 是否区分 UP, 加急阈值, UP 大保底)
    "特许寻访": ("special", "shared", True, (30,), 120),
    "重构寻访": ("rerun", "shared", True, (30, 60, 90), 120),
    "辉光庆典": ("joint", "per_pool", False, (30,), 0),
    "基础寻访": ("standard", "shared", False, (), 0),
    "启程寻访": ("beginner", "shared", False, (), 0),
}

CHAR_PITY = 80
WEAPON_PITY = 40
WEAPON_UP_PITY = 80
KEEPSAKE_CYCLE = 240
DOSSIER_AT = 60

WEAPON_PREFIX = "武器寻访-"
ARSENAL_QUOTA = {6: 2000, 5: 200, 4: 20}
ARSENAL_CLAIM_COST = 1980
UNKNOWN_CHAR_PREFIX = "E_CharacterGachaPoolType_"
WEAPON_GIFTS_FIRST = ((10, "box"), (18, "up"))
WEAPON_GIFT_STEP = 8


def _seq_key(r: dict):
    sid = r.get("seqId", "")
    try:
        return (1, int(sid))
    except (ValueError, TypeError):
        return (0, str(sid))


def ts_seconds(ts) -> int:
    try:
        n = int(ts)
        return n // 1000 if n > 1e12 else n
    except (ValueError, TypeError):
        pass
    try:
        return int(datetime.fromisoformat(str(ts)[:19]).timestamp())
    except Exception:
        return 0


def fmt_day(ts) -> str:
    s = ts_seconds(ts)
    return datetime.fromtimestamp(s).strftime("%Y.%m.%d") if s else ""


def _is_pull(r: dict) -> bool:
    """排除情报书 / 信物 / 武库赠礼等 kind=gift_* 记录"""
    return r.get("kind", "draw") == "draw"


def _item_name(r: dict) -> str:
    return r.get("charName") or r.get("weaponName") or "?"


def _pack(counter: Counter) -> list:
    return [{"name": k, "count": v} for k, v in counter.most_common()]


class UpJudge:
    """判断某个 6 星在某个卡池里是 UP 还是歪；百科缺该池时按记录推断。"""

    def __init__(self, meta: dict, pool_data: dict):
        self.pools: dict = meta.get("pools", {}) if meta else {}
        std_chars = set(meta.get("standard_chars", [])) if meta else set()
        for key in ("基础寻访", "启程寻访"):
            for r in pool_data.get(key, []):
                if r.get("rarity") == 6 and r.get("charName"):
                    std_chars.add(r["charName"])
        self.std_chars = std_chars

        std_weapons = set(meta.get("standard_weapons", [])) if meta else set()
        if not std_weapons:
            # 无百科数据：在 3 个以上卡池都出现过的 6 星武器视为常驻
            seen: dict[str, set] = {}
            for key, recs in pool_data.items():
                if key.startswith(WEAPON_PREFIX):
                    for r in recs:
                        if r.get("rarity") == 6:
                            seen.setdefault(_item_name(r), set()).add(key)
            std_weapons = {n for n, ks in seen.items() if len(ks) >= 3}
        self.std_weapons = std_weapons

        # 限定干员首次出现的卡池
        self.home: dict[str, str] = {}
        first_ts: dict[str, int] = {}
        for r in pool_data.get("特许寻访", []):
            pid = r.get("poolId", "")
            first_ts[pid] = min(first_ts.get(pid, 1 << 62), ts_seconds(r.get("gachaTs")))
        for r in sorted(pool_data.get("特许寻访", []), key=lambda x: first_ts.get(x.get("poolId", ""), 0)):
            if r.get("rarity") == 6:
                self.home.setdefault(_item_name(r), r.get("poolId", ""))

    def featured(self, pool_name: str) -> list:
        entry = self.pools.get(pool_name)
        return list(entry["up"]) if entry else []

    def char_is_up(self, name: str, char_id: str, pool_name: str, pool_id: str) -> bool:
        entry = self.pools.get(pool_name)
        if entry:
            return name in entry["up"]
        if name in self.std_chars:
            return False
        if pool_id.startswith("rerun_chr_"):
            return char_id.endswith("_" + pool_id[len("rerun_chr_"):])
        other_ups = {n for pn, e in self.pools.items() if pn != pool_name for n in e["up"]}
        if name in other_ups:
            return False
        return self.home.get(name, pool_id) == pool_id

    def weapon_is_up(self, name: str, pool_name: str) -> bool:
        entry = self.pools.get(pool_name)
        if entry:
            return name in entry["up"]
        return name not in self.std_weapons

    def weapon_kind(self, pool_name: str, pool_id: str, rerun: bool = False) -> str:
        entry = self.pools.get(pool_name)
        if entry and entry["kind"].startswith("weapon"):
            return entry["kind"]
        if "constant" in pool_id:
            return "weapon_constant"
        if rerun or pool_id.startswith("rerun_"):
            return "weapon_rerun"
        return "weapon"


def _new_banner(name: str, pool_id: str) -> dict:
    return {
        "name": name,
        "pool_id": pool_id,
        "paid": 0,
        "free": 0,
        "first_ts": 0,
        "last_ts": 0,
        "six": [],
        "free_records": [],
        "up_at": 0,
        "up_count": 0,
        "free_up": 0,
        "quota": 0,
        "gifts": Counter(),
    }


def _touch(b: dict, ts: int):
    if ts:
        b["first_ts"] = ts if not b["first_ts"] else min(b["first_ts"], ts)
        b["last_ts"] = max(b["last_ts"], ts)


def _free_batches(records: list) -> list:
    """records: [(记录, 是否 UP)]，每 10 条一组"""
    batches = []
    for i in range(0, len(records), 10):
        chunk = records[i:i + 10]
        batches.append({
            "items": [{"name": _item_name(r), "rarity": r.get("rarity", 0), "up": up} for r, up in chunk],
            "day": fmt_day(chunk[0][0].get("gachaTs")),
        })
    return batches


def _char_group(key: str, records: list, judge: UpJudge) -> dict:
    kind, chain_mode, has_up, rush, up_guarantee = CHAR_GROUPS.get(
        key, ("other", "shared", False, (), 0)
    )
    recs = sorted(records, key=_seq_key)
    banners: dict[str, dict] = {}
    chain = 0
    chain_banners: Counter = Counter()
    period5: Counter = Counter()
    period4: Counter = Counter()
    per_pool_chain: dict[str, int] = {}
    quota = 0

    for r in recs:
        pid = r.get("poolId") or key
        b = banners.get(pid)
        if b is None:
            b = banners[pid] = _new_banner(r.get("poolName") or key, pid)
        ts = ts_seconds(r.get("gachaTs"))
        _touch(b, ts)
        if not _is_pull(r):
            b["gifts"][r.get("kind", "")] += 1
            continue
        rarity = r.get("rarity", 0)
        name = _item_name(r)
        quota += ARSENAL_QUOTA.get(rarity, 0)
        b["quota"] += ARSENAL_QUOTA.get(rarity, 0)

        if r.get("isFree"):
            b["free"] += 1
            is_up = rarity == 6 and has_up and judge.char_is_up(name, r.get("charId", ""), b["name"], pid)
            b["free_records"].append((r, is_up))
            if rarity == 6:
                b["six"].append({
                    "name": name, "pity": None, "free": True, "is_up": is_up,
                    "tag": "free", "ts": ts, "carry": 0,
                    "five_items": [], "four_items": [],
                })
                if is_up:
                    b["free_up"] += 1
            continue

        b["paid"] += 1
        if chain_mode == "per_pool":
            per_pool_chain[pid] = per_pool_chain.get(pid, 0) + 1
        else:
            chain += 1
            chain_banners[pid] += 1
        if rarity == 5:
            period5[name] += 1
        elif rarity == 4:
            period4[name] += 1
        if rarity != 6:
            continue

        is_up = has_up and judge.char_is_up(name, r.get("charId", ""), b["name"], pid)
        if chain_mode == "per_pool":
            pity, carry = per_pool_chain[pid], 0
            per_pool_chain[pid] = 0
        else:
            pity, carry = chain, chain - chain_banners[pid]
            chain = 0
            chain_banners = Counter()
        tag = ("up" if is_up else "wai") if has_up else "std"
        b["six"].append({
            "name": name, "pity": pity, "free": False, "is_up": is_up, "tag": tag,
            "ts": ts, "carry": carry,
            "five_items": _pack(period5), "four_items": _pack(period4),
        })
        period5, period4 = Counter(), Counter()
        if is_up:
            b["up_count"] += 1
            if not b["up_at"]:
                b["up_at"] = b["paid"]

    out_banners = []
    for b in banners.values():
        featured = judge.featured(b["name"]) if has_up or kind == "joint" else []
        if has_up and not featured:
            got = [s["name"] for s in b["six"] if s["is_up"]]
            featured = got[:1]
        paid = b["paid"]
        milestones = []
        if rush:
            got_rush = sum(1 for t in rush if paid >= t)
            nxt = next((t for t in rush if paid < t), 0)
            milestones.append({
                "key": "rush", "label": "加急招募", "done": got_rush,
                "next": nxt, "left": nxt - paid if nxt else 0,
            })
        if kind == "special":
            milestones.append({
                "key": "dossier", "label": "情报书",
                "done": max(int(paid >= DOSSIER_AT), b["gifts"]["gift_intel_book"]),
                "next": DOSSIER_AT if paid < DOSSIER_AT else 0,
                "left": max(0, DOSSIER_AT - paid),
            })
        if kind == "joint":
            milestones.append({
                "key": "pick", "label": "自选凭证", "done": int(paid >= 120),
                "next": 120 if paid < 120 else 0, "left": max(0, 120 - paid),
            })
        if kind in ("special", "rerun"):
            milestones.append({
                "key": "keepsake", "label": "信物",
                "done": max(paid // KEEPSAKE_CYCLE, b["gifts"]["gift_operator_token"]),
                "next": (paid // KEEPSAKE_CYCLE + 1) * KEEPSAKE_CYCLE,
                "left": KEEPSAKE_CYCLE - paid % KEEPSAKE_CYCLE,
            })
        guarantee = None
        if up_guarantee:
            guarantee = {"target": up_guarantee, "progress": min(paid, up_guarantee)}
        b["six"].reverse()
        out_banners.append({
            "name": b["name"],
            "pool_id": b["pool_id"],
            "kind": kind,
            "featured": featured,
            "paid": paid,
            "free": b["free"],
            "total": paid + b["free"],
            "time_range": _range(b["first_ts"], b["last_ts"]),
            "start_ts": b["first_ts"],
            "end_ts": b["last_ts"],
            "six": b["six"],
            "six_count": len(b["six"]),
            "up_count": b["up_count"] + b["free_up"],
            "up_at": b["up_at"],
            "free_up": b["free_up"],
            "free_batches": _free_batches(b["free_records"]),
            "arsenal_quota": b["quota"],
            "guarantee": guarantee,
            "milestones": milestones,
        })
    out_banners.sort(key=lambda x: x["start_ts"], reverse=True)

    all_six = [s for b in out_banners for s in b["six"]]
    paid_six = [s for s in all_six if not s["free"]]
    paid_total = sum(b["paid"] for b in out_banners)
    free_total = sum(b["free"] for b in out_banners)
    up_total = sum(1 for s in all_six if s["is_up"])
    if chain_mode == "per_pool":
        latest = out_banners[0]["pool_id"] if out_banners else ""
        pity_now = per_pool_chain.get(latest, 0)
    else:
        pity_now = chain
    return {
        "key": kind,
        "title": "寻访·" + key[len(UNKNOWN_CHAR_PREFIX):] if key.startswith(UNKNOWN_CHAR_PREFIX) else key,
        "type": "char",
        "has_up": has_up,
        "chain": chain_mode,
        "pity_max": 40 if kind == "beginner" else CHAR_PITY,
        "pity": pity_now,
        "total": paid_total + free_total,
        "arsenal_quota": quota,
        "free": free_total,
        "six_count": len(all_six),
        "up_count": up_total,
        "wai_count": sum(1 for s in paid_six if has_up and not s["is_up"]),
        "avg_six": round(sum(s["pity"] for s in paid_six) / len(paid_six), 1) if paid_six else 0,
        "avg_up": round(paid_total / up_total, 1) if up_total else 0,
        "time_range": _group_range(out_banners),
        "banners": out_banners,
    }


def _range(a: int, b: int) -> str:
    if not a:
        return ""
    if not b or fmt_day(a) == fmt_day(b):
        return fmt_day(a)
    return f"{fmt_day(a)} - {fmt_day(b)}"


def _group_range(banners: list) -> str:
    starts = [b["start_ts"] for b in banners if b["start_ts"]]
    return _range(min(starts, default=0), max((b["end_ts"] for b in banners), default=0))


def _weapon_gifts(claims: int) -> tuple[list, Optional[dict]]:
    """返回 (已获得赠礼列表, 下一个赠礼)。"""
    got = []
    schedule = list(WEAPON_GIFTS_FIRST)
    at, kind = schedule[-1]
    while at <= claims + WEAPON_GIFT_STEP * 2:
        at += WEAPON_GIFT_STEP
        kind = "box" if kind == "up" else "up"
        schedule.append((at, kind))
    nxt = None
    for at, kind in schedule:
        if at <= claims:
            got.append(kind)
        elif nxt is None:
            nxt = {"kind": kind, "at": at, "left": at - claims}
    return got, nxt


def _weapon_banner(pool_name: str, records: list, judge: UpJudge) -> dict:
    ordered = sorted(records, key=_seq_key)
    recs = [r for r in ordered if _is_pull(r)]
    gift_records = Counter(r.get("kind", "") for r in ordered if not _is_pull(r))
    pool_id = next((r.get("poolId") for r in ordered if r.get("poolId")), "")
    rerun = any(r.get("poolType") == "rerun" for r in ordered)
    kind = judge.weapon_kind(pool_name, pool_id, rerun)
    chain = 0
    since_up = 0
    up_at = 0
    six = []
    first_ts = last_ts = 0
    for i, r in enumerate(recs, 1):
        ts = ts_seconds(r.get("gachaTs"))
        if ts:
            first_ts = ts if not first_ts else min(first_ts, ts)
            last_ts = max(last_ts, ts)
        chain += 1
        since_up += 1
        if r.get("rarity") != 6:
            continue
        name = _item_name(r)
        is_up = judge.weapon_is_up(name, pool_name)
        if is_up and not up_at:
            up_at = i
        six.append({
            "name": name, "pity": chain, "free": False, "is_up": is_up,
            "tag": "up" if is_up else "std", "ts": ts, "carry": 0,
            "up_cost": since_up if is_up else 0,
        })
        chain = 0
        if is_up:
            since_up = 0
    six.reverse()
    total = len(recs)
    claims = total // 10
    gifts_got, gift_next = _weapon_gifts(claims) if kind != "weapon_constant" else ([], None)
    featured = judge.featured(pool_name) or [s["name"] for s in six if s["is_up"]][:1]
    return {
        "name": pool_name,
        "pool_id": pool_id,
        "kind": kind,
        "featured": featured,
        "total": total,
        "claims": claims,
        "pity": chain,
        "time_range": _range(first_ts, last_ts),
        "start_ts": first_ts,
        "end_ts": last_ts,
        "six": six,
        "six_count": len(six),
        "up_count": sum(1 for s in six if s["is_up"]),
        "up_at": up_at,
        "guarantee": {"target": WEAPON_UP_PITY, "progress": min(total, WEAPON_UP_PITY)},
        "gifts": {
            "up": max(gifts_got.count("up"), gift_records["gift_weapon"]),
            "box": max(gifts_got.count("box"), gift_records["gift_weapon_box"]),
            "next": gift_next,
        },
    }


def _weapon_group(key: str, title: str, banners: list) -> dict:
    banners.sort(key=lambda x: x["start_ts"], reverse=True)
    all_six = [s for b in banners for s in b["six"]]
    total = sum(b["total"] for b in banners)
    up_total = sum(1 for s in all_six if s["is_up"])
    return {
        "key": key,
        "title": title,
        "type": "weapon",
        "has_up": True,
        "chain": "per_pool",
        "pity_max": WEAPON_PITY,
        "pity": banners[0]["pity"] if banners else 0,
        "total": total,
        "six_count": len(all_six),
        "up_count": up_total,
        "wai_count": len(all_six) - up_total,
        "avg_six": round(sum(s["pity"] for s in all_six) / len(all_six), 1) if all_six else 0,
        "avg_up": round(total / up_total, 1) if up_total else 0,
        "time_range": _group_range(banners),
        "banners": banners,
    }


def analyze(pool_data: dict, meta: Optional[dict]) -> list:
    """把原始抽卡记录整理为分组列表（特许 → 重构 → 武库 → 辉光 → 常驻武库 → 基础 → 启程 → 其它）。"""
    judge = UpJudge(meta or {}, pool_data)
    char_groups = {}
    for key, recs in pool_data.items():
        if key.startswith(WEAPON_PREFIX) or not recs:
            continue
        char_groups[key] = _char_group(key, recs, judge)

    limited: list = []
    constant: list = []
    for key, recs in pool_data.items():
        if not key.startswith(WEAPON_PREFIX) or not recs:
            continue
        b = _weapon_banner(key[len(WEAPON_PREFIX):], recs, judge)
        (constant if b["kind"] == "weapon_constant" else limited).append(b)

    groups = []
    for key in ("特许寻访", "重构寻访"):
        if key in char_groups:
            groups.append(char_groups.pop(key))
    if limited:
        groups.append(_weapon_group("weapon", "武库申领", limited))
    if "辉光庆典" in char_groups:
        groups.append(char_groups.pop("辉光庆典"))
    if constant:
        groups.append(_weapon_group("weapon_constant", "常驻申领", constant))
    for key in ("基础寻访", "启程寻访"):
        if key in char_groups:
            groups.append(char_groups.pop(key))
    groups.extend(char_groups.values())
    return groups


def summarize(groups: list) -> dict:
    char_groups = [g for g in groups if g["type"] == "char"]
    weapon_groups = [g for g in groups if g["type"] == "weapon"]
    quota = sum(g["arsenal_quota"] for g in char_groups)
    return {
        "arsenal_quota": quota,
        "arsenal_draws": quota // ARSENAL_CLAIM_COST * 10,
        "char_total": sum(g["total"] for g in char_groups),
        "char_six": sum(g["six_count"] for g in char_groups),
        "char_up": sum(g["up_count"] for g in char_groups if g["has_up"]),
        "weapon_total": sum(g["total"] for g in weapon_groups),
        "weapon_six": sum(g["six_count"] for g in weapon_groups),
        "weapon_up": sum(g["up_count"] for g in weapon_groups),
    }
