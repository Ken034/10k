import httpx
import asyncio
import re
from typing import Optional, Dict, Any, List
from datetime import datetime

from app.config import settings


HEADERS = {"User-Agent": settings.sec_user_agent}

# In-memory cache for ticker-to-CIK mapping
_TICKER_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


async def _get_client():
    return httpx.AsyncClient(headers=HEADERS, timeout=60.0)


async def get_ticker_mapping() -> Dict[str, Dict[str, Any]]:
    global _TICKER_CACHE
    if _TICKER_CACHE is not None:
        return _TICKER_CACHE

    async with await _get_client() as client:
        resp = await client.get("https://www.sec.gov/files/company_tickers.json")
        resp.raise_for_status()
        data = resp.json()

    mapping = {}
    for entry in data.values():
        ticker = entry["ticker"].upper()
        mapping[ticker] = {
            "cik": str(entry["cik_str"]).zfill(10),
            "name": entry["title"],
        }
    _TICKER_CACHE = mapping
    return mapping


async def get_company_by_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    mapping = await get_ticker_mapping()
    return mapping.get(ticker.upper())


def _cik_has_annual_filings(submissions: Dict[str, Any]) -> bool:
    """Check if a submissions response contains 10-K or 20-F filings."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    return any(f in ("10-K", "20-F") for f in forms)


async def _search_cik_by_ticker(ticker: str) -> Optional[str]:
    """
    Use SEC EFTS filing search to find the CIK that files 10-K under a given ticker.
    This handles cases where company_tickers.json maps a ticker to a shell entity
    (e.g. XOM -> 2115436 instead of the real 34088).
    """
    ticker_upper = ticker.upper()
    url = (
        f"https://efts.sec.gov/LATEST/search-index"
        f"?q=%22{ticker_upper}%22&forms=10-K"
        f"&dateRange=custom&startdt=2020-01-01&enddt=2030-12-31"
    )
    try:
        async with await _get_client() as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception:
        return None

    hits = data.get("hits", {}).get("hits", [])
    # display_names format: 'EXXON MOBIL CORP  (XOM)  (CIK 0000034088)'
    ticker_pattern = f"({ticker_upper})"
    for h in hits:
        src = h.get("_source", {})
        names = src.get("display_names", [])
        for name in names:
            if ticker_pattern in name:
                ciks = src.get("ciks", [])
                if ciks:
                    return ciks[0].zfill(10)
    return None


async def search_companies(query: str, limit: int = 10) -> List[Dict[str, str]]:
    """
    Search for companies by name or ticker.
    Returns list of {ticker, name, cik} matching the query.
    """
    mapping = await get_ticker_mapping()
    query_lower = query.lower()
    results = []

    for ticker, info in mapping.items():
        name = info["name"]
        # Match ticker exactly or name contains query
        if ticker == query.upper() or query_lower in name.lower():
            results.append({
                "ticker": ticker,
                "name": name,
                "cik": info["cik"],
            })

    # Sort: exact ticker match first, then by name length (shorter = more relevant)
    def sort_key(item):
        if item["ticker"] == query.upper():
            return (0, "")
        return (1, item["name"].lower())

    results.sort(key=sort_key)
    return results[:limit]


async def resolve_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    """
    Resolve a ticker to the CIK that has actual financial data (10-K/20-F).
    Handles SEC ticker mapping errors (e.g. XOM mapped to a shell entity).
    """
    info = await get_company_by_ticker(ticker)
    if not info:
        return None

    cik = info["cik"]

    # Check if this CIK has any 10-K or 20-F filings
    try:
        submissions = await get_submissions(cik)
    except Exception:
        return info

    if _cik_has_annual_filings(submissions):
        return info

    # No 10-K at this CIK — search SEC filings for the correct CIK
    real_cik = await _search_cik_by_ticker(ticker)
    if real_cik and real_cik != cik:
        try:
            real_subs = await get_submissions(real_cik)
            if _cik_has_annual_filings(real_subs):
                # Build a proper info dict for the real CIK
                real_name = real_subs.get("name", info["name"])
                return {
                    "cik": real_cik,
                    "name": real_name,
                }
        except Exception:
            pass

    # Return original info if no better match found
    return info


async def get_submissions(cik: str) -> Dict[str, Any]:
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    async with await _get_client() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def get_company_facts(cik: str) -> Dict[str, Any]:
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    async with await _get_client() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def get_filing_text(url: str) -> str:
    async with await _get_client() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def get_full_text_url(cik: str, accession_number: str) -> str:
    """Return the SEC full-text .txt URL for a filing."""
    accn_clean = accession_number.replace("-", "")
    cik_stripped = cik.lstrip("0") or "0"
    return f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{accn_clean}/{accession_number}.txt"


def find_latest_annual_filing_url(submissions: Dict[str, Any]) -> Optional[str]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    for idx, form in enumerate(forms):
        if form in ("10-K", "20-F"):
            accn = accession_numbers[idx].replace("-", "")
            doc = primary_docs[idx]
            return f"https://www.sec.gov/Archives/edgar/data/{submissions.get('cik', '').lstrip('0')}/{accn}/{doc}"
    return None


def get_recent_filings(submissions: Dict[str, Any], days: int = 7) -> List[Dict[str, Any]]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    cutoff = datetime.now().timestamp() - days * 24 * 3600
    results = []
    for idx, form in enumerate(forms):
        if form not in ("10-K", "20-F"):
            continue
        filing_dt = datetime.strptime(dates[idx], "%Y-%m-%d")
        if filing_dt.timestamp() < cutoff:
            continue
        accn = accession_numbers[idx]
        accn_clean = accn.replace("-", "")
        cik = submissions.get("cik", "").lstrip("0")
        doc = primary_docs[idx]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{doc}"
        results.append({
            "form": form,
            "filing_date": dates[idx],
            "fiscal_year": filing_dt.year,
            "accession_number": accn,
            "report_url": url,
        })
    return results


async def fetch_xbrl_instance_shares(
    cik: str, submissions: Dict[str, Any]
) -> Dict[int, float]:
    """
    Parse XBRL instance XML directly to extract share counts that the
    companyfacts API misses (e.g. BIDU reports shares with dimensional
    axes like ClassA/ClassB which companyfacts strips out).

    Returns dict of {fiscal_year: diluted_shares}.
    """
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    # Find recent 20-F / 10-K filings (last 5)
    filing_indices = []
    for idx, form in enumerate(forms):
        if form in ("10-K", "20-F"):
            filing_indices.append(idx)
        if len(filing_indices) >= 5:
            break

    if not filing_indices:
        return {}

    result: Dict[int, float] = {}
    cik_stripped = cik.lstrip("0") or "0"

    async with await _get_client() as client:
        for fidx in filing_indices:
            accn = accession_numbers[fidx]
            accn_clean = accn.replace("-", "")

            # Get the filing index to find the XBRL instance XML
            index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{accn_clean}/index.json"
            try:
                idx_resp = await client.get(index_url)
                if idx_resp.status_code != 200:
                    continue
                index_data = idx_resp.json()
            except Exception:
                continue

            # Find the XBRL instance XML file (usually *_htm.xml or *-*.xml)
            xml_file = None
            for item in index_data.get("directory", {}).get("item", []):
                name = item.get("name", "")
                if name.endswith(".xml") and ("htm.xml" in name or "xbrl" in name.lower()):
                    xml_file = name
                    break

            if not xml_file:
                continue

            # Fetch and parse the XBRL instance XML
            xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{accn_clean}/{xml_file}"
            try:
                xml_resp = await client.get(xml_url)
                if xml_resp.status_code != 200:
                    continue
                xml_text = xml_resp.text
            except Exception:
                continue

            # Parse WeightedAverageNumberOfDilutedSharesOutstanding
            # Look for entries with ClassA+ClassB combined context (no individual class axis)
            filing_year_shares = _parse_shares_from_xbrl(xml_text)
            for fy, shares in filing_year_shares.items():
                if fy not in result:
                    result[fy] = shares

    return result


def _parse_shares_from_xbrl(xml_text: str) -> Dict[int, float]:
    """
    Parse XBRL instance XML to extract WeightedAverageNumberOfDilutedSharesOutstanding.
    Handles dimensional contexts (ClassA+ClassB combined) that the companyfacts API strips.
    """
    result: Dict[int, float] = {}

    # First, build a context map: context_id -> {period_end, dimensions}
    context_map: Dict[str, Dict[str, Any]] = {}
    for m in re.finditer(
        r'<context[^>]*id="([^"]+)"[^>]*>(.*?)</context>', xml_text, re.DOTALL
    ):
        ctx_id = m.group(1)
        ctx_body = m.group(2)

        # Get period end date
        end_match = re.search(r"<endDate>([^<]+)</endDate>", ctx_body)
        start_match = re.search(r"<startDate>([^<]+)</startDate>", ctx_body)
        period_end = end_match.group(1) if end_match else None

        # Get dimensions
        dims: Dict[str, str] = {}
        for dim_m in re.finditer(
            r'<xbrldi:explicitMember[^>]*dimension="([^"]+)"[^>]*>([^<]+)<',
            ctx_body,
        ):
            dims[dim_m.group(1)] = dim_m.group(2)

        context_map[ctx_id] = {"end": period_end, "dims": dims}

    # Now find WeightedAverageNumberOfDilutedSharesOutstanding values
    pattern = (
        r'<us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding'
        r'([^>]*)>([^<]+)<'
    )
    for m in re.finditer(pattern, xml_text):
        attrs = m.group(1)
        val_str = m.group(2).strip()

        try:
            val = float(val_str)
        except ValueError:
            continue

        if val <= 0:
            continue

        # Get context ref
        ctx_match = re.search(r'contextRef="([^"]+)"', attrs)
        if not ctx_match:
            continue
        ctx_id = ctx_match.group(1)
        ctx = context_map.get(ctx_id, {})

        end_date = ctx.get("end")
        if not end_date:
            continue

        try:
            fy = int(end_date[:4])
        except (ValueError, IndexError):
            continue

        dims = ctx.get("dims", {})

        # Prefer the combined ClassA+ClassB context (has StatementClassOfStockAxis
        # with CommonClassAAndClassBMember) or no dimension at all
        stock_axis = dims.get("us-gaap:StatementClassOfStockAxis", "")
        is_combined = (
            "CommonClassAAndClassB" in stock_axis or stock_axis == ""
        )

        # Skip individual class entries (ClassA only, ClassB only)
        if not is_combined:
            continue

        # Also skip ADS-level entries (much smaller share count)
        eps_axis = dims.get("bidu:EarningsPerShareAxis", "")
        if "AmericanDepositary" in eps_axis:
            continue

        # Keep the largest value per year (combined > individual)
        if fy not in result or val > result[fy]:
            result[fy] = val

    return result
