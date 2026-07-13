import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.database import get_db
from app.models.db_models import Company, Filing
from app.models.pydantic_models import FilingItem, DailyFilingsResponse
from app.services.sec_client import get_submissions, get_recent_filings, get_ticker_mapping

router = APIRouter(prefix="/api/filings", tags=["filings"])


@router.get("/recent", response_model=DailyFilingsResponse)
async def recent_filings(days: int = 7, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Company, Filing)
        .join(Filing, Company.id == Filing.company_id)
        .where(Filing.form.in_(["10-K", "20-F"]))
        .order_by(Filing.filing_date.desc())
        .limit(100)
    )
    rows = result.all()

    if rows:
        filings = [
            FilingItem(
                ticker=company.ticker,
                name=company.name,
                form=filing.form,
                filing_date=filing.filing_date.strftime("%Y-%m-%d"),
                fiscal_year=filing.fiscal_year or filing.filing_date.year,
                accession_number=filing.accession_number,
            )
            for company, filing in rows
        ]
        return DailyFilingsResponse(filings=filings)

    # Fallback: fetch live from SEC for a small universe
    mapping = await get_ticker_mapping()
    all_items = []
    sample_tickers = list(mapping.keys())[:200]
    for ticker in sample_tickers:
        try:
            info = mapping[ticker]
            submissions = await get_submissions(info["cik"])
            recent = get_recent_filings(submissions, days=days)
            for f in recent:
                all_items.append(FilingItem(
                    ticker=ticker,
                    name=info["name"],
                    form=f["form"],
                    filing_date=f["filing_date"],
                    fiscal_year=f["fiscal_year"],
                    accession_number=f["accession_number"],
                ))
        except Exception:
            continue
        await asyncio.sleep(0.2)
        if len(all_items) >= 50:
            break

    return DailyFilingsResponse(filings=sorted(all_items, key=lambda x: x.filing_date, reverse=True)[:50])
