import httpx
from datetime import datetime
from typing import Optional, Dict

# In-memory cache: {(date, currency): rate}
_rate_cache: Dict[tuple, Optional[float]] = {}


async def get_usd_exchange_rate(date_str: str, currency: str) -> Optional[float]:
    """
    Fetch the USD exchange rate for a given currency on a given date.
    Returns how many USD 1 unit of `currency` equals.
    e.g. EUR->USD = 1.04 means 1 EUR = 1.04 USD
    """
    if currency == "USD":
        return 1.0

    # Normalize date
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        normalized_date = dt.strftime("%Y-%m-%d")
    except ValueError:
        return None

    cache_key = (normalized_date, currency)
    if cache_key in _rate_cache:
        return _rate_cache[cache_key]

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            url = f"https://api.frankfurter.app/{normalized_date}?from={currency}&to=USD"
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                rate = data.get("rates", {}).get("USD")
                _rate_cache[cache_key] = rate
                return rate
            # Some currencies may not be supported
            _rate_cache[cache_key] = None
            return None
    except Exception:
        _rate_cache[cache_key] = None
        return None
