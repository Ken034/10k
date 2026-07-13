from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, Boolean, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    cik = Column(String(20), unique=True, index=True, nullable=False)
    ticker = Column(String(20), index=True)
    name = Column(String(500))
    sic = Column(String(10))
    sector_bucket = Column(String(50))  # regular | banking | insurance
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Filing(Base):
    __tablename__ = "filings"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    accession_number = Column(String(50), index=True)
    form = Column(String(20), index=True)
    filing_date = Column(DateTime(timezone=True))
    fiscal_year_end = Column(DateTime(timezone=True))
    fiscal_year = Column(Integer, index=True)
    report_url = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FinancialMetric(Base):
    __tablename__ = "financial_metrics"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    metric_name = Column(String(100), nullable=False)
    value = Column(Float)
    unit = Column(String(20))
    source_tag = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_financial_metrics_company_year_name", "company_id", "fiscal_year", "metric_name", unique=True),)


class LLMCache(Base):
    __tablename__ = "llm_cache"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    filing_accession = Column(String(50))
    history = Column(Text)
    mdna_analysis = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PrefetchQueue(Base):
    __tablename__ = "prefetch_queue"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), unique=True, nullable=False)
    status = Column(String(20), default="pending")  # pending | in_progress | done | failed
    last_run = Column(DateTime(timezone=True))
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
