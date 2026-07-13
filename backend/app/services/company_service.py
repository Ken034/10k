from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Company, FinancialMetric, Filing, LLMCache
from app.models.pydantic_models import (
    CompanyProfile,
    CompanyDetailResponse,
    QualitativeSection,
    FinancialRow,
    CAGRow,
)
from app.services.sec_client import resolve_ticker, get_submissions, get_company_facts, find_latest_annual_filing_url, fetch_xbrl_instance_shares, _cik_has_annual_filings
from app.services.industry_classifier import classify_sector
from app.services.xbrl_mapper import extract_raw_metrics
from app.services.financial_calculator import (
    build_regular_metrics,
    build_banking_metrics,
    compute_cagr_table,
    format_financial_rows,
)
from app.services.yfinance_client import get_market_cap


REGULAR_ROWS = [
    ("shares_outstanding", "Weighted Avg Diluted Shares (M)", "M"),
    ("revenue", "Revenue ($M)", "$M"),
    ("operating_margin", "Operating Margin (%)", "%"),
    ("depreciation", "Depreciation ($M)", "$M"),
    ("net_profit", "Net Profit ($M)", "$M"),
    ("income_tax_rate", "Income Tax Rate (%)", "%"),
    ("net_profit_margin", "Net Profit Margin (%)", "%"),
    ("long_term_debt", "Long-Term Debt ($M)", "$M"),
    ("ppe", "Property, Plant & Equipment ($M)", "$M"),
    ("inventory", "Inventory ($M)", "$M"),
    ("return_on_capital", "Return on Capital (%)", "%"),
]

BANKING_ROWS = [
    ("shares_outstanding", "Weighted Avg Diluted Shares (M)", "M"),
    ("total_assets", "Total Assets ($M)", "$M"),
    ("loans", "Loans ($M)", "$M"),
    ("net_interest_income", "Net Interest Income ($M)", "$M"),
    ("noninterest_revenue", "Noninterest Revenue ($M)", "$M"),
    ("noninterest_expense", "Noninterest Expense ($M)", "$M"),
    ("net_profit", "Total Net Profit ($M)", "$M"),
    ("loan_loss_provision", "Loan Loss Provision ($M)", "$M"),
    ("long_term_debt", "Long-Term Debt ($M)", "$M"),
    ("return_on_assets", "Return on Assets (%)", "%"),
    ("return_on_equity", "Return on Equity (%)", "%"),
]

REGULAR_CAGR_ROWS = ["revenue", "net_profit"]
BANKING_CAGR_ROWS = ["loans", "net_interest_income", "net_profit"]


async def fetch_and_cache_company(session: AsyncSession, ticker: str) -> Optional[Company]:
    company_info = await resolve_ticker(ticker)
    if not company_info:
        return None

    cik = company_info["cik"]
    submissions = await get_submissions(cik)

    # Check if company has any 10-K or 20-F filings (public companies only)
    if not _cik_has_annual_filings(submissions):
        return None

    sic = str(submissions.get("sic", "")) if submissions.get("sic") else None
    sector_bucket = classify_sector(sic)

    company = Company(
        cik=cik,
        ticker=ticker.upper(),
        name=company_info["name"],
        sic=sic,
        sector_bucket=sector_bucket,
    )
    session.add(company)
    await session.flush()

    facts = await get_company_facts(cik)
    raw_metrics = await extract_raw_metrics(facts, sector_bucket, years=15)

    # Fallback: if shares_diluted is mostly empty, parse XBRL instance XML directly.
    # Some companies (e.g. BIDU) report shares with dimensional axes that the
    # companyfacts API strips out.
    shares = raw_metrics.get("shares_diluted", {})
    total_years = len(shares)
    filled_years = sum(1 for v in shares.values() if v is not None)
    if total_years > 0 and filled_years < total_years * 0.5:
        try:
            instance_shares = await fetch_xbrl_instance_shares(cik, submissions)
            for fy, val in instance_shares.items():
                if shares.get(fy) is None and val > 0:
                    shares[fy] = val
        except Exception:
            pass  # Silently fall back to whatever data we have

    if sector_bucket in ("banking", "insurance"):
        metrics = build_banking_metrics(raw_metrics, years=15)
        row_defs = BANKING_ROWS
        cagr_rows = BANKING_CAGR_ROWS
    else:
        metrics = build_regular_metrics(raw_metrics, years=15)
        row_defs = REGULAR_ROWS
        cagr_rows = REGULAR_CAGR_ROWS

    # Store metrics
    for metric_key, series in metrics.items():
        for fy, val in series.items():
            session.add(FinancialMetric(
                company_id=company.id,
                fiscal_year=fy,
                metric_name=metric_key,
                value=val,
                unit="USD_millions" if "shares" not in metric_key else "millions",
            ))

    # Store latest filing
    report_url = find_latest_annual_filing_url(submissions)
    recent = submissions.get("filings", {}).get("recent", {})
    latest_accession = ""
    if recent.get("form"):
        for idx, form in enumerate(recent["form"]):
            if form in ("10-K", "20-F"):
                latest_accession = recent["accessionNumber"][idx]
                session.add(Filing(
                    company_id=company.id,
                    accession_number=latest_accession,
                    form=form,
                    filing_date=datetime.strptime(recent["filingDate"][idx], "%Y-%m-%d"),
                    fiscal_year=max(metrics.get(cagr_rows[0], {}).keys()) if metrics.get(cagr_rows[0], {}) else None,
                    report_url=report_url,
                ))
                break

    await session.commit()
    return company


