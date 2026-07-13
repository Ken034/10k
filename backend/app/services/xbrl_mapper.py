from typing import Dict, List, Optional, Any
from collections import defaultdict
from datetime import datetime

from app.services.exchange_rate_service import get_usd_exchange_rate


TAGS = {
    "regular": {
        "revenue": [
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
            "SalesRevenueServicesNet",
            "TotalRevenues",
            "Revenue",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ],
        "operating_income": [
            "OperatingIncomeLoss",
            "OperatingIncome",
            "IncomeLossFromOperations",
            "OperatingProfitLoss",
            "ProfitLossFromOperatingActivities",
        ],
        "depreciation_and_amortization": [
            "DepreciationAndAmortization",
            "DepreciationAndAmortisation",
            "Depreciation",
            "DepreciationDepletionAndAmortization",
            "DepreciationAmortizationAndDepletion",
            "DepreciationAndAmortisationExpense",
        ],
        "depreciation": [
            "DepreciationFromPropertyPlantAndEquipment",
            "PropertyPlantAndEquipmentDepreciationExpense",
            "Depreciation",
            "DepreciationAndAmortization",
            "DepreciationDepletionAndAmortization",
            "DepreciationAmortizationAndDepletion",
        ],
        "net_income": ["NetIncomeLoss", "NetIncome", "ProfitLoss", "ProfitLossForPeriod"],
        "income_tax_expense": [
            "IncomeTaxExpenseBenefit",
            "IncomeTaxExpense",
            "IncomeTaxExpenseBenefitContinuingOperations",
            "TaxExpense",
            "IncomeTaxExpenseContinuingOperations",
        ],
        "income_before_tax": [
            "IncomeBeforeIncomeTax",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            "ProfitLossBeforeTax",
            "ProfitLossFromContinuingOperationsBeforeTax",
        ],
        "interest_expense": [
            "InterestExpense",
            "InterestAndDebtExpense",
            "InterestExpenseOperatingAndNonoperating",
        ],
        "short_term_debt": [
            "ShortTermBorrowings",
            "ShortTermDebt",
            "DebtCurrent",
            "CurrentPortionOfLongTermDebt",
            "BorrowingsCurrent",
            "CurrentPortionOfBorrowings",
        ],
        "long_term_debt": [
            "LongTermDebt",
            "LongTermDebtNoncurrent",
            "NoncurrentPortionOfLongTermDebt",
            "BorrowingsNoncurrent",
            "NoncurrentBorrowings",
            "Borrowings",
            "LongTermDebtAndCapitalLeaseObligations",
            "LongTermDebtAndLeaseObligations",
        ],
        "ppe": [
            "PropertyPlantAndEquipmentNet",
            "PropertyPlantAndEquipmentGross",
            "PropertyPlantAndEquipment",
        ],
        "inventory": [
            "InventoryNet",
            "Inventory",
            "Inventories",
            "EnergyRelatedInventory",
            "InventoryFinishedGoodsAndWorkInProcess",
            "InventoryCrudeOilProductsAndMerchandise",
        ],
        "stockholders_equity": [
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ],
        "assets": ["Assets"],
        "shares_diluted": [
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfShareOutstandingAssumingConversion",
            "WeightedAverageNumberOfSharesOutstandingBasic",
        ],
        "eps_diluted": [
            "EarningsPerShareDiluted",
        ],
    },
    "banking": {
        "assets": ["Assets"],
        "loans": [
            "LoansAndLeasesReceivableNetReportedAmount",
            "LoansAndLeasesReceivableNet",
            "LoansReceivableNet",
            "LoansNet",
            "LoansAndLeases",
        ],
        "net_interest_income": [
            "NetInterestIncome",
            "InterestIncomeExpenseNet",
            "InterestIncomeExpenseAfterProvisionForLoanLoss",
            "RevenuesNetOfInterestExpense",
        ],
        "noninterest_income": ["NoninterestIncome"],
        "noninterest_expense": ["NoninterestExpense"],
        "loan_loss_provision": [
            "ProvisionForLoanLosses",
            "ProvisionForCreditLosses",
            "ProvisionForLoanAndLeaseLosses",
            "ProvisionForLoanLeaseAndOtherLosses",
            "ProvisionForLoanLossesExpensed",
        ],
        "net_income": ["NetIncomeLoss", "NetIncome"],
        "short_term_debt": ["ShortTermBorrowings", "ShortTermDebt", "DebtCurrent", "CurrentPortionOfLongTermDebt"],
        "long_term_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
        "stockholders_equity": [
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ],
        "shares_diluted": [
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfShareOutstandingAssumingConversion",
        ],
    },
    "insurance": {
        "assets": ["Assets"],
        "loans": [
            "LoansAndLeasesReceivableNet",
            "LoansReceivableNet",
            "LoansNet",
        ],
        "net_interest_income": ["NetInterestIncome"],
        "noninterest_income": ["NoninterestIncome"],
        "noninterest_expense": ["NoninterestExpense"],
        "loan_loss_provision": [
            "ProvisionForLoanLosses",
            "ProvisionForCreditLosses",
            "ProvisionForLoanAndLeaseLosses",
            "ProvisionForLoanLeaseAndOtherLosses",
            "ProvisionForLoanLossesExpensed",
        ],
        "net_income": ["NetIncomeLoss", "NetIncome"],
        "short_term_debt": ["ShortTermBorrowings", "ShortTermDebt", "DebtCurrent"],
        "long_term_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
        "stockholders_equity": [
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ],
        "shares_diluted": [
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfShareOutstandingAssumingConversion",
        ],
    },
}


