from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field, field_validator


class CompanyProfile(BaseModel):
    cik: str
    ticker: str
    name: str
    sic: Optional[str] = None
    sector_bucket: str  # regular | banking | insurance


class YearlyValue(BaseModel):
    year: int
    value: Optional[float] = None


class FinancialRow(BaseModel):
    metric_name: str
    values: List[YearlyValue]
    unit: Optional[str] = None


class CAGRow(BaseModel):
    metric_name: str
    cagr_5y: Optional[float] = None
    cagr_10y: Optional[float] = None
    cagr_15y: Optional[float] = None


class QualitativeSection(BaseModel):
    history_and_development: str
    mdna_analysis: str


class CompanyDetailResponse(BaseModel):
    profile: CompanyProfile
    latest_filing_date: Optional[str] = None
    latest_fiscal_year: Optional[int] = None
    market_cap: Optional[float] = None  # USD, from Yahoo Finance
    qualitative: QualitativeSection
    financial_table: List[FinancialRow]
    cagr_table: List[CAGRow]


class FilingItem(BaseModel):
    ticker: str
    name: str
    form: str
    filing_date: str
    fiscal_year: int
    accession_number: str


class DailyFilingsResponse(BaseModel):
    filings: List[FilingItem]


class MetricSeries(BaseModel):
    metric_name: str
    unit: str = "USD"
    series: Dict[int, Optional[float]]

    @field_validator("series")
    @classmethod
    def validate_years(cls, v):
        for year in v.keys():
            if year < 1950 or year > 2100:
                raise ValueError(f"Invalid fiscal year: {year}")
        return v


class FinancialDataPayload(BaseModel):
    profile: CompanyProfile
    metrics: List[MetricSeries]
