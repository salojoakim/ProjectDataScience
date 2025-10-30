# adk_agent/tools.py
"""
Updated tools for GCS-based operation in AgentSpace.

Key changes:
1. All file operations go through GCS (utils/gcs_storage.py)
2. HTML summaries are returned as downloadable content
3. Email parsing works from GCS bucket
4. Snapshots stored in GCS
"""

from __future__ import annotations

import os
import re
import io
import json
import tempfile
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ---------------- Config ----------------
SUMMARY_TITLE = os.getenv("SUMMARY_TITLE", "Daily SMS Price Changes")
MOCK_EMAIL = os.getenv("MOCK_EMAIL", "false").lower() in ("1", "true", "yes")
MOCK_LLM = os.getenv("MOCK_LLM", "false").lower() in ("1", "true", "yes")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "0"))
DEBUG_TABLES = os.getenv("DEBUG_TABLES", "false").lower() in ("1", "true", "yes")

# GCS imports
from utils.gcs_storage import (
    get_storage,
    EMAILS_PREFIX,
    INBOX_PREFIX,
    LOGS_PREFIX,
    SUMMARIES_PREFIX,
)

from utils.attachment_parser import parse_attachments
from utils.price_analyzer import (
    load_previous_prices_gcs,
    save_current_prices_gcs,
    compare_prices,
)

# GCS email reader
from utils.email_reader_gcs import iter_eml_messages_gcs


from utils.currency_converter import normalize_prices_to_base
from utils.html_renderer import render_summary_html

# ---------------- Logging ----------------
def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")

# ---------------- Normalization (unchanged) ----------------
def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(h).strip().lower())

def _parse_price_cell(cell, header_currency: str | None = None) -> tuple[Optional[float], Optional[str]]:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return None, header_currency
    if isinstance(cell, (int, float)):
        return float(cell), header_currency

    s = str(cell).strip()
    if not s:
        return None, header_currency

    s_norm = s.replace("\xa0", " ").strip()
    pat = re.compile(
        r"(?:(?P<cur1>[€$£]|[A-Z]{3})\s*)?(?P<num>[0-9]+(?:[.,][0-9]+)?)\s*(?P<cur2>[€$£]|[A-Z]{3})?",
        re.IGNORECASE,
    )
    m = pat.search(s_norm)
    if not m:
        return None, header_currency

    num = m.group("num").replace(",", ".")
    try:
        val = float(num)
    except Exception:
        return None, header_currency

    cur = m.group("cur1") or m.group("cur2") or header_currency
    if cur in {"€", "$", "£"}:
        cur = {"€": "EUR", "$": "USD", "£": "GBP"}[cur]
    elif cur:
        cur = cur.upper()

    return val, cur

def _pick_columns(df: pd.DataFrame) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    cols = {_norm_header(c): str(c) for c in df.columns}
    norm_cols = list(cols.keys())

    def find_first(candidates):
        for c in norm_cols:
            if any(tok in c for tok in candidates):
                return c
        return None

    country = find_first(["country", "country_code", "destination"])
    network = find_first(["network", "operator", "carrier", "route"])
    price = find_first(["price", "rate", "eur", "usd", "cost", "mt_price"])
    change = find_first(["change", "delta", "variation"])
    valid = find_first(["valid", "effective", "start_date", "effective_date"])

    header_currency = None
    if price:
        raw_header = cols[price].upper()
        m = re.search(r"\((EUR|USD|GBP)\)", raw_header)
        if m:
            header_currency = m.group(1)
        else:
            m2 = re.search(r"\b(EUR|USD|GBP)\b", raw_header)
            if m2:
                header_currency = m2.group(1)

    if DEBUG_TABLES:
        print("  -> picked:", dict(country=country, network=network, price=price, 
                                   change=change, valid=valid, header_currency=header_currency))

    return country, network, price, change, valid, header_currency