TAG_FALLBACKS: Dict[str, Dict[str, List[str]]] = {
    "ppe": {
        "include": ["PropertyPlantAndEquipment"],
        # Tags excluded if they CONTAIN any of these
        "exclude": ["Payment", "Proceed", "Tax", "Impairment", "Repair",
                     "Maintenance", "Acquisition", "ConstructionInProgress"],
        # Tags excluded if they START with any of these (dep/amortization sub-items)
        "exclude_starts": ["AccumulatedDepreciation", "AccumulatedDepletion",
                           "AccumulatedAmortization", "Depreciation", "Depletion",
                           "Amortization"],
        "prefer": ["Net", "After"],
    },
    "inventory": {
        "include": ["Inventor"],
        "exclude": ["LIFO", "IncreaseDecrease", "Effect", "Reserve", "Adjustment",
                     "WriteDown", "Obsolescence", "Disclosure"],
        "exclude_starts": [],
        "prefer": ["Net"],
    },
    "long_term_debt": {
        "include": ["LongTermDebt"],
        "exclude": ["Maturit", "Proceed", "Repayment", "Issuance", "Interest",
                     "Fair", "Discount", "Premium", "Gain", "Loss", "Restriction"],
        "exclude_starts": [],
        "prefer": ["Noncurrent"],
    },
    "operating_income": {
        "include": ["OperatingIncome", "OperatingProfit", "IncomeFromOperation"],
        "exclude": ["Tax", "Noncontrolling", "Extraordinary", "Discontinued",
                     "Foreign", "Domestic"],
        "exclude_starts": [],
        "prefer": ["Loss"],
    },
    "short_term_debt": {
        "include": ["DebtCurrent", "ShortTermDebt", "ShortTermBorrow"],
        "exclude": ["Interest", "Fair", "Gain", "Loss"],
        "exclude_starts": [],
        "prefer": [],
    },
}


