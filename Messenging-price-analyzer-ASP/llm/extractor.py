"""
LLM-based extraction of SMS pricing rows from free text (email body or text
extracted from PDFs/DOCX). Two modes:

- MOCK_LLM=true  → uses a lightweight, rule-based extractor (fast and free).
- MOCK_LLM=false → uses Google Gemini via google.genai.
    * If GOOGLE_API_KEY is present -> Google AI (API-key) backend.
    * Else if GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION -> Vertex (ADC).
    * Else falls back to google-generativeai if API key exists.

Output: list[dict] of normalized rows.
"""

from __future__ import annotations
import os
import re
import json
from typing import List, Dict, Optional
from dotenv import load_dotenv

from .prompt_templates import PRICE_EXTRACTION_PROMPT

load_dotenv()

_BACKEND = None         # "genai_api", "genai_vertex", "old_api", or None
_client = None

API_KEY = os.getenv("GOOGLE_API_KEY")
V_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
V_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION")

_DEFAULT_MODEL_GENAI_API = os.getenv("EXTRACTOR_MODEL", "gemini-2.5-flash")  # Valid per your fix
_DEFAULT_MODEL_GENAI_VERTEX = os.getenv("EXTRACTOR_MODEL", "gemini-2.5-flash-001")  # For Vertex; confirm via list_models
_DEFAULT_MODEL_OLD = os.getenv("EXTRACTOR_MODEL", "gemini-2.5-flash")

try:
    from google import genai as _genai  # new SDK
    if API_KEY:
        _BACKEND = "genai_api"
        _client = _genai.Client(api_key=API_KEY)

        def _llm_generate(prompt: str, model: Optional[str] = None) -> str:
            model = model or _DEFAULT_MODEL_GENAI_API
            resp = _client.models.generate_content(model=model, contents=prompt)
            return (resp.text or "").strip()

    elif V_PROJECT and V_LOCATION:
        _BACKEND = "genai_vertex"
        _client = _genai.Client(vertexai={"project": V_PROJECT, "location": V_LOCATION})

        def _llm_generate(prompt: str, model: Optional[str] = None) -> str:
            model = model or _DEFAULT_MODEL_GENAI_VERTEX
            resp = _client.models.generate_content(model=model, contents=prompt)
            return (resp.text or "").strip()

    else:
        # Try old client only if an API key exists
        if API_KEY:
            import google.generativeai as _old_genai  # type: ignore
            _BACKEND = "old_api"
            _old_genai.configure(api_key=API_KEY)

            def _llm_generate(prompt: str, model: Optional[str] = None) -> str:
                model = model or _DEFAULT_MODEL_OLD
                resp = _old_genai.GenerativeModel(model).generate_content(prompt)
                return (getattr(resp, "text", "") or "").strip()
        else:
            _BACKEND = None

except Exception:
    try:
        if API_KEY:
            import google.generativeai as _old_genai  # type: ignore
            _BACKEND = "old_api"
            _old_genai.configure(api_key=API_KEY)

            def _llm_generate(prompt: str, model: Optional[str] = None) -> str:
                model = model or _DEFAULT_MODEL_OLD
                resp = _old_genai.GenerativeModel(model).generate_content(prompt)
                return (getattr(resp, "text", "") or "").strip()
        else:
            _BACKEND = None
    except Exception:
        _BACKEND = None

_NUMERIC_KEYS = {"previous_rate", "old_price", "current_rate", "new_price", "price", "count", "cost"}

def _first_json(text: str) -> Optional[str]:
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S)
    if m:
        return m.group(1)
    m2 = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
    return m2.group(1) if m2 else None

def _to_float(x) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x)
    s = s.replace("€", "").replace("$", "").replace("£", "")
    s = s.replace("\u00a0", " ").strip()
    s = s.replace(",", ".")
    s = re.sub(r"[A-Za-z]", "", s)
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in ("", ".", "-"):
        return None
    try:
        return float(s)
    except Exception:
        return None

def _normalize_record(rec: Dict) -> Dict:
    out = dict(rec)
    for k in list(out.keys()):
        if k in _NUMERIC_KEYS:
            out[k] = _to_float(out.get(k))
    var = out.get("variation")
    if isinstance(var, str):
        v = var.strip().lower()
        mapping = {
            "up": "increase", "increase": "increase", "inc": "increase",
            "down": "decrease", "decrease": "decrease", "dec": "decrease",
            "unchanged": "unchanged", "no change": "unchanged", "nochange": "unchanged",
            "new": "new",
        }
        out["variation"] = mapping.get(v, v)
    for k, v in list(out.items()):
        if isinstance(v, str) and v.strip() == "":
            out[k] = None
    return out

