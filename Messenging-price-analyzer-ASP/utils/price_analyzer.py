# utils/price_analyzer.py
from __future__ import annotations

import json
from typing import List, Dict, Tuple

Key = Tuple[str, str, str, str]  # (provider, country, operator, currency)

def _key(row: Dict) -> Key:
    return (
        (row.get("provider") or "").strip(),
        (row.get("country") or "").strip(),
        (row.get("operator") or row.get("network") or "").strip(),
        (row.get("currency") or "").strip().upper(),
    )

def _price(row: Dict) -> float | None:
    for k in ("new_price", "price", "rate", "current_rate"):
        v = row.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            try:
                return float(str(v).replace(",", "."))
            except Exception:
                pass
    return None

def load_previous_prices(path: str) -> List[Dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

def save_current_prices(rows: List[Dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

def compare_prices(current: List[Dict], previous: List[Dict]) -> Dict:
    prev_map = {_key(r): r for r in previous or []}
    cur_map  = {_key(r): r for r in current  or []}

    changed = []
    new = []
    removed = []

    for k, row in cur_map.items():
        if k not in prev_map:
            new.append(row)
            continue
        p_old = _price(prev_map[k])
        p_new = _price(row)
        if p_old is not None and p_new is not None and abs(p_new - p_old) > 1e-12:
            changed.append({"before": prev_map[k], "after": row, "delta": p_new - p_old})

    for k, row in prev_map.items():
        if k not in cur_map:
            removed.append(row)

    unchanged = len(cur_map) - len(new) - len(changed)
    return {
        "changed": changed,
        "new": new,
        "removed": removed,
        "summary": {"unchanged": max(unchanged, 0), "current_count": len(cur_map), "previous_count": len(prev_map)},
    }
