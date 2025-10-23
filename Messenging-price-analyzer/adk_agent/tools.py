# adk_agent/tools.py
from __future__ import annotations

import os
import re
import io
import json
import glob
import shutil
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd
from dotenv import load_dotenv

# Load env
load_dotenv()

# ---------------- Flags & Paths ----------------
EMAIL_DIR       = os.getenv("EMAIL_DIR_DEFAULT", "data/email_memory")          # seed/mock emails (.eml)
INBOX_TODAY_DIR = os.getenv("INBOX_TODAY_DIR", "data/inbox_today")      # working folder
LOG_DIR         = os.getenv("LOG_DIR", "logs")
SUMMARY_TITLE   = os.getenv("SUMMARY_TITLE", "Daily SMS Price Changes")

USE_GRAPH    = os.getenv("USE_GRAPH", "false").lower() in ("1", "true", "yes")
MOCK_EMAIL   = os.getenv("MOCK_EMAIL", "false").lower() in ("1", "true", "yes")
MOCK_LLM     = os.getenv("MOCK_LLM", "false").lower() in ("1", "true", "yes")
DRY_RUN      = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")
MAX_MESSAGES = int(os.getenv("MAX_MESSAGES", "0"))  # 0 = no cap
DEBUG_TABLES = os.getenv("DEBUG_TABLES", "false").lower() in ("1", "true", "yes")

from utils.email_reader import iter_eml_messages
from utils.attachment_parser import parse_attachments
from utils.price_analyzer import (
    load_previous_prices,
    save_current_prices,
    compare_prices,
)
from utils.mailer import send_email  # keep your existing implementation

try:
    from utils.graph_mail import fetch_shared_mailbox_to_folder
except Exception:
    fetch_shared_mailbox_to_folder = None  # optional

# ---------------- Logging helpers ----------------
def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def _ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p

def _copy_if_empty(src_dir: str, dest_dir: str) -> int:
    _ensure_dir(dest_dir)
    existing = [n for n in os.listdir(dest_dir) if n.lower().endswith(".eml")]
    if existing:
        return 0
    count = 0
    if os.path.isdir(src_dir):
        for name in os.listdir(src_dir):
            if name.lower().endswith(".eml"):
                shutil.copy2(os.path.join(src_dir, name), os.path.join(dest_dir, name))
                count += 1
    return count

def _read_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _att_name(att) -> str:
    if isinstance(att, str):
        return os.path.basename(att) or "attachment"
    if isinstance(att, dict):
        for k in ("filename", "name", "FileName", "file_name", "path"):
            if k in att and att[k]:
                return os.path.basename(str(att[k]))
    return "attachment"

def _ext(name: str) -> str:
    return os.path.splitext(name.lower())[1].lstrip(".")

def _price_any(rec: Dict) -> Optional[float]:
    if not isinstance(rec, dict):
        return None
    for k in ("new_price", "price", "rate", "current_rate", "previous_rate", "old_price"):
        v = rec.get(k)
        try:
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str) and v.strip():
                return float(v.replace(",", "."))
        except Exception:
            pass
    return None

# ---------------- Normalization ----------------
def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(h).strip().lower())

def _parse_price_cell(cell, header_currency: str | None = None) -> tuple[Optional[float], Optional[str]]:
    """
    Handles '€ 0.123', '0.123 €', 'USD 0.123', '0,123 EUR', 0.123
    """
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
    price   = find_first(["price", "rate", "eur", "usd", "cost", "mt_price"])
    change  = find_first(["change", "delta", "variation"])
    valid   = find_first(["valid", "effective", "start_date", "effective_date"])

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
        print("  -> headers:", list(df.columns))
        print("  -> picked:", dict(country=country, network=network, price=price, change=change, valid=valid, header_currency=header_currency))

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
            "country":  (str(r.get(country_col)).strip() if country_col else None),
            "operator": (str(r.get(network_col)).strip() if network_col else None),
            "new_price": price,
            "currency": currency,
            "variation": (str(r.get(change_col)).strip().lower() if change_col else None),
            "effective_date": (str(r.get(valid_col)).strip() if valid_col else None),
        })
    return out