def _rows_from_dataframe(df: pd.DataFrame, provider_hint: str | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    df = df.copy()
    df.columns = [_norm_header(c) for c in df.columns]
    country_col, network_col, price_col, change_col, valid_col, header_currency = _pick_columns(df)
    if not price_col:
        return []
    out = []
    for _, r in df.iterrows():
        price, currency = _parse_price_cell(r.get(price_col), header_currency=header_currency)
        if price is None:
            continue
        out.append({
            "provider": provider_hint,
            "country": (str(r.get(country_col)).strip() if country_col else None),
            "operator": (str(r.get(network_col)).strip() if network_col else None),
            "new_price": price,
            "currency": currency,
            "variation": (str(r.get(change_col)).strip().lower() if change_col else None),
            "effective_date": (str(r.get(valid_col)).strip() if valid_col else None),
        })
    return out

def _rows_from_html_tables(html: str, provider_hint: str | None = None) -> list[dict]:
    if not html or "<table" not in html.lower():
        return []
    try:
        frames = pd.read_html(io.StringIO(html))
    except Exception:
        return []
    out: list[dict] = []
    for df in frames:
        out.extend(_rows_from_dataframe(df, provider_hint))
    return out

def _frames_from_tabular_file(file_path: str) -> list[pd.DataFrame]:
    """Parse CSV/Excel from a local temp file path."""
    ext = os.path.splitext(file_path.lower())[1].lstrip(".")
    try:
        if ext == "csv":
            try:
                df = pd.read_csv(file_path, sep=None, engine="python", encoding="utf-8", on_bad_lines="skip")
            except Exception:
                df = pd.read_csv(file_path, sep=None, engine="python", encoding="latin-1", on_bad_lines="skip")
            return [df]

        if ext in ("xls", "xlsx"):
            xls = pd.ExcelFile(file_path)
            frames = []
            for sheet_name in xls.sheet_names:
                try:
                    frames.append(xls.parse(sheet_name=sheet_name))
                except Exception:
                    continue
            return frames
    except Exception as e:
        _log(f"Error parsing tabular file {file_path}: {e}")
        return []
    return []

# ---------------- Extraction ----------------
def _extract_from_message(msg: Dict) -> List[Dict]:
    if not MOCK_LLM:
        from llm.extractor import extract_sms_prices_llm

    rows: List[Dict] = []
    filename = msg.get("filename", "")
    provider_hint = os.path.splitext(filename)[0] or None
    body = msg.get("body", "")

    # 1) HTML tables in body
    html_rows = _rows_from_html_tables(body, provider_hint=provider_hint)
    if html_rows:
        rows.extend(html_rows)
        _log(f"message: {filename[:80]} -> {len(html_rows)} rows from HTML tables")

    # 2) LLM on body text
    if body and not MOCK_LLM:
        try:
            r = extract_sms_prices_llm(body, provider_hint=provider_hint)
            if r:
                rows.extend(r)
            _log(f"message: {filename[:80]} -> {len(r) if r else 0} rows from LLM body")
        except Exception as e:
            _log(f"LLM body extraction error: {e}")

    # 3) Attachments
    for att in msg.get("attachments", []):
        att_name = att.get("filename", "attachment")
        att_path = att.get("temp_path")  # Will be a temp file path
        
        if not att_path:
            continue
        
        ext = os.path.splitext(att_name.lower())[1].lstrip(".")

        # Tabular files
        if ext in ("csv", "xls", "xlsx"):
            try:
                frames = _frames_from_tabular_file(att_path)
                parsed = 0
                for df in frames:
                    rows_from_df = _rows_from_dataframe(df, provider_hint=provider_hint)
                    if rows_from_df:
                        rows.extend(rows_from_df)
                        parsed += len(rows_from_df)
                _log(f"attachment: {att_name} -> {parsed} rows (tabular)")
                if parsed > 0:
                    continue
            except Exception as e:
                _log(f"Tabular parse error ({att_name}): {e}")

        # Fallback: parse to text, then LLM
        try:
            # parse_attachments expects a file path
            text = parse_attachments(att_path)
        except Exception as e:
            _log(f"Attachment parse error ({att_name}): {e}")
            text = ""
        
        if not text:
            continue

        if not MOCK_LLM:
            try:
                r2 = extract_sms_prices_llm(text, provider_hint=provider_hint)
            except Exception as e:
                _log(f"LLM attachment extraction error ({att_name}): {e}")
                r2 = []
        else:
            r2 = []

        if r2:
            rows.extend(r2)
        _log(f"attachment: {att_name} -> {len(r2) if r2 else 0} rows (text+LLM)")

    return rows

def _extract_rows_internal() -> List[Dict]:
    """Extract rows from emails in GCS inbox."""
    rows: List[Dict] = []
    count = 0
    
    for msg in iter_eml_messages_gcs(INBOX_PREFIX):
        count += 1
        rows.extend(_extract_from_message(msg))
        if MAX_MESSAGES and count >= MAX_MESSAGES:
            _log(f"Hit MAX_MESSAGES={MAX_MESSAGES}, stopping")
            break
    
    _log(f"Extracted {len(rows)} rows from {count} messages")
    
    # NEW: Normalize all prices to EUR for comparison
    from utils.currency_converter import normalize_prices_to_base
    rows = normalize_prices_to_base(rows, base_currency="EUR")
    
    return rows

# ---------------- Diff & Snapshot ----------------
def _diff_and_snapshot_internal(rows: List[Dict]) -> Dict:
    storage = get_storage()
    stamp = _today()
    
    # Save current extraction
    parsed_blob = f"{LOGS_PREFIX}parsed_{stamp}.json"
    latest_blob = f"{LOGS_PREFIX}latest.json"
    
    # Load previous
    previous = load_previous_prices_gcs(latest_blob)
    _log(f"Loaded {len(previous)} previous prices")
    
    # Compare
    diff = compare_prices(rows, previous)
    
    # Save current as latest and timestamped
    save_current_prices_gcs(rows, parsed_blob)
    save_current_prices_gcs(rows, latest_blob)
    
    # Save diff
    diff_blob = f"{LOGS_PREFIX}diff_{stamp}.json"
    storage.write_json(diff_blob, diff)
    
    _log(f"Diff saved: {diff_blob}")
    return {"path": diff_blob, "diff": diff}

def _adapt_diff_for_html(diff: Dict) -> Dict:
    """Convert canonical diff format to flat HTML format."""
    def _price_any(rec):
        if not isinstance(rec, dict):
            return None
        for k in ("new_price", "price", "rate", "current_rate", "previous_rate", "old_price"):
            v = rec.get(k)
            try:
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str) and v.strip():
                    return float(v.replace(",", "."))
            except:
                pass
        return None
    
    if isinstance(diff, dict) and "changed" in diff and "new" in diff and "removed" in diff:
        ch = diff.get("changed") or []
        if ch and isinstance(ch[0], dict) and "before" in ch[0]:
            changed_adapted = []
            for c in ch:
                before, after = c.get("before"), c.get("after")
                old = _price_any(before)
                newv = _price_any(after)
                direction = (
                    "increase" if (old is not None and newv is not None and newv > old)
                    else "decrease" if (old is not None and newv is not None and newv < old)
                    else "changed"
                )
                changed_adapted.append({
                    "provider": (after or before or {}).get("provider"),
                    "country": (after or before or {}).get("country"),
                    "operator": (after or before or {}).get("operator") or (after or before or {}).get("network"),
                    "previous_rate": old,
                    "new_price": newv,
                    "currency": (after or before or {}).get("currency"),
                    "variation": direction,
                })

            added_adapted = []
            for n in diff.get("new", []):
                added_adapted.append({
                    "provider": n.get("provider"),
                    "country": n.get("country"),
                    "operator": n.get("operator") or n.get("network"),
                    "previous_rate": None,
                    "new_price": _price_any(n),
                    "currency": n.get("currency"),
                    "variation": "new",
                })

            removed_adapted = []
            for r in diff.get("removed", []):
                removed_adapted.append({
                    "provider": r.get("provider"),
                    "country": r.get("country"),
                    "operator": r.get("operator") or r.get("network"),
                    "previous_rate": _price_any(r),
                    "new_price": None,
                    "currency": r.get("currency"),
                    "variation": "removed",
                })

            return {
                "added": added_adapted,
                "changed": changed_adapted,
                "removed": removed_adapted,
                "unchanged_count": diff.get("summary", {}).get("unchanged", 0) or diff.get("unchanged_count", 0),
            }

    return {
        "added": diff.get("added") or diff.get("new") or [],
        "changed": diff.get("changed", []),
        "removed": diff.get("removed", []),
        "unchanged_count": diff.get("unchanged_count", 0),
    }