def _discover_tags(facts: Dict[str, Any], metric_name: str) -> List[str]:
    """Dynamically discover XBRL tags for a metric based on keyword patterns.
    This handles companies that use non-standard or renamed XBRL tag names."""
    config = TAG_FALLBACKS.get(metric_name)
    if not config:
        return []

    include_keywords = config.get("include", [])
    exclude_keywords = config.get("exclude", [])
    exclude_starts = config.get("exclude_starts", [])
    prefer_keywords = config.get("prefer", [])

    discovered = []
    for ns in ["us-gaap", "ifrs-full"]:
        ns_facts = facts.get("facts", {}).get(ns, {})
        for tag in ns_facts:
            tag_lower = tag.lower()
            # Must match at least one include keyword
            if not any(kw.lower() in tag_lower for kw in include_keywords):
                continue
            # Must NOT contain any exclude keyword
            if any(kw.lower() in tag_lower for kw in exclude_keywords):
                continue
            # Must NOT start with any exclude_starts keyword
            if any(tag_lower.startswith(kw.lower()) for kw in exclude_starts):
                continue
            discovered.append(tag)

    # Sort: prefer tags containing preferred keywords first
    def sort_key(t):
        t_lower = t.lower()
        score = 0
        for kw in prefer_keywords:
            if kw.lower() in t_lower:
                score -= 10
        # Prefer shorter tag names (more standard/concise)
        score += len(t)
        return score

    discovered.sort(key=sort_key)
    # Deduplicate across namespaces (same tag name from us-gaap and ifrs-full)
    seen = set()
    unique = []
    for t in discovered:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _is_annual_entry(entry: Dict[str, Any]) -> bool:
    """Return True if the entry represents an annual (FY) value."""
    frame = entry.get("frame") or ""
    # Frame explicitly quarterly (Q1-Q3) -> not annual
    if frame and any(q in frame for q in ("Q1", "Q2", "Q3")):
        return False
    # Duration facts: must span roughly a full year to be annual
    start = entry.get("start")
    end = entry.get("end")
    if start and end:
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d")
            end_dt = datetime.strptime(end, "%Y-%m-%d")
            duration_days = (end_dt - start_dt).days
            return duration_days > 300
        except ValueError:
            return False
    # Instant facts (balance sheet) without quarterly marker are treated as annual
    return True


def _entry_fiscal_year(entry: Dict[str, Any]) -> Optional[int]:
    """Determine the fiscal year the data belongs to."""
    frame = entry.get("frame") or ""
    # Frame like CY2017, FY2017, CY2017Q4, CY2017Q4I
    import re
    m = re.search(r"(?:CY|FY)(\d{4})", frame)
    if m:
        return int(m.group(1))
    end = entry.get("end")
    if end:
        try:
            return datetime.strptime(end, "%Y-%m-%d").year
        except ValueError:
            pass
    return None


def _pick_annual_entry(entries: List[Dict[str, Any]], fiscal_year: int) -> Optional[Dict[str, Any]]:
    """Pick the best annual entry for a fiscal year."""
    candidates = []
    for entry in entries:
        if not _is_annual_entry(entry):
            continue
        fy = _entry_fiscal_year(entry)
        if fy != fiscal_year:
            continue
        score = 0
        if entry.get("fp") == "FY":
            score += 100
        if entry.get("form") in ("10-K", "20-F"):
            score += 50
        try:
            filed_dt = datetime.strptime(entry.get("filed", ""), "%Y-%m-%d")
            score += filed_dt.toordinal()
        except ValueError:
            pass
        candidates.append((score, entry))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _pick_annual_value(entries: List[Dict[str, Any]], fiscal_year: int) -> Optional[float]:
    """Pick the best annual value for a fiscal year."""
    entry = _pick_annual_entry(entries, fiscal_year)
    if entry is None:
        return None
    return float(entry.get("val"))


def _get_tag_values(facts: Dict[str, Any], tag: str, unit_preferences: List[str]) -> List[Dict[str, Any]]:
    namespaces = ["us-gaap", "ifrs-full"]
    for ns in namespaces:
        ns_facts = facts.get("facts", {}).get(ns, {})
        tag_data = ns_facts.get(tag)
        if not tag_data:
            continue
        units = tag_data.get("units", {})
        for unit in unit_preferences:
            if unit in units:
                return units[unit]
    return []