# ---------------- HTML table parser (no LLM) ----------------
def _rows_from_html_tables(html: str, provider_hint: str | None = None) -> list[dict]:
    if not html or "<table" not in html.lower():
        return []
    try:
        frames = pd.read_html(io.StringIO(html))  # list[DataFrame]
    except Exception:
        return []
    out: list[dict] = []
    for df in frames:
        out.extend(_rows_from_dataframe(df, provider_hint))
    return out

# ---------------- Tabular attachment parser (no LLM) ----------------
def _frames_from_tabular_attachment(att) -> list[pd.DataFrame]:
    path = None
    if isinstance(att, str):
        path = att
    elif isinstance(att, dict):
        for k in ("path", "filepath", "file_path", "filename", "name", "FileName"):
            if k in att and att[k]:
                path = str(att[k])
                break
    if not path or not os.path.exists(path):
        return []

    ext = _ext(path)
    try:
        if ext == "csv":
            # delimiter + encoding inference
            try:
                df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8", on_bad_lines="skip")
            except Exception:
                df = pd.read_csv(path, sep=None, engine="python", encoding="latin-1", on_bad_lines="skip")
            return [df]

        if ext in ("xls", "xlsx"):
            xls = pd.ExcelFile(path)
            frames = []
            for sheet_name in xls.sheet_names:
                try:
                    frames.append(xls.parse(sheet_name=sheet_name))
                except Exception:
                    continue
            return frames
    except Exception:
        return []
    return []

# ---------------- Fetch ----------------
def _fetch_emails_internal(days_back: int, use_graph_flag: bool) -> str:
    inbox = _ensure_dir(INBOX_TODAY_DIR)
    if not use_graph_flag or MOCK_EMAIL:
        copied = _copy_if_empty(EMAIL_DIR, inbox)
        _log(f"fetch_emails(mock): inbox='{inbox}', copied={copied}")
        return inbox

    if fetch_shared_mailbox_to_folder is None:
        raise RuntimeError("Graph fetch not available. Set USE_GRAPH=false (mock).")

    tenant        = os.getenv("MS_TENANT_ID", "")
    client_id     = os.getenv("MS_CLIENT_ID", "")
    client_secret = os.getenv("MS_CLIENT_SECRET", "")
    shared_mail   = os.getenv("MS_SHARED_MAILBOX", "")
    mail_folder   = os.getenv("MS_MAIL_FOLDER", "Inbox")
    clear_first   = os.getenv("MS_CLEAR_DEST_FIRST", "true").lower() in ("1", "true", "yes")
    top           = int(os.getenv("MS_TOP", "100"))

    if not all([tenant, client_id, client_secret, shared_mail]):
        raise RuntimeError("Missing MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET / MS_SHARED_MAILBOX env vars.")

    _log("fetch_emails(graph): fetching from Microsoft Graph…")
    fetch_shared_mailbox_to_folder(
        tenant_id=tenant,
        client_id=client_id,
        client_secret=client_secret,
        shared_mailbox=shared_mail,
        dest_folder=inbox,
        days_back=days_back,
        mail_folder=mail_folder,
        clear_dest_first=clear_first,
        top=top,
    )
    _log(f"fetch_emails(graph): saved to '{inbox}'")
    return inbox

