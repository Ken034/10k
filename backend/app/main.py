from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routers import company, filings
from app.scheduler import start_scheduler
from app.services.sec_client import get_ticker_mapping
import os


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Pre-warm ticker cache so first search is fast
    try:
        mapping = await get_ticker_mapping()
        print(f"Pre-warmed ticker cache: {len(mapping)} tickers loaded")
    except Exception as e:
        print(f"Failed to pre-warm ticker cache: {e}")
    start_scheduler()
    yield


app = FastAPI(title="SEC Financial Analyst", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(company.router)
app.include_router(filings.router)

# Serve React static files
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
