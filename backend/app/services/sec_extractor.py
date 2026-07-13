"""Lightweight SEC filing text extractor.

Extracts key sections (Business Description, MD&A) directly from
SEC 10-K/20-F filings using regex — no LLM or browser needed.
Also extracts specific financial line items from notes.
"""

import re
from html.parser import HTMLParser
from typing import Optional, Dict, List, Tuple

from app.services.sec_client import get_filing_text, get_full_text_url


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data)

    def get_text(self):
        return "".join(self.text)


def _strip_html(html: str) -> str:
    stripper = _HTMLStripper()
    try:
        stripper.feed(html)
        return stripper.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", "", html)


def _normalize(text: str) -> str:
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u00a0", " ")
    return text


def _flexible_regex(pattern: str) -> str:
    escaped = re.escape(pattern.upper())
    flexible = escaped.replace(r"\ ", r"\s+")
    flexible = re.sub(r"\\\.\\\s+", r"\\.\\s*", flexible)
    return flexible


def _extract_section(text: str, start_patterns: list, end_patterns: list, max_chars: int = 50_000) -> Optional[str]:
    """Extract a section from filing text by heading patterns.
    Picks the longest match to skip table-of-contents snippets.
    """
    best: Optional[str] = None
    best_len = 0

    for pattern in start_patterns:
        rx = _flexible_regex(pattern)
        try:
            for m in re.finditer(rx, text, re.IGNORECASE):
                start = m.start()
                end = len(text)
                for ep in end_patterns:
                    em = re.search(_flexible_regex(ep), text[start + len(m.group(0)):], re.IGNORECASE)
                    if em:
                        end = min(end, start + len(m.group(0)) + em.start())
                section = text[start:end][:max_chars]
                if len(section) > best_len:
                    best_len = len(section)
                    best = section
        except re.error:
            continue
    return best