# ---------------- Extraction ----------------
def _extract_from_message(msg: Dict) -> List[Dict]:
    # keep LLM import lazy (used only when MOCK_LLM=false)
    if not MOCK_LLM:
        from llm.extractor import extract_sms_prices_llm

    rows: List[Dict] = []
    filename = (msg.get("filename") or "").strip()
    provider_hint = os.path.splitext(filename)[0] or None
    body = (msg.get("body") or "").strip()

    # 1) HTML table in body (fast, no LLM)
    html_rows = _rows_from_html_tables(body, provider_hint=provider_hint)
    if html_rows:
        rows.extend(html_rows)
        _log(f"message: file='{filename[:80]}' html_table_rows={len(html_rows)}")

    # 2) Optional LLM on body
    if body and not MOCK_LLM:
        try:
            r = extract_sms_prices_llm(body, provider_hint=provider_hint)
            if r:
                rows.extend(r)
            _log(f"message: file='{filename[:80]}' body_rows={len(r) if r else 0}")
        except Exception as e:
            _log(f"extract body error: {e}")

    # 3) Attachments: CSV/XLS(X) first (no LLM), then fallback to text->LLM
    for att in msg.get("attachments", []):
        name = _att_name(att)
        ext = _ext(name)

        if ext in ("csv", "xls", "xlsx"):
            try:
                frames = _frames_from_tabular_attachment(att)
                parsed = 0
                for df in frames:
                    rows_from_df = _rows_from_dataframe(df, provider_hint=provider_hint)
                    if rows_from_df:
                        rows.extend(rows_from_df)
                        parsed += len(rows_from_df)
                _log(f"attachment(tabular): name='{name}' rows={parsed}")
                if parsed > 0:
                    continue
            except Exception as e:
                _log(f"attachment tabular parse error ({name}): {e}")

        # Fallback: parse to text
        try:
            text = parse_attachments(att)
        except Exception as e:
            _log(f"attachment parse error ({name}): {e}")
            text = ""
        if not text:
            _log(f"attachment text empty ({name})")
            continue

        if not MOCK_LLM:
            try:
                r2 = extract_sms_prices_llm(text, provider_hint=provider_hint)
            except Exception as e:
                _log(f"extract attachment error ({name}): {e}")
                r2 = []
        else:
            r2 = []  # mock mode: skip LLM

        if r2:
            rows.extend(r2)
        _log(f"attachment(text): name='{name}' rows={len(r2) if r2 else 0}")

    return rows

def _extract_rows_internal(box: str) -> List[Dict]:
    rows: List[Dict] = []
    count = 0
    for msg in iter_eml_messages(box):
        count += 1
        rows.extend(_extract_from_message(msg))
        if MAX_MESSAGES and count >= MAX_MESSAGES:
            _log(f"extract_rows: hit MAX_MESSAGES={MAX_MESSAGES}, stopping early")
            break
    _log(f"extract_rows: messages={count} rows={len(rows)}")
    return rows

# ---------------- Diff & Render ----------------
def _diff_and_snapshot_internal(rows: List[Dict]) -> Dict:
    stamp = _today()
    today_path  = os.path.join(LOG_DIR, f"parsed_{stamp}.json")
    latest_path = os.path.join(LOG_DIR, "latest.json")
    _ensure_dir(LOG_DIR)

    previous = load_previous_prices(latest_path)
    prev_len = len(previous) if isinstance(previous, list) else 0
    curr_len = len(rows) if isinstance(rows, list) else 0
    _log(f"diff input: previous={prev_len} current={curr_len}")

    diff = compare_prices(rows, previous)

    save_current_prices(rows, today_path)
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    diff_path = os.path.join(LOG_DIR, f"diff_{stamp}.json")
    with open(diff_path, "w", encoding="utf-8") as f:
        json.dump(diff, f, ensure_ascii=False, indent=2)

    _log(f"diff_and_snapshot: wrote '{today_path}', 'logs/latest.json', '{diff_path}'")
    return {"path": diff_path, "diff": diff}

def _render_html_internal(diff_for_html: Dict, title: str) -> str:
    def html_rows(section: str, rows: List[Dict]) -> str:
        head = f"<h2>{section}</h2>"
        if not rows:
            return head + "<p>No entries</p>"
        th = (
            "<table><tr>"
            "<th>Provider</th><th>Country</th><th>Operator</th>"
            "<th>Old</th><th>New</th><th>Currency</th><th>Variation</th>"
            "</tr>"
        )
        trs = []
        for r in rows:
            trs.append(
                "<tr>"
                f"<td>{r.get('provider','')}</td>"
                f"<td>{r.get('country','')}</td>"
                f"<td>{r.get('operator') or r.get('network') or ''}</td>"
                f"<td>{r.get('previous_rate') or r.get('old_price') or ''}</td>"
                f"<td>{r.get('new_price') or r.get('price') or ''}</td>"
                f"<td>{r.get('currency','')}</td>"
                f"<td>{r.get('variation','')}</td>"
                "</tr>"
            )
        return head + th + "".join(trs) + "</table>"

    stamp = _today()
    html_path = os.path.join(LOG_DIR, f"summary_{stamp}.html")
    _ensure_dir(LOG_DIR)
    title = title or SUMMARY_TITLE
    parts = [
        "<html><head><meta charset='utf-8'>",
        "<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:6px;font-size:12px}"
        "th{background:#f5f5f5;text-align:left}h2{margin:18px 0 6px}.small{color:#666;font-size:12px}</style>",
        "</head><body>",
        f"<h1>{title}</h1>",
        f"<p class=\"small\">Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>",
        html_rows("Changed", diff_for_html.get("changed", [])),
        html_rows("Added / New", diff_for_html.get("added", [])),
        html_rows("Removed", diff_for_html.get("removed", [])),
        f"<p>Unchanged pairs (not listed): {diff_for_html.get('unchanged_count', 0)}</p>",
        "</body></html>",
    ]
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    _log(f"render_html: wrote '{html_path}'")
    return html_path

