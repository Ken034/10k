from typing import Dict, List, Optional
import math


MILLION = 1_000_000.0


def to_millions(val: Optional[float]) -> Optional[float]:
    if val is None:
        return None
    return round(val / MILLION, 2)


def safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def compute_cagr(start_val: Optional[float], end_val: Optional[float], years: int) -> Optional[float]:
    if start_val is None or end_val is None or start_val <= 0 or end_val <= 0 or years <= 0:
        return None
    return round((math.pow(end_val / start_val, 1.0 / years) - 1.0) * 100, 2)


def normalize_for_stock_splits(shares: Dict[int, Optional[float]]) -> Dict[int, Optional[float]]:
    """
    Detect stock splits and normalize all share counts to the latest year's basis.
    When XBRL data has mixed pre/post-split values (due to restated 10-K filings),
    this detects outlier values and adjusts them to match the latest year.
    """
    valid = {fy: v for fy, v in shares.items() if v is not None and v > 0}
    if len(valid) < 2:
        return shares

    sorted_years = sorted(valid.keys())
    latest_fy = sorted_years[-1]
    latest_val = valid[latest_fy]
    if latest_val <= 0:
        return shares

    normalized = dict(shares)
    for fy in sorted_years:
        v = shares[fy]
        if v is None or v <= 0:
            continue
        # Compare each year to the latest year's value
        ratio = latest_val / v
        if ratio > 1.5:
            # This year is much smaller — likely pre-split, multiply up
            split_ratio = round(ratio)
            normalized[fy] = v * split_ratio
        elif ratio < (1 / 1.5):
            # This year is much larger — divide down to match
            split_ratio = round(1 / ratio)
            normalized[fy] = v / split_ratio

    return normalized


def _normalize_share_scale(shares: Dict[int, Optional[float]]) -> Dict[int, Optional[float]]:
    """
    Detect if shares are already reported in millions (e.g. MCD, UNH)
    vs raw share counts. Normalizes per-year because companies may switch
    reporting scale across years (e.g. MCD: raw shares before 2021, millions after).

    Heuristic per value:
    - < 100,000 → already in millions, multiply by 1M
    - >= 100,000 → raw shares, no adjustment
    """
    return {
        fy: v * MILLION if v is not None and 0 < v < 100_000 else v
        for fy, v in shares.items()
    }


def build_regular_metrics(raw: Dict[str, Dict[int, Optional[float]]], years: int = 15) -> Dict[str, Dict[int, Optional[float]]]:
    current_year = max(raw["revenue"].keys()) if raw["revenue"] else 0
    fiscal_years = list(range(current_year - years + 1, current_year + 1))

    metrics: Dict[str, Dict[int, Optional[float]]] = {}

    # Shares outstanding: use direct data, fallback to Net Income / Diluted EPS
    shares = {}
    for fy in fiscal_years:
        direct = raw["shares_diluted"].get(fy)
        if direct is not None:
            shares[fy] = direct
        else:
            ni = raw.get("net_income", {}).get(fy)
            eps = raw.get("eps_diluted", {}).get(fy)
            if ni is not None and eps is not None and eps != 0:
                shares[fy] = ni / eps
            else:
                shares[fy] = None

    # Detect scale: some companies report shares in millions (MCD, UNH) vs raw counts
    shares = _normalize_share_scale(shares)

    # Normalize for stock splits (e.g. AMZN 20:1 in 2022, AAPL 4:1 in 2020)
    shares = normalize_for_stock_splits(shares)

    metrics["shares_outstanding"] = {fy: round(v / MILLION) if v is not None else None for fy, v in shares.items()}
    metrics["revenue"] = {fy: to_millions(raw["revenue"].get(fy)) for fy in fiscal_years}
    metrics["depreciation"] = {fy: to_millions(raw["depreciation"].get(fy)) for fy in fiscal_years}
    metrics["net_profit"] = {fy: to_millions(raw["net_income"].get(fy)) for fy in fiscal_years}

    # EBITDA = Operating Income + Depreciation & Amortization
    # When operating income is unavailable (e.g. XOM uses custom XBRL taxonomy),
    # derive it from: Income Before Tax + Interest Expense
    ebitda = {}
    operating_margin = {}
    for fy in fiscal_years:
        op_income = raw["operating_income"].get(fy)
        dna = raw["depreciation_and_amortization"].get(fy)
        # Fallback: derive operating income from income before tax + interest expense
        if op_income is None:
            ibt = raw["income_before_tax"].get(fy)
            interest = raw["interest_expense"].get(fy)
            if ibt is not None and interest is not None:
                op_income = ibt + interest
        if op_income is not None and dna is not None:
            e = op_income + dna
        elif op_income is not None:
            e = op_income
        else:
            e = None
        ebitda[fy] = e
        # Operating Margin = (EBITDA - Depreciation) / Revenue * 100
        rev = raw["revenue"].get(fy)
        dep = raw["depreciation"].get(fy)
        if e is not None and dep is not None and rev:
            operating_margin[fy] = round(((e - dep) / rev) * 100, 1)
        elif e is not None and rev:
            # No depreciation available — fall back to EBITDA / Revenue
            operating_margin[fy] = round(safe_div(e, rev) * 100, 1)
        else:
            operating_margin[fy] = None

    metrics["operating_margin"] = operating_margin

    income_tax_rate = {}
    for fy in fiscal_years:
        tax = raw["income_tax_expense"].get(fy)
        ebt = raw["income_before_tax"].get(fy)
        if tax is not None and ebt is not None and ebt != 0:
            income_tax_rate[fy] = round((tax / ebt) * 100, 1)
        else:
            income_tax_rate[fy] = None
    metrics["income_tax_rate"] = income_tax_rate

    net_profit_margin = {}
    for fy in fiscal_years:
        ni = raw["net_income"].get(fy)
        rev = raw["revenue"].get(fy)
        net_profit_margin[fy] = round(safe_div(ni, rev) * 100, 1) if ni is not None and rev else None
    metrics["net_profit_margin"] = net_profit_margin

    total_debt = {}
    for fy in fiscal_years:
        st = raw["short_term_debt"].get(fy) or 0
        lt = raw["long_term_debt"].get(fy) or 0
        total_debt[fy] = to_millions(st + lt) if (st or lt) else None
    metrics["long_term_debt"] = total_debt

    metrics["ppe"] = {fy: to_millions(raw["ppe"].get(fy)) for fy in fiscal_years}
    metrics["inventory"] = {fy: to_millions(raw["inventory"].get(fy)) for fy in fiscal_years}

    return_on_capital = {}
    for fy in fiscal_years:
        e = ebitda.get(fy)
        dep = raw["depreciation"].get(fy)
        inv = raw["inventory"].get(fy)
        ppe = raw["ppe"].get(fy)
        denom = (inv or 0) + (ppe or 0)
        if e is not None and dep is not None and denom and denom != 0:
            return_on_capital[fy] = round(((e - dep) / denom) * 100, 1)
        elif e is not None and denom and denom != 0:
            # No depreciation available — use EBITDA (or operating income) as proxy
            return_on_capital[fy] = round((e / denom) * 100, 1)
        else:
            return_on_capital[fy] = None
    metrics["return_on_capital"] = return_on_capital

    return metrics