def _render_html_internal(diff: Dict, title: str) -> str:
    """Generate enhanced HTML summary using the new renderer."""
    from utils.html_renderer import render_summary_html
    return render_summary_html(diff, title or SUMMARY_TITLE)

# ---------------- Public Tools ----------------

def fetch_emails_from_bucket() -> str:
    """
    Prepare emails for processing from GCS bucket.
    Copies emails from EMAILS_PREFIX to INBOX_PREFIX (working folder).
    
    Returns:
        Status message
    """
    storage = get_storage()
    
    # List emails in the main emails folder
    email_files = storage.list_files(prefix=EMAILS_PREFIX, suffix=".eml")
    
    if not email_files:
        return f"No .eml files found in gs://{storage.bucket_name}/{EMAILS_PREFIX}"
    
    # Copy to inbox (working folder)
    copied = 0
    for email_blob in email_files:
        # Extract filename
        filename = os.path.basename(email_blob)
        dest_blob = f"{INBOX_PREFIX}{filename}"
        
        try:
            storage.copy(email_blob, dest_blob)
            copied += 1
        except Exception as e:
            _log(f"Error copying {email_blob}: {e}")
    
    _log(f"Copied {copied} emails to inbox")
    return f"Fetched {copied} emails from bucket, ready for processing"

