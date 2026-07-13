from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database import get_db
from app.models.pydantic_models import CompanyDetailResponse
from app.services.company_service import get_company_detail
from app.services.sec_client import search_companies

router = APIRouter(prefix="/api/company", tags=["company"])


@router.get("/search")
async def search_company(q: str = Query(..., min_length=1, description="Search query")):
    """Search companies by name or ticker."""
    results = await search_companies(q, limit=10)
    return {"results": results}


@router.get("/{ticker}", response_model=CompanyDetailResponse)
async def read_company(ticker: str, db: AsyncSession = Depends(get_db)):
    detail = await get_company_detail(db, ticker)
    if not detail:
        raise HTTPException(
            status_code=404,
            detail=f"No public financial data available for '{ticker.upper()}'. This may be a private company or one that doesn't file 10-K/20-F reports with the SEC."
        )
    return detail