def _adapt_diff_for_html(diff: Dict) -> Dict:
    # canonical -> flat adapter
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
                    "country":  (after or before or {}).get("country"),
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
                    "country":  n.get("country"),
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
                    "country":  r.get("country"),
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

# ---------------- Public tools ----------------
def fetch_emails(days_back: int = 1, use_graph: bool = False) -> str:
    use_graph_flag = bool(use_graph) and USE_GRAPH
    return _fetch_emails_internal(days_back=days_back, use_graph_flag=use_graph_flag)

def extract_rows(inbox_dir: str = "") -> str:
    box = inbox_dir or INBOX_TODAY_DIR
    rows = _extract_rows_internal(box)
    stamp = _today()
    out_path = os.path.join(LOG_DIR, f"extraction_{stamp}.json")
    _ensure_dir(LOG_DIR)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    _log(f"extract_rows: wrote '{out_path}'")
    return out_path

def diff_and_snapshot(rows_path: str = "") -> str:
    if not rows_path:
        candidates = sorted(glob.glob(os.path.join(LOG_DIR, "extraction_*.json")))
        if not candidates:
            raise ValueError("No extraction found. Run extract_rows first.")
        rows_path = candidates[-1]
    rows = _read_json(rows_path)
    info = _diff_and_snapshot_internal(rows)
    return info["path"]

def render_html(diff_path: str = "") -> str:
    if not diff_path:
        candidates = sorted(glob.glob(os.path.join(LOG_DIR, "diff_*.json")))
        if not candidates:
            raise ValueError("No diff found. Run diff_and_snapshot first.")
        diff_path = candidates[-1]
    diff = _read_json(diff_path)
    diff_for_html = _adapt_diff_for_html(diff)
    return _render_html_internal(diff_for_html, SUMMARY_TITLE)

def send_summary_email(html_path: str = "", to: str = "", subject: str = "") -> str:
    if not html_path:
        candidates = sorted(glob.glob(os.path.join(LOG_DIR, "summary_*.html")))
        if not candidates:
            raise ValueError("No HTML summary found. Run render_html first.")
        html_path = candidates[-1]
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    subj = subject or SUMMARY_TITLE
    if DRY_RUN:
        _log(f"[DRY_RUN] Would send email '{subj}' (file: {html_path})")
        return html_path
    recipients = [s.strip() for s in to.split(",")] if to else None
    send_email(subject=subj, html_body=html, to=recipients)
    _log("send_summary_email: sent.")
    return html_path

def run_daily_pipeline() -> str:
    _log(f"run_daily_pipeline: start (USE_GRAPH={USE_GRAPH} MOCK_EMAIL={MOCK_EMAIL} MOCK_LLM={MOCK_LLM})")
    inbox = fetch_emails(days_back=1, use_graph=USE_GRAPH)
    rows_path = extract_rows(inbox_dir=inbox)
    diff_path = diff_and_snapshot(rows_path=rows_path)
    html = render_html(diff_path=diff_path)
    if DRY_RUN:
        _log("[DRY_RUN] done -> Daily SMS Price Changes (not emailed)")
    else:
        send_summary_email(html_path=html, to="", subject=SUMMARY_TITLE)
        _log("run_daily_pipeline: done")
    return html