def extract_rows() -> str:
    """
    Extract pricing data from emails in inbox.
    
    Returns:
        Path to extraction results in GCS
    """
    storage = get_storage()
    rows = _extract_rows_internal()
    
    stamp = _today()
    extraction_blob = f"{LOGS_PREFIX}extraction_{stamp}.json"
    storage.write_json(extraction_blob, rows)
    
    _log(f"Extraction saved: {extraction_blob}")
    return f"Extracted {len(rows)} price records. Saved to {extraction_blob}"

def diff_and_snapshot() -> str:
    """
    Compare extracted prices against previous snapshot.
    
    Returns:
        Path to diff results in GCS
    """
    storage = get_storage()
    stamp = _today()
    
    # Load latest extraction
    extraction_blob = f"{LOGS_PREFIX}extraction_{stamp}.json"
    try:
        rows = storage.read_json(extraction_blob)
    except FileNotFoundError:
        return "No extraction found. Run extract_rows first."
    
    info = _diff_and_snapshot_internal(rows)
    return f"Diff complete. Found {len(info['diff'].get('changed', []))} changes, {len(info['diff'].get('new', []))} new routes. Saved to {info['path']}"

def generate_summary_html() -> Dict[str, str]:
    """
    Generate HTML summary of price changes with enhanced styling and anomaly detection.
    """
    storage = get_storage()
    stamp = _today()
    
    # Load latest diff
    diff_blob = f"{LOGS_PREFIX}diff_{stamp}.json"
    try:
        diff = storage.read_json(diff_blob)
    except FileNotFoundError:
        return {
            "error": "No diff found. Run diff_and_snapshot first.",
            "html": "",
            "download_url": ""
        }
    
    # Generate enhanced HTML
    html_content = _render_html_internal(diff, SUMMARY_TITLE)
    
    # Save to GCS
    summary_blob = f"{SUMMARIES_PREFIX}summary_{stamp}.html"
    storage.write_text(summary_blob, html_content)
    
    # Build GCS path
    gcs_path = f"gs://{storage.bucket_name}/{summary_blob}"
    
    # Try to generate signed URL
    download_url = gcs_path  # Default to GCS path
    message = f"Summary generated. Download using:\ngsutil cp {gcs_path} ./summary.html"
    
    try:
        download_url = storage.get_public_url(summary_blob, expiration=3600)
        message = "Summary generated successfully. Download from the URL (valid for 1 hour)."
        _log(f"✅ Generated signed URL: {summary_blob}")
    except Exception as e:
        _log(f"⚠️  Could not generate signed URL (need service account key): {e}")
        _log(f"📁 Use GCS path instead: {gcs_path}")
    
    # Build summary message
    summary_stats = diff.get("summary", {})
    changes = summary_stats.get("changes_count", 0)
    new_routes = summary_stats.get("new_count", 0)
    anomalies_count = summary_stats.get("anomalies_count", 0)
    
    summary_text = f"📊 Summary: {changes} price changes, {new_routes} new routes"
    if anomalies_count > 0:
        summary_text += f", ⚠️ {anomalies_count} anomalies detected!"
    
    return {
        "status": "success",
        "download_url": download_url,
        "gcs_path": gcs_path,
        "message": message,
        "summary": summary_text,
        "instructions": f"To download: gsutil cp {gcs_path} ./summary.html" if download_url == gcs_path else None
    }

def run_daily_pipeline() -> Dict[str, str]:
    """
    Run the complete daily pipeline:
    1. Fetch emails from bucket
    2. Extract pricing data
    3. Compare with previous day
    4. Generate HTML summary
    
    Returns:
        Dictionary with results and download URL
    """
    _log("Starting daily pipeline")
    
    # Step 1: Fetch
    fetch_result = fetch_emails_from_bucket()
    _log(f"Fetch: {fetch_result}")
    
    # Step 2: Extract
    extract_result = extract_rows()
    _log(f"Extract: {extract_result}")
    
    # Step 3: Diff
    diff_result = diff_and_snapshot()
    _log(f"Diff: {diff_result}")
    
    # Step 4: Generate summary
    summary_result = generate_summary_html()
    
    if "error" in summary_result:
        return summary_result
    
    _log("Pipeline complete")
    
    return {
        "status": "success",
        "message": "Daily pipeline completed successfully",
        "download_url": summary_result["download_url"],
        "summary": f"Fetch: {fetch_result}\nExtract: {extract_result}\nDiff: {diff_result}"
    }