# --- simple rule-based fallback for MOCK_LLM=true ---
_COUNTRY_RE = re.compile(r"\bcountry(?:\s*iso)?\s*[:=]\s*([A-Za-z ()/&'-]+)", re.I)
_OPERATOR_RE = re.compile(r"\b(operator|network)\s*[:=]\s*([A-Za-z0-9 ()/&'._-]+)", re.I)
_MCC_RE = re.compile(r"\bmcc\D{0,5}(\d{2,4})\b", re.I)
_MNC_RE = re.compile(r"\bmnc\D{0,5}(\d{1,4})\b", re.I)
_CUR_RE = re.compile(r"\b(EUR|USD|SEK|GBP)\b", re.I)
_OLD_RE = re.compile(r"\b(old price|previous rate|old rate|current rate)\b\D{0,10}([0-9][0-9.,]*)", re.I)
_NEW_RE = re.compile(r"\b(new price|rate)\b\D{0,10}([0-9][0-9.,]*)", re.I)
_CHG_RE = re.compile(r"\b(increase|decrease|unchanged|up|down|new)\b", re.I)
_DATE_RE = re.compile(r"\b(20\d{2}[-/]\d{2}[-/]\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?)\b")

def _rule_based_extract(email_text: str, provider_hint: Optional[str]) -> List[Dict]:
    rows: List[Dict] = []
    blocks = [b.strip() for b in re.split(r"\n{2,}", email_text) if b.strip()]
    for block in blocks:
        old_match = _OLD_RE.search(block)
        new_match = _NEW_RE.search(block)
        if not (old_match or new_match):
            solo = re.search(r"\b(rate|price)\b\D{0,10}([0-9][0-9.,]*)", block, re.I)
            if not solo:
                continue

        country = (_COUNTRY_RE.search(block) or (None,))[1] if _COUNTRY_RE.search(block) else None
        operator = (_OPERATOR_RE.search(block) or (None, None, ""))[2] if _OPERATOR_RE.search(block) else None
        mcc = (_MCC_RE.search(block) or (None, ""))[1] if _MCC_RE.search(block) else None
        mnc = (_MNC_RE.search(block) or (None, ""))[1] if _MNC_RE.search(block) else None
        currency = (_CUR_RE.search(block) or (None, ""))[1].upper() if _CUR_RE.search(block) else None
        variation = (_CHG_RE.search(block) or (None, ""))[1] if _CHG_RE.search(block) else None
        eff = (_DATE_RE.search(block) or (None, ""))[1].replace("/", "-") if _DATE_RE.search(block) else None

        old_val = _to_float(old_match.group(2)) if old_match else None
        new_val = _to_float(new_match.group(2)) if new_match else None
        if new_val is None:
            solo = re.search(r"\b(rate|price)\b\D{0,10}([0-9][0-9.,]*)", block, re.I)
            if solo:
                new_val = _to_float(solo.group(2))

        row = {
            "provider": (provider_hint or None),
            "country": country,
            "country_iso": None,
            "country_code": None,
            "operator": operator,
            "network": None,
            "mcc": mcc,
            "mnc": mnc,
            "imsi": None,
            "nnc": None,
            "number_type": None,
            "destination": None,
            "previous_rate": old_val,
            "old_price": old_val,
            "current_rate": None,
            "new_price": new_val,
            "price": new_val if old_val is None else None,
            "currency": currency,
            "variation": variation,
            "effective_from": eff,
            "count": None,
            "cost": None,
            "product_category": None,
            "notes": None,
        }
        rows.append(_normalize_record(row))
    return rows


def extract_sms_prices_llm(email_text: str, provider_hint: Optional[str] = None) -> List[Dict]:
    """
    MOCK_LLM=true  -> rule-based parser (no API cost).
    MOCK_LLM=false -> Gemini via google.genai/google-generativeai per backend.
    """
    if not email_text or not email_text.strip():
        return []

    mock = os.getenv("MOCK_LLM", "false").lower() in ("1", "true", "yes")
    if mock:
        return _rule_based_extract(email_text, provider_hint)

    if _BACKEND is None:
        print("❌ No LLM backend configured. Set GOOGLE_API_KEY (API mode) or "
              "GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION for Vertex.")
        return []

    prompt = PRICE_EXTRACTION_PROMPT.format(
        email=email_text.strip(),
        provider_hint=(provider_hint or "")
    )

    try:
        raw = _llm_generate(prompt)
        json_str = _first_json(raw) or raw
        data = json.loads(json_str)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return []
        return [_normalize_record(r) for r in data if isinstance(r, dict)]
    except Exception as e:
        print(f"❌ LLM/parsing error: {e}")
        return []