def _get_all_tag_units(facts: Dict[str, Any], tag: str) -> Dict[str, List[Dict[str, Any]]]:
    """Return all available {unit: entries} for a tag across namespaces."""
    all_units: Dict[str, List[Dict[str, Any]]] = {}
    namespaces = ["us-gaap", "ifrs-full"]
    for ns in namespaces:
        ns_facts = facts.get("facts", {}).get(ns, {})
        tag_data = ns_facts.get(tag)
        if not tag_data:
            continue
        units = tag_data.get("units", {})
        for unit, entries in units.items():
            if unit not in all_units:
                all_units[unit] = entries
    return all_units


async def _extract_metric(facts: Dict[str, Any], tag_candidates: List[str], fiscal_years: List[int],
                          unit_preferences: List[str]) -> Dict[int, Optional[float]]:
    # First pass: merge values from preferred units (USD first)
    merged: Dict[int, Optional[float]] = {fy: None for fy in fiscal_years}
    for tag in tag_candidates:
        entries = _get_tag_values(facts, tag, unit_preferences)
        if not entries:
            continue
        for fy in fiscal_years:
            if merged[fy] is not None:
                continue
            val = _pick_annual_value(entries, fy)
            if val is not None:
                merged[fy] = val
        if all(v is not None for v in merged.values()):
            break

    # Second pass: if USD is missing, try to convert from local currency
    missing_years = [fy for fy in fiscal_years if merged[fy] is None]
    if missing_years:
        for tag in tag_candidates:
            all_units = _get_all_tag_units(facts, tag)
            for unit, entries in all_units.items():
                # Skip already-tried preferred units and non-currency units
                if unit in unit_preferences or unit in ("shares",):
                    continue
                # Extract currency code from unit (e.g. "EUR", "USD", "GBP")
                currency = unit.split("/")[0]
                if currency == "USD":
                    continue
                for fy in missing_years:
                    entry = _pick_annual_entry(entries, fy)
                    if entry is None:
                        continue
                    end_date = entry.get("end")
                    if not end_date:
                        continue
                    rate = await get_usd_exchange_rate(end_date, currency)
                    if rate is None:
                        continue
                    val = float(entry.get("val"))
                    merged[fy] = val * rate
            if all(merged[fy] is not None for fy in fiscal_years):
                break

    return merged


async def extract_raw_metrics(facts: Dict[str, Any], sector_bucket: str, years: int = 15) -> Dict[str, Dict[int, Optional[float]]]:
    current_year = datetime.now().year
    fiscal_years = list(range(current_year - years, current_year))

    tags = TAGS.get(sector_bucket, TAGS["regular"])
    unit_preferences = ["USD", "USD/shares"]
    share_units = ["shares", "USD/shares"]

    result = {}
    for metric_name, tag_candidates in tags.items():
        if metric_name == "shares_diluted":
            units = share_units
        elif metric_name == "eps_diluted":
            units = ["USD/shares", "USD"]
        else:
            units = unit_preferences

        result[metric_name] = await _extract_metric(facts, tag_candidates, fiscal_years, units)

        # Dynamic fallback: if hardcoded tags didn't find data, discover tags by keyword
        missing_years = [fy for fy in fiscal_years if result[metric_name].get(fy) is None]
        if missing_years and metric_name in TAG_FALLBACKS:
            discovered = _discover_tags(facts, metric_name)
            # Only try discovered tags not already in the hardcoded list
            new_tags = [t for t in discovered if t not in tag_candidates]
            if new_tags:
                fallback = await _extract_metric(facts, new_tags, fiscal_years, units)
                for fy in missing_years:
                    if result[metric_name].get(fy) is None and fallback.get(fy) is not None:
                        result[metric_name][fy] = fallback[fy]

    return result