def build_banking_metrics(raw: Dict[str, Dict[int, Optional[float]]], years: int = 15) -> Dict[str, Dict[int, Optional[float]]]:
    current_year = max(raw["assets"].keys()) if raw["assets"] else 0
    fiscal_years = list(range(current_year - years + 1, current_year + 1))

    metrics: Dict[str, Dict[int, Optional[float]]] = {}
    # Shares: detect scale, then normalize for stock splits
    bank_shares = {fy: raw["shares_diluted"].get(fy) for fy in fiscal_years}
    bank_shares = _normalize_share_scale(bank_shares)
    bank_shares = normalize_for_stock_splits(bank_shares)
    metrics["shares_outstanding"] = {fy: to_millions(bank_shares.get(fy)) for fy in fiscal_years}
    metrics["total_assets"] = {fy: to_millions(raw["assets"].get(fy)) for fy in fiscal_years}
    metrics["loans"] = {fy: to_millions(raw["loans"].get(fy)) for fy in fiscal_years}
    metrics["net_interest_income"] = {fy: to_millions(raw["net_interest_income"].get(fy)) for fy in fiscal_years}
    metrics["noninterest_revenue"] = {fy: to_millions(raw["noninterest_income"].get(fy)) for fy in fiscal_years}
    metrics["noninterest_expense"] = {fy: to_millions(raw["noninterest_expense"].get(fy)) for fy in fiscal_years}
    metrics["net_profit"] = {fy: to_millions(raw["net_income"].get(fy)) for fy in fiscal_years}
    metrics["loan_loss_provision"] = {fy: to_millions(raw["loan_loss_provision"].get(fy)) for fy in fiscal_years}

    total_debt = {}
    for fy in fiscal_years:
        st = raw["short_term_debt"].get(fy) or 0
        lt = raw["long_term_debt"].get(fy) or 0
        total_debt[fy] = to_millions(st + lt) if (st or lt) else None
    metrics["long_term_debt"] = total_debt

    roa = {}
    roe = {}
    for fy in fiscal_years:
        ni = raw["net_income"].get(fy)
        assets = raw["assets"].get(fy)
        equity = raw["stockholders_equity"].get(fy)
        roa[fy] = round(safe_div(ni, assets) * 100, 1) if ni is not None and assets else None
        roe[fy] = round(safe_div(ni, equity) * 100, 1) if ni is not None and equity else None
    metrics["return_on_assets"] = roa
    metrics["return_on_equity"] = roe

    return metrics


def compute_cagr_table(metrics: Dict[str, Dict[int, Optional[float]]],
                       cagr_rows: List[str]) -> List[Dict[str, Optional[float]]]:
    current_year = max(metrics[cagr_rows[0]].keys()) if cagr_rows and metrics.get(cagr_rows[0]) else 0
    result = []
    for row in cagr_rows:
        series = metrics.get(row, {})
        end_val = series.get(current_year)
        result.append({
            "metric_name": row,
            "cagr_5y": compute_cagr(series.get(current_year - 5), end_val, 5),
            "cagr_10y": compute_cagr(series.get(current_year - 10), end_val, 10),
            "cagr_15y": compute_cagr(series.get(current_year - 15), end_val, 15),
        })
    return result


def format_financial_rows(metrics: Dict[str, Dict[int, Optional[float]]],
                          row_definitions: List[tuple]) -> List[Dict[str, Any]]:
    current_year = max(next(iter(metrics.values())).keys()) if metrics else 0
    fiscal_years = sorted([y for y in range(current_year - 14, current_year + 1)])

    rows = []
    for metric_key, display_name, unit in row_definitions:
        series = metrics.get(metric_key, {})
        values = [series.get(fy) for fy in fiscal_years]
        rows.append({
            "metric_name": display_name,
            "unit": unit,
            "values": [{"year": fy, "value": val} for fy, val in zip(fiscal_years, values)],
        })
    return rows
