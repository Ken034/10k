from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from pydantic import BaseModel
import asyncio

from app.database import get_db
from app.models.pydantic_models import CompanyDetailResponse, CompanyProfile, FinancialRow, YearlyValue, QualitativeSection
from app.services.company_service import get_company_detail
from app.services.sec_client import search_companies
from app.services.asian_stock_service import is_asian_ticker, fetch_asian_stock, search_asian_companies

router = APIRouter(prefix="/api/company", tags=["company"])


class AsianCompanyProfile(BaseModel):
    name: str
    ticker: str
    exchange: str
    currency: str


class AsianCompanyResponse(BaseModel):
    profile: AsianCompanyProfile
    market_cap: Optional[float] = None
    financial_table: List[FinancialRow]
    cagr_table: List = []
    qualitative: Optional[QualitativeSection] = None
    latest_filing_date: Optional[str] = None
    latest_fiscal_year: Optional[int] = None


@router.get("/search")
async def search_company(q: str = Query(..., min_length=1, description="Search query")):
    """Search companies by name or ticker - includes SEC, HK, and China stocks."""
    results = []
    
    # Search SEC companies
    sec_results = await search_companies(q, limit=10)
    if isinstance(sec_results, dict):
        results.extend(sec_results.get("results", []))
    elif isinstance(sec_results, list):
        results.extend(sec_results)
    
    # Always search Asian companies (by ticker or name)
    asian_results = search_asian_companies(q, limit=5)
    results.extend(asian_results)
    
    return {"results": results[:15]}


@router.get("/{ticker}")
async def read_company(ticker: str, db: AsyncSession = Depends(get_db)):
    """Get company financial data - supports SEC (US), HKEX, and China stocks."""
    
    # Check if it's an Asian stock first
    if is_asian_ticker(ticker):
        # Run blocking AKShare calls in executor to avoid blocking event loop
        data = await asyncio.get_event_loop().run_in_executor(
            None, fetch_asian_stock, ticker, 10
        )
        if data:
            # Convert to response format matching frontend expectations
            financial_rows = [
                FinancialRow(
                    metric_name=row["metric_name"],
                    values=[YearlyValue(year=v["year"], value=v["value"]) for v in row["values"]],
                    unit=row.get("unit"),
                )
                for row in data.get("financial_table", [])
            ]
            
            return {
                "profile": {
                    "cik": data["profile"]["ticker"],
                    "ticker": data["profile"]["ticker"],
                    "name": data["profile"]["name"],
                    "sic": None,
                    "sector_bucket": "regular",
                    "exchange": data["profile"]["exchange"],
                    "currency": data["profile"]["currency"],
                },
                "latest_filing_date": None,
                "latest_fiscal_year": None,
                "market_cap": data.get("market_cap"),
                "qualitative": {"history_and_development": "", "mdna_analysis": ""},
                "financial_table": [row.dict() for row in financial_rows],
                "cagr_table": [],
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=f"No financial data available for '{ticker.upper()}'. Please check the ticker format (e.g., 0700.HK for Tencent, 600519.SS for Moutai)."
            )
    
    # Otherwise, use SEC data
    detail = await get_company_detail(db, ticker)
    if not detail:
        raise HTTPException(
            status_code=404,
            detail=f"No public financial data available for '{ticker.upper()}'. This may be a private company or one that doesn't file 10-K/20-F reports with the SEC."
        )
    return detail
