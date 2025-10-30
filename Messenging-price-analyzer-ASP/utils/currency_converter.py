# utils/currency_converter.py
"""
Currency conversion utilities for normalizing SMS pricing data.
Uses exchangerate-api.com (free tier: 1500 requests/month).
"""

from __future__ import annotations

import os
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from dotenv import load_dotenv

load_dotenv()

# Cache for exchange rates (in-memory, resets on restart)
_FX_CACHE: Dict[str, tuple[float, float]] = {}  # key -> (rate, timestamp)
_FX_CACHE_TTL = 3600  # 1 hour cache

# Fallback rates (if API fails, use approximate rates)
_FALLBACK_RATES = {
    "USD_EUR": 0.92,
    "GBP_EUR": 1.17,
    "SEK_EUR": 0.088,
    "NOK_EUR": 0.086,
    "DKK_EUR": 0.134,
    "CHF_EUR": 1.06,
    "PLN_EUR": 0.23,
    "CZK_EUR": 0.040,
    # Add the currencies from your data:
    "TEL_EUR": 1.0,  # Unknown currency, treat as EUR
    "AUS_EUR": 1.0,  # Australian? Needs clarification
    "ELE_EUR": 1.0,  # Unknown
    "DAV_EUR": 1.0,  # Unknown
    "ILE_EUR": 1.0,  # Unknown
    "TBD_EUR": 1.0,  # To Be Determined
    "GMO_EUR": 1.0,  # Unknown
    "COM_EUR": 1.0,  # Unknown
    "MOB_EUR": 1.0,  # Unknown
    "CAO_EUR": 1.0,  # Unknown
    "PRI_EUR": 1.0,  # Unknown
}


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [FX] {msg}")


def get_exchange_rate(from_currency: str, to_currency: str = "EUR") -> float:
    """
    Get exchange rate from one currency to another.
    """
    from_currency = from_currency.upper().strip()
    to_currency = to_currency.upper().strip()
    
    # Same currency
    if from_currency == to_currency:
        return 1.0
    
    # Check cache
    cache_key = f"{from_currency}_{to_currency}"
    now = datetime.now().timestamp()
    
    if cache_key in _FX_CACHE:
        rate, cached_time = _FX_CACHE[cache_key]
        if now - cached_time < _FX_CACHE_TTL:
            return rate
    
    # Try to fetch from API (only if API key is configured)
    api_key = os.getenv("EXCHANGE_RATE_API_KEY", "")
    
    if api_key:
        try:
            url = f"https://v6.exchangerate-api.com/v6/{api_key}/pair/{from_currency}/{to_currency}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            if data.get("result") == "success":
                rate = float(data.get("conversion_rate", 1.0))
                _FX_CACHE[cache_key] = (rate, now)
                _log(f"Fetched rate {from_currency}/{to_currency}: {rate:.6f}")
                return rate
        except Exception as e:
            _log(f"API fetch failed for {from_currency}/{to_currency}: {e}")
    
    # Use fallback rates immediately (don't try free API, it's unreliable)
    if cache_key in _FALLBACK_RATES:
        rate = _FALLBACK_RATES[cache_key]
        _FX_CACHE[cache_key] = (rate, now)  # Cache the fallback
        _log(f"Using fallback rate {from_currency}/{to_currency}: {rate:.6f}")
        return rate
    
    # Try reverse rate
    reverse_key = f"{to_currency}_{from_currency}"
    if reverse_key in _FALLBACK_RATES:
        rate = 1.0 / _FALLBACK_RATES[reverse_key]
        _FX_CACHE[cache_key] = (rate, now)  # Cache the fallback
        _log(f"Using reverse fallback rate {from_currency}/{to_currency}: {rate:.6f}")
        return rate
    
    # Last resort: return 1.0 and log warning
    _log(f"WARNING: No rate found for {from_currency}/{to_currency}, using 1.0")
    return 1.0


def convert_price(amount: float, from_currency: str, to_currency: str = "EUR") -> float:
    """
    Convert a price from one currency to another.
    
    Args:
        amount: Price amount to convert
        from_currency: Source currency code
        to_currency: Target currency code (default: 'EUR')
    
    Returns:
        Converted amount
    """
    if amount is None:
        return None
    
    rate = get_exchange_rate(from_currency, to_currency)
    return amount * rate


def normalize_prices_to_base(rows: List[Dict], base_currency: str = "EUR") -> List[Dict]:
    """
    Normalize all prices in a list of price records to a base currency.
    Adds 'normalized_price' and 'base_currency' fields to each row.
    
    Args:
        rows: List of price records
        base_currency: Target currency for normalization (default: 'EUR')
    
    Returns:
        List of records with normalized prices added
    """
    if not rows:
        return []
    
    normalized = []
    conversion_errors = 0
    
    for row in rows:
        row_copy = dict(row)
        
        # Get original price
        original_price = None
        for key in ("new_price", "price", "rate", "current_rate"):
            if key in row and row[key] is not None:
                try:
                    original_price = float(row[key])
                    break
                except (ValueError, TypeError):
                    pass
        
        # Get currency
        currency = (row.get("currency") or "EUR").upper().strip()
        
        if original_price is not None:
            try:
                normalized_price = convert_price(original_price, currency, base_currency)
                row_copy["normalized_price"] = round(normalized_price, 6)
                row_copy["base_currency"] = base_currency
                row_copy["original_currency"] = currency
            except Exception as e:
                _log(f"Conversion error for {row.get('country')}/{row.get('operator')}: {e}")
                row_copy["normalized_price"] = original_price
                row_copy["base_currency"] = currency
                row_copy["original_currency"] = currency
                conversion_errors += 1
        else:
            row_copy["normalized_price"] = None
            row_copy["base_currency"] = base_currency
            row_copy["original_currency"] = currency
        
        normalized.append(row_copy)
    
    if conversion_errors > 0:
        _log(f"WARNING: {conversion_errors} prices could not be converted")
    
    _log(f"Normalized {len(normalized)} prices to {base_currency}")
    return normalized


def get_supported_currencies() -> List[str]:
    """Get list of commonly supported currencies."""
    return ["EUR", "USD", "GBP", "SEK", "NOK", "DKK", "CHF", "PLN", "CZK", "HUF", "RON"]