def _truncate(text: str, max_chars: int = 8_000) -> str:
    """Truncate long text with an ellipsis."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit("\n", 1)[0] + "\n\n*[...truncated — full text available in SEC filing]*"


async def extract_qualitative(company_name: str, ticker: str, cik: str, accession_number: str) -> Dict[str, str]:
    """Extract business description and MD&A from SEC filing. Zero LLM cost."""
    url = get_full_text_url(cik, accession_number)
    try:
        raw = await get_filing_text(url)
    except Exception as e:
        return {
            "history_and_development": f"Unable to fetch filing: {e}",
            "mdna_analysis": "",
        }

    text = _normalize(_strip_html(raw))

    # --- Item 1: Business ---
    business = _extract_section(
        text,
        ["ITEM 1. BUSINESS", "ITEM 1.BUSINESS", "ITEM 1 BUSINESS"],
        [
            "ITEM 1A. RISK FACTORS", "ITEM 1A.RISK FACTORS",
            "ITEM 1B. UNRESOLVED STAFF COMMENTS",
            "ITEM 2. PROPERTIES", "ITEM 2.PROPERTIES",
            "ITEM 7. MANAGEMENT'S DISCUSSION",
            "ITEM 8. FINANCIAL STATEMENTS",
        ],
        max_chars=60_000,
    )

    # --- Item 7: MD&A ---
    mdna = _extract_section(
        text,
        [
            "ITEM 7. MANAGEMENT'S DISCUSSION",
            "ITEM 7.MANAGEMENT'S DISCUSSION",
            "ITEM 7 MANAGEMENT'S DISCUSSION",
            "ITEM 7. MD&A",
        ],
        [
            "ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES",
            "ITEM 7A.QUANTITATIVE AND QUALITATIVE DISCLOSURES",
            "ITEM 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA",
            "ITEM 8.FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA",
            "ITEM 9. CHANGES IN AND DISAGREEMENTS WITH ACCOUNTANTS",
        ],
        max_chars=80_000,
    )

    biz_text = _truncate(business) if business else "Business section not found in filing."
    mdna_text = _truncate(mdna) if mdna else "MD&A section not found in filing."

    return {
        "history_and_development": biz_text,
        "mdna_analysis": mdna_text,
    }


def _parse_financial_line(text: str, max_lines: int = 30) -> List[Tuple[int, float]]:
    """
    Parse financial table lines to extract (fiscal_year, value_in_millions).
    Returns list of (year, amount) tuples. Amount is in millions if large.
    """
    results = []
    # Common patterns for years and amounts
    # "2025    123,456"  or "2025    $123.4 million" or "2025  (123,456)"
    for line in text.split('\n'):
        line = line.strip()
        if not line or len(line) > 200:
            continue
        # Find years like 2020-2026
        year_matches = re.findall(r'\b(20[12]\d)\b', line)
        # Find numbers (may have commas, decimals, parentheses for negatives)
        num_matches = re.findall(r'[-−]?\$?([\d,]+(?:\.\d+)?)', line)
        if year_matches and num_matches:
            # Take first number as the amount for that year
            for ym in year_matches:
                for nm in num_matches:
                    try:
                        val = float(nm.replace(',', ''))
                        if val > 0:  # ignore small/zero values
                            results.append((int(ym), val))
                    except ValueError:
                        continue
        if len(results) > max_lines:
            break
    return results


async def extract_depreciation_from_filing(cik: str, accession_number: str) -> Dict[int, float]:
    """
    Extract depreciation expense from 10-K/20-F filing notes.
    Returns {fiscal_year: depreciation_in_millions}.
    Looks for:
    1. PPE notes: "depreciation expense"
    2. Cash flow statement: "depreciation"
    """
    url = get_full_text_url(cik, accession_number)
    try:
        raw = await get_filing_text(url)
    except Exception:
        return {}

    text = _normalize(_strip_html(raw))
    dep_values: Dict[int, float] = {}

    # Strategy 1: Extract "Depreciation expense" line with multiple years
    # Common phrasing: "Depreciation expense was $X million, $Y million, $Z million for the years ended..."
    dep_patterns = [
        r'depreciation\s+expense[^.]*?\$([\d,]+(?:\.\d+)?)\s*(?:million|billion|in\s+millions)',
        r'depreciation\s+(?:of\s+)?(?:property|plant)[^.]*?\$([\d,]+(?:\.\d+)?)\s*(?:million|billion|in\s+millions)',
        r'depreciation\s+(?:and\s+amort(?:i|)sation)?\s+expense[^.]*?\$([\d,]+(?:\.\d+)?)\s*(?:million|billion|in\s+millions)',
    ]
    for pat in dep_patterns:
        matches = re.findall(pat, text, re.IGNORECASE | re.DOTALL)
        if matches:
            # Find years near these matches
            for m in re.finditer(pat, text, re.IGNORECASE | re.DOTALL):
                context = text[max(0, m.start()-200):min(len(text), m.end()+200)]
                years_nearby = re.findall(r'\b(20[12]\d)\b', context)
                amount_str = m.group(1).replace(',', '')
                try:
                    amount = float(amount_str)
                    for y in years_nearby:
                        if int(y) not in dep_values:
                            dep_values[int(y)] = amount
                except ValueError:
                    pass

    # Strategy 2: Look for depreciation line in a table format
    # "Depreciation    12,345    13,456    14,567"
    dep_table_patterns = [
        r'[Dd]epreciation[^\n\r]*?([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)',
        r'[Dd]epreciation\s+expense[^\n\r]*?([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)',
    ]
    for pat in dep_table_patterns:
        matches = re.findall(pat, text)
        if matches:
            # Typically the three numbers are for three fiscal years in chronological order
            for triplet in matches:
                try:
                    vals = [float(v.replace(',', '')) for v in triplet]
                    # Guess fiscal years based on current year
                    from datetime import datetime
                    current_year = datetime.now().year
                    years = [current_year - 2, current_year - 1, current_year]
                    for y, v in zip(years, vals):
                        if y not in dep_values and v > 0:
                            dep_values[y] = v
                except (ValueError, IndexError):
                    pass

    return dep_values