async def get_company_detail(session: AsyncSession, ticker: str) -> Optional[CompanyDetailResponse]:
    ticker = ticker.upper()

    # Check cache
    result = await session.execute(select(Company).where(Company.ticker == ticker))
    company = result.scalar_one_or_none()

    if company is None or company.created_at is None or (datetime.utcnow() - company.created_at) > timedelta(hours=24):
        if company is not None:
            # Delete old cached data to refresh
            await session.execute(FinancialMetric.__table__.delete().where(FinancialMetric.company_id == company.id))
            await session.execute(Filing.__table__.delete().where(Filing.company_id == company.id))
            await session.execute(LLMCache.__table__.delete().where(LLMCache.company_id == company.id))
            await session.delete(company)
            await session.commit()
        company = await fetch_and_cache_company(session, ticker)
        if company is None:
            return None

    # Load metrics
    result = await session.execute(
        select(FinancialMetric).where(FinancialMetric.company_id == company.id)
    )
    metrics_map: Dict[str, Dict[int, Optional[float]]] = {}
    for m in result.scalars().all():
        metrics_map.setdefault(m.metric_name, {})[m.fiscal_year] = m.value

    # Load qualitative
    result = await session.execute(
        select(LLMCache).where(LLMCache.company_id == company.id).order_by(LLMCache.created_at.desc())
    )
    cache = result.scalar_one_or_none()
    qualitative = QualitativeSection(
        history_and_development=cache.history if cache else "",
        mdna_analysis=cache.mdna_analysis if cache else "",
    )

    # Latest filing
    result = await session.execute(
        select(Filing).where(Filing.company_id == company.id).order_by(Filing.filing_date.desc()).limit(1)
    )
    latest_filing = result.scalar_one_or_none()

    if company.sector_bucket in ("banking", "insurance"):
        row_defs = BANKING_ROWS
        cagr_rows = BANKING_CAGR_ROWS
    else:
        row_defs = REGULAR_ROWS
        cagr_rows = REGULAR_CAGR_ROWS

    financial_table = format_financial_rows(metrics_map, row_defs)
    cagr_table = compute_cagr_table(metrics_map, cagr_rows)

    # Fetch live market cap from Yahoo Finance
    import asyncio as _asyncio
    market_cap = await _asyncio.get_event_loop().run_in_executor(
        None, get_market_cap, company.ticker
    )

    return CompanyDetailResponse(
        profile=CompanyProfile(
            cik=company.cik,
            ticker=company.ticker,
            name=company.name,
            sic=company.sic,
            sector_bucket=company.sector_bucket,
        ),
        latest_filing_date=latest_filing.filing_date.strftime("%Y-%m-%d") if latest_filing else None,
        latest_fiscal_year=latest_filing.fiscal_year if latest_filing else None,
        market_cap=market_cap,
        qualitative=qualitative,
        financial_table=[FinancialRow(**row) for row in financial_table],
        cagr_table=[CAGRow(**row) for row in cagr_table],
    )
