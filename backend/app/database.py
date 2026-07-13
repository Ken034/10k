from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

from app.config import settings

# SQLite async driver needs a longer timeout and WAL mode to avoid "database is locked"
# errors when concurrent requests or the background scheduler write to the same file.
_engine_kwargs = {"echo": False, "future": True}
if settings.database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"timeout": 30.0}

engine = create_async_engine(settings.database_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Enable WAL mode for SQLite so reads don't block writes
        if settings.database_url.startswith("sqlite"):
            await conn.execute(text("PRAGMA journal_mode=WAL;"))
            await conn.execute(text("PRAGMA busy_timeout=30000;"))
    if not settings.database_url.startswith("postgresql"):
        return
    async with AsyncSessionLocal() as session:
        await session.execute(text(""""
            CREATE OR REPLACE VIEW financial_pivot AS
            SELECT
                c.cik,
                c.ticker,
                c.name,
                m.metric_name,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 1 THEN m.value END) AS y1,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 2 THEN m.value END) AS y2,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 3 THEN m.value END) AS y3,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 4 THEN m.value END) AS y4,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 5 THEN m.value END) AS y5,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 6 THEN m.value END) AS y6,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 7 THEN m.value END) AS y7,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 8 THEN m.value END) AS y8,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 9 THEN m.value END) AS y9,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 10 THEN m.value END) AS y10,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 11 THEN m.value END) AS y11,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 12 THEN m.value END) AS y12,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 13 THEN m.value END) AS y13,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 14 THEN m.value END) AS y14,
                MAX(CASE WHEN m.fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE) - 15 THEN m.value END) AS y15
            FROM companies c
            JOIN financial_metrics m ON c.id = m.company_id
            GROUP BY c.id, c.cik, c.ticker, c.name, m.metric_name;
        """))
        await session.commit()
