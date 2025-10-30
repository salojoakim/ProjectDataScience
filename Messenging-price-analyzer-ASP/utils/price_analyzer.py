# utils/price_analyzer.py
"""
Enhanced price comparison logic with anomaly detection and statistics.
"""

from __future__ import annotations

import json
from typing import List, Dict, Tuple, Optional

Key = Tuple[str, str, str, str]  # (provider, country, operator, currency)


def _key(row: Dict) -> Key:
    return (
        (row.get("provider") or "").strip(),
        (row.get("country") or "").strip(),
        (row.get("operator") or row.get("network") or "").strip(),
        (row.get("currency") or "").strip().upper(),
    )


def _price(row: Dict) -> Optional[float]:
    """Extract price from a row, preferring normalized_price if available."""
    # First try normalized price (after currency conversion)
    if "normalized_price" in row and row["normalized_price"] is not None:
        try:
            return float(row["normalized_price"])
        except (ValueError, TypeError):
            pass
    
    # Fallback to original price fields
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


def _detect_anomalies(change_record: Dict, threshold_percent: float = 50.0) -> Optional[Dict]:
    """
    Detect anomalous price changes.
    
    Args:
        change_record: Dictionary with 'before', 'after', 'delta', 'percent_change'
        threshold_percent: Threshold for flagging changes (default: 50%)
    
    Returns:
        Anomaly record if detected, None otherwise
    """
    before = change_record.get("before", {})
    after = change_record.get("after", {})
    pct_change = change_record.get("percent_change", 0)
    delta = change_record.get("delta", 0)
    
    old_price = _price(before)
    new_price = _price(after)
    
    if old_price is None or new_price is None:
        return None
    
    anomaly = None
    
    # Type 1: Extreme percentage change (>50%)
    if abs(pct_change) > threshold_percent:
        severity = "critical" if abs(pct_change) > 100 else "high" if abs(pct_change) > 75 else "medium"
        anomaly = {
            **change_record,
            "anomaly_type": "extreme_change",
            "severity": severity,
            "reason": f"Price change of {pct_change:+.1f}% exceeds threshold"
        }
    
    # Type 2: Suspicious scale mismatch (jump from cents to dollars)
    elif new_price > 1.0 and old_price < 0.01:
        anomaly = {
            **change_record,
            "anomaly_type": "scale_mismatch",
            "severity": "critical",
            "reason": f"Suspicious jump from {old_price:.6f} to {new_price:.6f}"
        }
    
    # Type 3: Price went to zero or near-zero
    elif new_price < 0.0001 and old_price > 0.01:
        anomaly = {
            **change_record,
            "anomaly_type": "near_zero",
            "severity": "high",
            "reason": f"Price dropped to near-zero: {new_price:.6f}"
        }
    
    # Type 4: Unusually large absolute change (>0.1 EUR for small prices)
    elif abs(delta) > 0.1 and old_price < 0.5:
        anomaly = {
            **change_record,
            "anomaly_type": "large_absolute_change",
            "severity": "medium",
            "reason": f"Absolute change of {delta:+.4f} is large for base price {old_price:.4f}"
        }
    
    return anomaly


def load_previous_prices_gcs(blob_name: str) -> List[Dict]:
    """Load previous prices from GCS."""
    from utils.gcs_storage import get_storage
    
    storage = get_storage()
    try:
        data = storage.read_json(blob_name)
        if isinstance(data, list):
            return data
    except FileNotFoundError:
        print(f"No previous prices found at {blob_name} (this is normal for first run)")
    except Exception as e:
        print(f"Error loading previous prices: {e}")
    return []


def save_current_prices_gcs(rows: List[Dict], blob_name: str) -> None:
    """Save current prices to GCS."""
    from utils.gcs_storage import get_storage
    
    storage = get_storage()
    storage.write_json(blob_name, rows)


def compare_prices(current: List[Dict], previous: List[Dict]) -> Dict:
    """
    Enhanced price comparison with anomaly detection and statistics.
    
    Args:
        current: Current price records
        previous: Previous price records
    
    Returns:
        Dictionary with changes, anomalies, and statistics
    """
    prev_map = {_key(r): r for r in previous or []}
    cur_map = {_key(r): r for r in current or []}

    changed = []
    new = []
    removed = []
    anomalies = []

    # Track statistics
    price_increases = []
    price_decreases = []
    
    # Compare current vs previous
    for k, row in cur_map.items():
        if k not in prev_map:
            new.append(row)
            continue
        
        p_old = _price(prev_map[k])
        p_new = _price(row)
        
        if p_old is not None and p_new is not None and abs(p_new - p_old) > 1e-9:
            delta = p_new - p_old
            pct_change = (delta / p_old * 100) if p_old != 0 else 0
            
            change_record = {
                "before": prev_map[k],
                "after": row,
                "delta": round(delta, 6),
                "percent_change": round(pct_change, 2)
            }
            
            changed.append(change_record)
            
            # Track for statistics
            if delta > 0:
                price_increases.append(delta)
            else:
                price_decreases.append(delta)
            
            # Check for anomalies
            anomaly = _detect_anomalies(change_record)
            if anomaly:
                anomalies.append(anomaly)

    # Find removed entries
    for k, row in prev_map.items():
        if k not in cur_map:
            removed.append(row)

    unchanged = len(cur_map) - len(new) - len(changed)
    
    # Calculate statistics
    stats = {
        "unchanged": max(unchanged, 0),
        "current_count": len(cur_map),
        "previous_count": len(prev_map),
        "changes_count": len(changed),
        "new_count": len(new),
        "removed_count": len(removed),
        "anomalies_count": len(anomalies),
    }
    
    if price_increases:
        stats["avg_increase"] = round(sum(price_increases) / len(price_increases), 6)
        stats["max_increase"] = round(max(price_increases), 6)
        stats["increases_count"] = len(price_increases)
    else:
        stats["avg_increase"] = 0
        stats["max_increase"] = 0
        stats["increases_count"] = 0
    
    if price_decreases:
        stats["avg_decrease"] = round(sum(price_decreases) / len(price_decreases), 6)
        stats["max_decrease"] = round(min(price_decreases), 6)  # min because they're negative
        stats["decreases_count"] = len(price_decreases)
    else:
        stats["avg_decrease"] = 0
        stats["max_decrease"] = 0
        stats["decreases_count"] = 0
    
    # Calculate net change
    all_deltas = price_increases + price_decreases
    if all_deltas:
        stats["net_change"] = round(sum(all_deltas), 6)
        stats["avg_change"] = round(sum(all_deltas) / len(all_deltas), 6)
    else:
        stats["net_change"] = 0
        stats["avg_change"] = 0
    
    return {
        "changed": changed,
        "new": new,
        "removed": removed,
        "anomalies": anomalies,
        "summary": stats,
    }


# Keep original local functions for backward compatibility
def load_previous_prices(path: str) -> List[Dict]:
    """Load previous prices from local file (backward compatibility)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def save_current_prices(rows: List[Dict], path: str) -> None:
    """Save current prices to local file (backward compatibility)."""
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)