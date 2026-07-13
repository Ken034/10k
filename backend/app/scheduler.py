import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.services.company_service import fetch_and_cache_company
from app.config import settings


SP500_TICKERS = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "GOOG", "BRK.B", "UNH",
    "JNJ", "XOM", "JPM", "V", "PG", "HD", "MA", "CVX", "MRK", "ABBV",
    "PEP", "KO", "BAC", "AVGO", "TMO", "COST", "DIS", "PFE", "WMT", "ABT",
    "ACN", "ADBE", "AMD", "AMGN", "AMT", "AXP", "BA", "BMY", "C", "CAT",
    "CHTR", "CL", "CMCSA", "COF", "COP", "CRM", "CSCO", "CSX", "DHR", "DUK",
    "EMR", "F", "FDX", "GD", "GE", "GILD", "GM", "GS", "HON", "IBM",
    "INTC", "INTU", "ISRG", "KHC", "LIN", "LLY", "LMT", "LOW", "MDT", "MMM",
    "MO", "MS", "NEE", "NFLX", "NKE", "ORCL", "PM", "PYPL", "QCOM", "RTX",
    "SBUX", "SCHW", "SO", "SPG", "SYK", "T", "TMUS", "TXN", "UNP", "UPS",
    "VZ", "WBA", "WFC", "ZTS"
]


async def prefetch_popular_tickers():
    print("Starting prefetch of popular tickers...")
    async with AsyncSessionLocal() as session:
        for ticker in SP500_TICKERS:
            try:
                await fetch_and_cache_company(session, ticker)
                await asyncio.sleep(0.2)  # be polite to SEC
            except Exception as e:
                print(f"Prefetch failed for {ticker}: {e}")
    print("Prefetch complete.")


scheduler = AsyncIOScheduler()


def start_scheduler():
    if not settings.prefetch_enabled:
        return
    scheduler.add_job(prefetch_popular_tickers, CronTrigger(hour=4, minute=0), id="prefetch", replace_existing=True)
    scheduler.start()
