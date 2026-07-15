"""Fetch financial data for HK and China stocks using AKShare and yfinance."""
import yfinance as yf
import akshare as ak
import pandas as pd
import os
import json
import psycopg
import psycopg.rows
import gc
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import threading

# Timeout for AKShare API calls (seconds)
AKSHARE_TIMEOUT = 90

# Database-backed persistent cache for China/HK stock financial data
CHINA_CACHE_TTL_DAYS = 3
_china_cache: Dict[str, Dict[str, Any]] = {}
_china_cache_lock = threading.Lock()

# Limit concurrent background AKShare fetches to avoid memory spikes
_background_fetch_semaphore = threading.Semaphore(2)
_background_fetch_in_progress: set = set()
_background_fetch_lock = threading.Lock()

# Shared thread pool for AKShare timeout calls (avoids creating many thread pools)
_akshare_thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="akshare")

# Shared thread pool for background fetches
_background_thread_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="asian_bg")

# Database connection from settings (sync psycopg2 connection for cache)
def _get_db_url() -> str:
    """Get database URL from settings."""
    try:
        from app.config import settings
        url = settings.database_url
        # Convert async URL to sync URL for psycopg2
        return url.replace("postgresql+asyncpg://", "postgresql://").replace("sqlite+aiosqlite:///", "sqlite:///")
    except Exception:
        pass
    # Fallback
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return f"sqlite:///{os.path.join(backend_dir, 'app.db')}"


def _is_postgres() -> bool:
    """Check if using PostgreSQL."""
    return _get_db_url().startswith("postgresql")


def _get_db_conn():
    """Get synchronous database connection."""
    db_url = _get_db_url()
    if db_url.startswith("postgresql"):
        conn = psycopg.connect(db_url, autocommit=False)
        return conn
    else:
        # SQLite fallback
        import sqlite3 as _sqlite3
        db_path = db_url.replace("sqlite:///", "")
        if not os.path.isabs(db_path):
            backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(backend_dir, db_path)
        conn = _sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        return conn


def _init_china_cache_table() -> None:
    """Create the cache table if it doesn't exist."""
    try:
        with _get_db_conn() as conn:
            cur = conn.cursor()
            if _is_postgres():
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS asian_stock_cache (
                        id SERIAL PRIMARY KEY,
                        ticker VARCHAR(20) UNIQUE NOT NULL,
                        name VARCHAR(500),
                        exchange VARCHAR(50),
                        currency VARCHAR(10),
                        market_cap REAL,
                        financial_data TEXT,
                        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            else:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS asian_stock_cache (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticker VARCHAR(20) UNIQUE NOT NULL,
                        name VARCHAR(500),
                        exchange VARCHAR(50),
                        currency VARCHAR(10),
                        market_cap REAL,
                        financial_data TEXT,
                        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_asian_stock_cache_ticker ON asian_stock_cache(ticker)")
            conn.commit()
    except Exception as e:
        print(f"Failed to init asian_stock_cache table: {e}")


def _load_cache_from_db() -> None:
    """Load all cached China stock data from database on startup."""
    global _china_cache
    try:
        with _get_db_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT ticker, name, exchange, currency, market_cap, financial_data, cached_at FROM asian_stock_cache"
            )
            rows = cur.fetchall()
            with _china_cache_lock:
                for row in rows:
                    ticker, name, exchange, currency, market_cap, financial_data, cached_at = row
                    try:
                        if isinstance(cached_at, str):
                            cached_dt = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
                        else:
                            cached_dt = cached_at
                    except Exception:
                        cached_dt = datetime.utcnow()
                    age = datetime.utcnow() - cached_dt.replace(tzinfo=None)
                    if age < timedelta(days=CHINA_CACHE_TTL_DAYS):
                        _china_cache[ticker] = {
                            "data": {
                                "profile": {
                                    "name": name,
                                    "ticker": ticker,
                                    "exchange": exchange,
                                    "currency": currency,
                                },
                                "market_cap": market_cap,
                                "financial_table": json.loads(financial_data) if financial_data else [],
                            },
                            "cached_at": cached_dt.replace(tzinfo=None),
                        }
                    else:
                        if _is_postgres():
                            cur.execute("DELETE FROM asian_stock_cache WHERE ticker = %s", (ticker,))
                        else:
                            cur.execute("DELETE FROM asian_stock_cache WHERE ticker = ?", (ticker,))
                        conn.commit()
    except Exception as e:
        print(f"Failed to load cache from DB: {e}")


def _save_cache_to_db(ticker: str, data: Dict[str, Any]) -> None:
    """Save cached stock data to database."""
    try:
        profile = data.get("profile", {})
        financial_json = json.dumps(data.get("financial_table", []))
        with _get_db_conn() as conn:
            cur = conn.cursor()
            if _is_postgres():
                cur.execute("""
                    INSERT INTO asian_stock_cache (ticker, name, exchange, currency, market_cap, financial_data, cached_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(ticker) DO UPDATE SET
                        name = EXCLUDED.name,
                        exchange = EXCLUDED.exchange,
                        currency = EXCLUDED.currency,
                        market_cap = EXCLUDED.market_cap,
                        financial_data = EXCLUDED.financial_data,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    ticker,
                    profile.get("name"),
                    profile.get("exchange"),
                    profile.get("currency"),
                    data.get("market_cap"),
                    financial_json,
                ))
            else:
                cur.execute("""
                    INSERT INTO asian_stock_cache (ticker, name, exchange, currency, market_cap, financial_data, cached_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(ticker) DO UPDATE SET
                        name = excluded.name,
                        exchange = excluded.exchange,
                        currency = excluded.currency,
                        market_cap = excluded.market_cap,
                        financial_data = excluded.financial_data,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    ticker,
                    profile.get("name"),
                    profile.get("exchange"),
                    profile.get("currency"),
                    data.get("market_cap"),
                    financial_json,
                ))
            conn.commit()
    except Exception as e:
        print(f"Failed to save cache to DB for {ticker}: {e}")


# Initialize table and load cache on module import
_init_china_cache_table()
_load_cache_from_db()


# Exchange detection patterns
HK_SUFFIX = ".HK"
SH_SUFFIX = ".SS"  # Shanghai
SZ_SUFFIX = ".SZ"  # Shenzhen

# Years of data to fetch
DISPLAY_YEARS = 10


def is_hk_ticker(ticker: str) -> bool:
    """Check if ticker is a HK stock (e.g., 0700.HK or 00700)."""
    ticker_upper = ticker.upper()
    if ticker_upper.endswith(HK_SUFFIX):
        return True
    if len(ticker) == 5 and ticker.isdigit():
        return True
    return False


def is_china_ticker(ticker: str) -> bool:
    """Check if ticker is a China A-share (e.g., 600519.SS, 600519, 000858.SZ, 000858)."""
    ticker_upper = ticker.upper()
    if ticker_upper.endswith(SH_SUFFIX) or ticker_upper.endswith(SZ_SUFFIX):
        return True
    if len(ticker) == 6 and ticker.isdigit():
        if ticker.startswith(("6", "0", "3")):
            return True
    return False


def is_asian_ticker(ticker: str) -> bool:
    """Check if ticker is HK or China stock."""
    return is_hk_ticker(ticker) or is_china_ticker(ticker)


def normalize_ticker(ticker: str) -> str:
    """Normalize ticker to yfinance format (e.g., 0700.HK, 2513.HK, 600519.SS).
    
    yfinance expects 4-digit HK tickers:
    - 0700.HK for Tencent (code 700, padded to 4 digits)
    - 2513.HK for Z.AI (code 2513, exactly 4 digits)
    - 9988.HK for Alibaba (code 9988, exactly 4 digits)
    """
    ticker_upper = ticker.upper()
    if ticker_upper.endswith(".HK"):
        # yfinance uses 4-digit format for HK stocks
        code = ticker_upper.replace(".HK", "")
        # Convert to int and back to 4-digit padded string
        try:
            num = int(code)
            return f"{num:04d}.HK"
        except ValueError:
            return ticker_upper
    if ticker_upper.endswith((".SS", ".SZ")):
        return ticker_upper
    if ticker.isdigit():
        if len(ticker) == 5:
            # HK stock - format as 4 digits
            try:
                num = int(ticker)
                return f"{num:04d}{HK_SUFFIX}"
            except ValueError:
                return f"{ticker}{HK_SUFFIX}"
        elif len(ticker) == 6:
            if ticker.startswith("6"):
                return f"{ticker}{SH_SUFFIX}"
            else:
                return f"{ticker}{SZ_SUFFIX}"
    return ticker_upper


def get_hk_code(ticker: str) -> str:
    """Get HK stock code (5 digits) for AKShare."""
    ticker_upper = ticker.upper()
    if ticker_upper.endswith(HK_SUFFIX):
        code = ticker_upper.replace(HK_SUFFIX, "")
    else:
        code = ticker
    # Pad to 5 digits
    return code.zfill(5)


def get_exchange_name(ticker: str) -> str:
    """Get exchange name for display."""
    ticker_upper = ticker.upper()
    if ticker_upper.endswith(HK_SUFFIX) or (len(ticker) == 5 and ticker.isdigit()):
        return "HKEX"
    elif ticker_upper.endswith(SH_SUFFIX) or (len(ticker) == 6 and ticker.isdigit() and ticker.startswith("6")):
        return "Shanghai"
    elif ticker_upper.endswith(SZ_SUFFIX) or (len(ticker) == 6 and ticker.isdigit() and ticker.startswith(("0", "3"))):
        return "Shenzhen"
    return "Unknown"


def get_currency(ticker: str) -> str:
    """Get currency for the exchange."""
    exchange = get_exchange_name(ticker)
    if exchange == "HKEX":
        return "HKD"
    elif exchange in ("Shanghai", "Shenzhen"):
        return "CNY"
    return "USD"


def _to_millions(val):
    """Convert value to millions."""
    if val is None or (isinstance(val, float) and val != val):  # NaN check
        return None
    return round(float(val) / 1_000_000, 2)


def _safe_float(val):
    """Safely convert to float, handling None and NaN."""
    if val is None:
        return None
    if isinstance(val, float) and val != val:  # NaN
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def is_financial_industry(company_name: str, yfinance_info: dict = None) -> bool:
    """Detect if company is a bank or insurance company.
    
    Args:
        company_name: Company name to check
        yfinance_info: Optional yfinance info dict with 'industry' field
    
    Returns:
        True if company is in banking or insurance industry
    """
    # Check yfinance industry field
    if yfinance_info:
        industry = (yfinance_info.get("industry") or "").lower()
        sector = (yfinance_info.get("sector") or "").lower()
        if any(kw in industry for kw in ["bank", "insurance", "diversified financial"]):
            return True
        if "financial services" in sector and any(kw in industry for kw in ["bank", "insurance", "credit"]):
            return True
    
    # Check company name keywords
    name_lower = company_name.lower()
    financial_keywords = [
        "bank", "insurance", "insurer", "assurance",
        "银行", "保险", "信托", "金融",  # Chinese keywords
    ]
    if any(kw in name_lower for kw in financial_keywords):
        return True
    
    return False


def _init_regular_metrics() -> Dict[str, Dict[int, Optional[float]]]:
    """Initialize metrics dict for regular (non-financial) companies."""
    return {
        "shares_outstanding": {},
        "revenue": {},
        "operating_margin": {},
        "depreciation": {},
        "income_tax_rate": {},
        "net_profit_margin": {},
        "long_term_debt": {},
        "ppe": {},
        "inventory": {},
        "return_on_capital": {},
    }


def _init_banking_metrics() -> Dict[str, Dict[int, Optional[float]]]:
    """Initialize metrics dict for banking/insurance companies."""
    return {
        "shares_outstanding": {},
        "total_assets": {},
        "loans": {},
        "net_interest_income": {},
        "noninterest_revenue": {},
        "noninterest_expense": {},
        "net_profit": {},
        "loan_loss_provision": {},
        "long_term_debt": {},
        "return_on_assets": {},
        "return_on_equity": {},
    }


# HK stock metric mappings (Chinese to English)
HK_INCOME_MAP = {
    "营业额": "revenue",           # Revenue/Turnover
    "营运支出": "operating_expense",  # Operating Expenses
    "毛利": "gross_profit",        # Gross Profit
    "税项": "income_tax",          # Income Tax
    "股东应占溢利": "net_income",   # Net Income (attributable to shareholders)
    "除税前溢利": "profit_before_tax",  # Profit Before Tax
    "经营溢利": "operating_income", # Operating Profit
}

HK_BALANCE_MAP = {
    "固定资产": "ppe",             # PPE (Fixed Assets)
    "存货": "inventory",           # Inventory
    "净资产": "net_assets",        # Net Assets
    "长期债务": "long_term_debt",  # Long Term Debt
}

HK_CASHFLOW_MAP = {
    "加:折旧及摊销": "depreciation",  # Depreciation & Amortization
}


def fetch_hk_stock_akshare(ticker: str, years: int = DISPLAY_YEARS) -> Optional[Dict[str, Any]]:
    """Fetch HK stock data using AKShare (10+ years of data) with caching."""
    hk_code = get_hk_code(ticker)
    normalized = normalize_ticker(ticker)

    # Check cache first
    cached = _get_asian_cache(normalized)
    if cached:
        print(f"Returning cached data for {normalized}")
        return cached

    try:
        # Get company info from yfinance
        stock = yf.Ticker(normalized)
        info = stock.info
        if not info or not info.get("longName"):
            return None

        profile = {
            "name": info.get("longName") or info.get("shortName", normalized),
            "ticker": normalized,
            "exchange": "HKEX",
            "currency": info.get("currency", "HKD"),
        }
        market_cap = info.get("marketCap")
        
        # Detect if this is a financial industry company
        is_financial = is_financial_industry(profile["name"], info)
        if is_financial:
            print(f"Detected {normalized} as financial industry, using banking metrics")

        # Initialize metrics storage based on industry
        if is_financial:
            metrics = _init_banking_metrics()
        else:
            metrics = _init_regular_metrics()

        # Fetch income statement from AKShare
        try:
            income_df = ak.stock_financial_hk_report_em(stock=hk_code, symbol='利润表', indicator='年度')
            income_df['REPORT_DATE'] = pd.to_datetime(income_df['REPORT_DATE'])
            income_df['year'] = income_df['REPORT_DATE'].dt.year
            income_pivot = income_df.pivot_table(index='STD_ITEM_NAME', columns='year', values='AMOUNT', aggfunc='first')

            # Get years available
            available_years = sorted(income_pivot.columns, reverse=True)[:years]

            for year in available_years:
                if is_financial:
                    # Banking/Insurance metrics extraction
                    # Net Interest Income
                    nii = None
                    for key in ["利息净收入", "净利息收入"]:
                        if key in income_pivot.index:
                            nii = _safe_float(income_pivot.loc[key, year])
                            if nii is not None:
                                break
                    metrics["net_interest_income"][year] = _to_millions(nii)
                    
                    # Noninterest Revenue (fees, commissions, trading income)
                    nir = None
                    for key in ["手续费及佣金净收入", "非利息收入", "其他经营收入"]:
                        if key in income_pivot.index:
                            nir = _safe_float(income_pivot.loc[key, year])
                            if nir is not None:
                                break
                    metrics["noninterest_revenue"][year] = _to_millions(nir)
                    
                    # Noninterest Expense (operating expenses)
                    nie = None
                    for key in ["营业支出", "营运支出", "业务及管理费"]:
                        if key in income_pivot.index:
                            nie = _safe_float(income_pivot.loc[key, year])
                            if nie is not None:
                                break
                    metrics["noninterest_expense"][year] = _to_millions(nie)
                    
                    # Net Profit
                    net_income = None
                    if "股东应占溢利" in income_pivot.index:
                        net_income = _safe_float(income_pivot.loc["股东应占溢利", year])
                    elif "除税后溢利" in income_pivot.index:
                        net_income = _safe_float(income_pivot.loc["除税后溢利", year])
                    metrics["net_profit"][year] = _to_millions(net_income)
                    
                    # Loan Loss Provision (from income statement)
                    llp = None
                    for key in ["贷款减值准备", "贷款损失准备", "信用减值损失", "资产减值损失"]:
                        if key in income_pivot.index:
                            llp = _safe_float(income_pivot.loc[key, year])
                            if llp is not None:
                                break
                    metrics["loan_loss_provision"][year] = _to_millions(llp)
                else:
                    # Regular company metrics extraction
                    # Revenue
                    if "营业额" in income_pivot.index:
                        val = income_pivot.loc["营业额", year]
                        metrics["revenue"][year] = _to_millions(val)

                    # Net Income
                    net_income = None
                    if "股东应占溢利" in income_pivot.index:
                        net_income = _safe_float(income_pivot.loc["股东应占溢利", year])
                    elif "除税后溢利" in income_pivot.index:
                        net_income = _safe_float(income_pivot.loc["除税后溢利", year])

                    # Operating Income for margin calculation
                    op_income = None
                    if "经营溢利" in income_pivot.index:
                        op_income = _safe_float(income_pivot.loc["经营溢利", year])

                    # Revenue for margin calculation
                    revenue_val = _safe_float(income_pivot.loc["营业额", year]) if "营业额" in income_pivot.index else None

                    # Operating margin = Operating Income / Revenue * 100
                    if op_income and revenue_val and revenue_val > 0:
                        metrics["operating_margin"][year] = round(op_income / revenue_val * 100, 2)

                    # Income tax rate
                    tax_val = None
                    if "税项" in income_pivot.index:
                        tax_val = _safe_float(income_pivot.loc["税项", year])
                    pre_tax = None
                    if "除税前溢利" in income_pivot.index:
                        pre_tax = _safe_float(income_pivot.loc["除税前溢利", year])
                    if tax_val is not None and pre_tax and pre_tax > 0:
                        metrics["income_tax_rate"][year] = round(tax_val / pre_tax * 100, 2)

                    # Net profit margin
                    if net_income and revenue_val and revenue_val > 0:
                        metrics["net_profit_margin"][year] = round(net_income / revenue_val * 100, 2)

        except Exception as e:
            print(f"HK income fetch error: {e}")

        # Fetch balance sheet from AKShare
        try:
            balance_df = ak.stock_financial_hk_report_em(stock=hk_code, symbol='资产负债表', indicator='年度')
            balance_df['REPORT_DATE'] = pd.to_datetime(balance_df['REPORT_DATE'])
            balance_df['year'] = balance_df['REPORT_DATE'].dt.year
            balance_pivot = balance_df.pivot_table(index='STD_ITEM_NAME', columns='year', values='AMOUNT', aggfunc='first')

            # Determine which years to process based on available data
            year_keys = metrics["net_interest_income"].keys() if is_financial else metrics["revenue"].keys()
            
            for year in year_keys:
                if is_financial:
                    # Banking balance sheet metrics
                    # Total Assets
                    total_assets = None
                    for key in ["总资产", "资产总计"]:
                        if key in balance_pivot.index:
                            total_assets = _safe_float(balance_pivot.loc[key, year])
                            if total_assets is not None:
                                break
                    metrics["total_assets"][year] = _to_millions(total_assets)
                    
                    # Loans (customer loans)
                    loans = None
                    for key in ["客户贷款", "发放贷款及垫款", "贷款"]:
                        if key in balance_pivot.index:
                            loans = _safe_float(balance_pivot.loc[key, year])
                            if loans is not None:
                                break
                    metrics["loans"][year] = _to_millions(loans)
                    
                    # Long-term debt (borrowings for banks)
                    ltd = None
                    for debt_key in ["已发行债务证券", "长期借贷", "银行借贷(非流动)", "应付债券"]:
                        if debt_key in balance_pivot.index:
                            val = _safe_float(balance_pivot.loc[debt_key, year])
                            if val is not None and val > 0:
                                if ltd is None:
                                    ltd = 0
                                ltd += val
                    metrics["long_term_debt"][year] = _to_millions(ltd)
                    
                    # Equity for ROE calculation
                    equity = None
                    for eq_key in ["股东权益", "总权益", "净资产", "归属于母公司股东权益"]:
                        if eq_key in balance_pivot.index:
                            equity = _safe_float(balance_pivot.loc[eq_key, year])
                            if equity is not None:
                                break
                    
                    # Net income for ROA/ROE
                    net_income_val = None
                    if "股东应占溢利" in income_pivot.index:
                        net_income_val = _safe_float(income_pivot.loc["股东应占溢利", year])
                    elif "除税后溢利" in income_pivot.index:
                        net_income_val = _safe_float(income_pivot.loc["除税后溢利", year])
                    
                    # Return on Assets = Net Income / Total Assets * 100
                    if net_income_val and total_assets and total_assets > 0:
                        metrics["return_on_assets"][year] = round(net_income_val / total_assets * 100, 2)
                    
                    # Return on Equity = Net Income / Equity * 100
                    if net_income_val and equity and equity > 0:
                        metrics["return_on_equity"][year] = round(net_income_val / equity * 100, 2)
                else:
                    # Regular company balance sheet metrics
                    # PPE
                    if "固定资产" in balance_pivot.index:
                        metrics["ppe"][year] = _to_millions(balance_pivot.loc["固定资产", year])

                    # Inventory
                    if "存货" in balance_pivot.index:
                        metrics["inventory"][year] = _to_millions(balance_pivot.loc["存货", year])

                    # Long-term debt (look for various Chinese names)
                    ltd = None
                    for debt_key in ["其他金融负债(非流动)", "长期借贷", "长期债务", "银行借贷(非流动)", "融资租赁负债(非流动)"]:
                        if debt_key in balance_pivot.index:
                            val = _safe_float(balance_pivot.loc[debt_key, year])
                            if val is not None and val > 0:
                                if ltd is None:
                                    ltd = 0
                                ltd += val
                    metrics["long_term_debt"][year] = _to_millions(ltd) if ltd else None

                    # Net assets/equity for return on capital calculation
                    equity = None
                    for eq_key in ["股东权益", "总权益", "净资产"]:
                        if eq_key in balance_pivot.index:
                            equity = _safe_float(balance_pivot.loc[eq_key, year])
                            if equity is not None:
                                break

                    # Calculate return on capital
                    net_income_val = None
                    if "股东应占溢利" in income_pivot.index:
                        net_income_val = _safe_float(income_pivot.loc["股东应占溢利", year])

                    if net_income_val and equity and ltd is not None and (equity + max(ltd, 0)) > 0:
                        metrics["return_on_capital"][year] = round(net_income_val / (equity + max(ltd, 0)) * 100, 2)
                    elif net_income_val and equity and equity > 0:
                        metrics["return_on_capital"][year] = round(net_income_val / equity * 100, 2)

        except Exception as e:
            print(f"HK balance fetch error: {e}")

        # Fetch cash flow from AKShare for depreciation (only for non-financial)
        if not is_financial:
            try:
                cf_df = ak.stock_financial_hk_report_em(stock=hk_code, symbol='现金流量表', indicator='年度')
                cf_df['REPORT_DATE'] = pd.to_datetime(cf_df['REPORT_DATE'])
                cf_df['year'] = cf_df['REPORT_DATE'].dt.year
                cf_pivot = cf_df.pivot_table(index='STD_ITEM_NAME', columns='year', values='AMOUNT', aggfunc='first')

                for year in metrics["revenue"].keys():
                    if "加:折旧及摊销" in cf_pivot.index:
                        metrics["depreciation"][year] = _to_millions(cf_pivot.loc["加:折旧及摊销", year])

            except Exception as e:
                print(f"HK cashflow fetch error: {e}")

        # Get diluted shares from yfinance (AKShare doesn't have this easily)
        primary_metric = "net_interest_income" if is_financial else "revenue"
        try:
            income_yf = stock.financials
            if income_yf is not None and "Diluted Average Shares" in income_yf.index:
                for date in income_yf.columns:
                    year = date.year
                    if year in metrics[primary_metric]:
                        shares = income_yf.loc["Diluted Average Shares", date]
                        if shares and shares > 0:
                            metrics["shares_outstanding"][year] = round(shares / 1_000_000, 2)
        except Exception:
            pass

        # Ensure all metrics have the same years (pad with None for missing years)
        all_years = sorted(metrics[primary_metric].keys())
        for metric_key in metrics:
            for year in all_years:
                if year not in metrics[metric_key]:
                    metrics[metric_key][year] = None

        # Convert metrics to financial table format
        financial_table = _metrics_to_table(metrics, is_financial=is_financial)

        # Free memory from large DataFrames
        try:
            del income_df, balance_pivot, cf_pivot
        except Exception:
            pass
        gc.collect()

        if not financial_table:
            return None

        result = {
            "profile": profile,
            "market_cap": market_cap,
            "financial_table": financial_table,
        }

        # Cache the result
        _set_asian_cache(normalized, result)
        return result

    except Exception as e:
        print(f"Error fetching HK stock {hk_code}: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        # Ensure DataFrames are freed even on error
        try:
            del income_df, balance_pivot, cf_pivot
        except Exception:
            pass
        gc.collect()


def get_china_code(ticker: str) -> str:
    """Get China stock code for AKShare (sh600519 or sz000858)."""
    ticker_upper = ticker.upper()
    if ticker_upper.endswith(SH_SUFFIX):
        code = ticker_upper.replace(SH_SUFFIX, "")
        return f"sh{code}"
    elif ticker_upper.endswith(SZ_SUFFIX):
        code = ticker_upper.replace(SZ_SUFFIX, "")
        return f"sz{code}"
    # Pure numeric
    if len(ticker) == 6 and ticker.isdigit():
        if ticker.startswith("6"):
            return f"sh{ticker}"
        else:
            return f"sz{ticker}"
    return ticker


def _get_asian_cache(ticker: str) -> Optional[Dict[str, Any]]:
    """Get cached Asian stock data if not expired."""
    with _china_cache_lock:
        entry = _china_cache.get(ticker)
        if entry:
            age = datetime.utcnow() - entry.get("cached_at", datetime.utcnow())
            if age < timedelta(days=CHINA_CACHE_TTL_DAYS):
                # Move to end to mark as recently used
                _china_cache[ticker] = _china_cache.pop(ticker)
                return entry.get("data")
            else:
                del _china_cache[ticker]
        return None


def _set_asian_cache(ticker: str, data: Dict[str, Any]) -> None:
    """Cache Asian stock data in memory and in SQLite."""
    with _china_cache_lock:
        # Limit in-memory cache to ~100 tickers to avoid unbounded memory growth
        MAX_MEMORY_CACHE = 100
        while len(_china_cache) >= MAX_MEMORY_CACHE:
            # Remove oldest (first inserted) entry
            oldest = next(iter(_china_cache))
            del _china_cache[oldest]
        _china_cache[ticker] = {
            "data": data,
            "cached_at": datetime.utcnow(),
        }
    _save_cache_to_db(ticker, data)


def _akshare_with_timeout(func, *args, timeout=AKSHARE_TIMEOUT, **kwargs):
    """Call AKShare function with timeout using shared thread pool."""
    future = _akshare_thread_pool.submit(func, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        print(f"AKShare call timed out after {timeout}s")
        return None


def fetch_china_stock_akshare(ticker: str, years: int = DISPLAY_YEARS, timeout: int = AKSHARE_TIMEOUT) -> Optional[Dict[str, Any]]:
    """Fetch China A-share data using AKShare (10+ years of data) with caching."""
    china_code = get_china_code(ticker)
    normalized = normalize_ticker(ticker)

    # Check cache first
    cached = _get_asian_cache(normalized)
    if cached:
        print(f"Returning cached data for {normalized}")
        return cached

    try:
        # Get company info from yfinance
        stock = yf.Ticker(normalized)
        info = stock.info
        if not info or not info.get("longName"):
            return None

        profile = {
            "name": info.get("longName") or info.get("shortName", normalized),
            "ticker": normalized,
            "exchange": get_exchange_name(ticker),
            "currency": info.get("currency", "CNY"),
        }
        market_cap = info.get("marketCap")
        
        # Detect if this is a financial industry company
        is_financial = is_financial_industry(profile["name"], info)
        if is_financial:
            print(f"Detected {normalized} as financial industry, using banking metrics")

        # Fetch income statement and balance sheet concurrently
        def fetch_income():
            return _akshare_with_timeout(ak.stock_financial_report_sina, stock=china_code, symbol="利润表", timeout=timeout)

        def fetch_balance():
            return _akshare_with_timeout(ak.stock_financial_report_sina, stock=china_code, symbol="资产负债表", timeout=timeout)

        print(f"Fetching AKShare financial reports for {china_code} (timeout={timeout}s)...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            income_future = executor.submit(fetch_income)
            balance_future = executor.submit(fetch_balance)
            income_df = income_future.result()
            balance_df = balance_future.result()

        # Initialize metrics based on industry
        if is_financial:
            metrics = _init_banking_metrics()
        else:
            metrics = _init_regular_metrics()

        # Process income statement
        if income_df is not None:
            try:
                income_df['year'] = income_df['报告日'].astype(str).str[:4].astype(int)
                income_df['month'] = income_df['报告日'].astype(str).str[4:6]
                annual = income_df[income_df['month'] == '12'].copy()
                annual = annual.sort_values('year', ascending=False).head(years)

                for _, row in annual.iterrows():
                    year = int(row['year'])
                    
                    if is_financial:
                        # Banking metrics from income statement
                        # Net Interest Income (Sina uses 净利息收入)
                        nii = _safe_float(row.get('净利息收入'))
                        if nii is None:
                            nii = _safe_float(row.get('利息净收入'))
                        metrics["net_interest_income"][year] = _to_millions(nii)
                        
                        # Noninterest Revenue (fees, commissions)
                        nir = _safe_float(row.get('手续费及佣金净收入'))
                        if nir is None:
                            nir = _safe_float(row.get('投资收益'))
                        metrics["noninterest_revenue"][year] = _to_millions(nir)
                        
                        # Noninterest Expense (Sina uses 业务及管理费用)
                        nie = _safe_float(row.get('业务及管理费用'))
                        if nie is None:
                            nie = _safe_float(row.get('业务及管理费'))
                        if nie is None:
                            nie = _safe_float(row.get('营业支出'))
                        metrics["noninterest_expense"][year] = _to_millions(nie)
                        
                        # Net Profit
                        net_income = _safe_float(row.get('净利润'))
                        metrics["net_profit"][year] = _to_millions(net_income)
                        
                        # Loan Loss Provision
                        llp = _safe_float(row.get('资产减值损失'))
                        if llp is None:
                            llp = _safe_float(row.get('信用减值损失'))
                        metrics["loan_loss_provision"][year] = _to_millions(llp)
                    else:
                        # Regular company metrics
                        rev = _safe_float(row.get('营业总收入'))
                        metrics["revenue"][year] = _to_millions(rev)

                        # Operating margin
                        op_profit = _safe_float(row.get('营业利润'))
                        if rev and op_profit and rev > 0:
                            metrics["operating_margin"][year] = round(op_profit / rev * 100, 2)

                        # Income tax rate
                        tax = _safe_float(row.get('所得税费用'))
                        profit_before_tax = _safe_float(row.get('利润总额'))
                        if tax is not None and profit_before_tax and profit_before_tax > 0:
                            metrics["income_tax_rate"][year] = round(tax / profit_before_tax * 100, 2)

                        # Net profit margin
                        net_income = _safe_float(row.get('净利润'))
                        if rev and net_income and rev > 0:
                            metrics["net_profit_margin"][year] = round(net_income / rev * 100, 2)
            except Exception as e:
                print(f"China income processing error: {e}")

        # Process balance sheet
        if balance_df is not None:
            try:
                balance_df['year'] = balance_df['报告日'].astype(str).str[:4].astype(int)
                balance_df['month'] = balance_df['报告日'].astype(str).str[4:6]
                annual_bs = balance_df[balance_df['month'] == '12'].copy()
                annual_bs_desc = annual_bs.sort_values('year', ascending=False)
                
                # Take years+1 for depreciation calculation (YoY change needs N+1 rows)
                annual_bs_extended = annual_bs_desc.head(years + 1)
                
                # Calculate depreciation from accumulated depreciation change
                # 累计折旧 = Accumulated Depreciation; annual depreciation = YoY change
                annual_bs_asc = annual_bs_extended.sort_values('year', ascending=True)
                if '累计折旧' in annual_bs_asc.columns:
                    annual_bs_asc['accum_dep'] = annual_bs_asc['累计折旧'].apply(_safe_float)
                    annual_bs_asc['dep_change'] = annual_bs_asc['accum_dep'].diff()
                    for _, row in annual_bs_asc.iterrows():
                        year = int(row['year'])
                        dep = row.get('dep_change')
                        if dep is not None and not pd.isna(dep) and dep > 0:
                            metrics["depreciation"][year] = _to_millions(dep)

                # Process other balance sheet items (only 'years' rows)
                for _, row in annual_bs_desc.head(years).iterrows():
                    year = int(row['year'])
                    
                    if is_financial:
                        # Banking balance sheet metrics
                        # Total Assets
                        total_assets = _safe_float(row.get('资产总计'))
                        metrics["total_assets"][year] = _to_millions(total_assets)
                        
                        # Loans (customer loans)
                        loans = _safe_float(row.get('发放贷款及垫款'))
                        metrics["loans"][year] = _to_millions(loans)
                        
                        # Long-term debt (borrowings/bonds for banks)
                        ltd = _safe_float(row.get('应付债券'))
                        if ltd is None:
                            ltd = _safe_float(row.get('长期借款'))
                        metrics["long_term_debt"][year] = _to_millions(ltd)
                        
                        # Equity for ROE calculation (Sina uses different names)
                        equity = _safe_float(row.get('归属于母公司股东的权益'))
                        if equity is None:
                            equity = _safe_float(row.get('所有者权益(或股东权益)合计'))
                        if equity is None:
                            equity = _safe_float(row.get('归属于母公司股东权益合计'))
                        
                        # Net income for ROA/ROE
                        net_income_val = metrics["net_profit"].get(year)
                        if net_income_val is not None:
                            net_income_val = net_income_val * 1_000_000  # Convert back from millions
                        
                        # Return on Assets = Net Income / Total Assets * 100
                        if net_income_val and total_assets and total_assets > 0:
                            metrics["return_on_assets"][year] = round(net_income_val / total_assets * 100, 2)
                        
                        # Return on Equity = Net Income / Equity * 100
                        if net_income_val and equity and equity > 0:
                            metrics["return_on_equity"][year] = round(net_income_val / equity * 100, 2)
                    else:
                        # Regular company balance sheet metrics
                        # PPE (Net)
                        ppe = _safe_float(row.get('固定资产净额'))
                        metrics["ppe"][year] = _to_millions(ppe)

                        # Inventory
                        inv = _safe_float(row.get('存货'))
                        metrics["inventory"][year] = _to_millions(inv)

                        # Long-term debt - try multiple possible column names
                        ltd = _safe_float(row.get('长期借款'))
                        if ltd is None:
                            ltd = _safe_float(row.get('长期负债合计'))
                        if ltd is None:
                            ltd = _safe_float(row.get('非流动负债合计'))
                        metrics["long_term_debt"][year] = _to_millions(ltd)

                        # Return on capital
                        equity = _safe_float(row.get('所有者权益(或股东权益)合计'))
                        if equity is None:
                            equity = _safe_float(row.get('归属于母公司股东权益合计'))
                        
                        # Get net income from income statement for this year
                        net_income_val = None
                        if year in metrics["net_profit_margin"] and year in metrics["revenue"]:
                            npm = metrics["net_profit_margin"][year]
                            rev_val = metrics["revenue"][year]
                            if npm is not None and rev_val is not None:
                                net_income_val = rev_val * npm / 100 * 1_000_000

                        if net_income_val and equity and ltd is not None and (equity + max(ltd, 0)) > 0:
                            metrics["return_on_capital"][year] = round(net_income_val / (equity + max(ltd, 0)) * 100, 2)
                        elif net_income_val and equity and equity > 0:
                            metrics["return_on_capital"][year] = round(net_income_val / equity * 100, 2)
            except Exception as e:
                print(f"China balance processing error: {e}")

        # Get diluted shares from yfinance
        primary_metric = "net_interest_income" if is_financial else "revenue"
        try:
            income_yf = stock.financials
            if income_yf is not None and "Diluted Average Shares" in income_yf.index:
                for date in income_yf.columns:
                    year = date.year
                    if year in metrics[primary_metric]:
                        shares = income_yf.loc["Diluted Average Shares", date]
                        if shares and shares > 0:
                            metrics["shares_outstanding"][year] = round(shares / 1_000_000, 2)
        except Exception:
            pass

        # Ensure all metrics have the same years (pad with None for missing years)
        all_years = sorted(metrics[primary_metric].keys())
        for metric_key in metrics:
            for year in all_years:
                if year not in metrics[metric_key]:
                    metrics[metric_key][year] = None

        # Convert metrics to financial table format
        financial_table = _metrics_to_table(metrics, is_financial=is_financial)

        # Free memory from large DataFrames
        try:
            del income_df, balance_df
        except Exception:
            pass
        gc.collect()

        if not financial_table:
            return None

        result = {
            "profile": profile,
            "market_cap": market_cap,
            "financial_table": financial_table,
        }

        # Cache the result
        _set_asian_cache(normalized, result)
        return result

    except Exception as e:
        print(f"Error fetching China stock {china_code}: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        # Ensure DataFrames are freed even on error
        try:
            del income_df, balance_df
        except Exception:
            pass
        gc.collect()


def fetch_china_stock_yfinance(ticker: str, years: int = DISPLAY_YEARS) -> Optional[Dict[str, Any]]:
    """Fallback: Fetch China stock data using yfinance only (less data but faster)."""
    normalized = normalize_ticker(ticker)

    try:
        stock = yf.Ticker(normalized)
        info = stock.info
        if not info or not info.get("longName"):
            return None

        profile = {
            "name": info.get("longName") or info.get("shortName", normalized),
            "ticker": normalized,
            "exchange": get_exchange_name(ticker),
            "currency": info.get("currency", "CNY"),
        }
        market_cap = info.get("marketCap")
        
        # Detect if this is a financial industry company
        is_financial = is_financial_industry(profile["name"], info)

        # Initialize metrics based on industry
        if is_financial:
            metrics = _init_banking_metrics()
        else:
            metrics = _init_regular_metrics()

        # Get financials from yfinance
        income = stock.financials
        balance = stock.balance_sheet
        cashflow = stock.cashflow

        if income is None:
            return None

        # Process income statement
        for date in income.columns:
            year = date.year
            primary_key = "net_interest_income" if is_financial else "revenue"
            if len(metrics[primary_key]) >= years:
                break

            if is_financial:
                # Banking metrics
                # Net Interest Income
                for key in ["Net Interest Income", "Interest Income Net"]:
                    if key in income.index:
                        nii = _safe_float(income.loc[key, date])
                        if nii:
                            metrics["net_interest_income"][year] = _to_millions(nii)
                            break
                
                # Noninterest Revenue
                for key in ["Fee Income And Other Income", "Total Non-Interest Income"]:
                    if key in income.index:
                        nir = _safe_float(income.loc[key, date])
                        if nir:
                            metrics["noninterest_revenue"][year] = _to_millions(nir)
                            break
                
                # Noninterest Expense
                for key in ["Total Non-Interest Expense", "Total Operating Expense"]:
                    if key in income.index:
                        nie = _safe_float(income.loc[key, date])
                        if nie:
                            metrics["noninterest_expense"][year] = _to_millions(nie)
                            break
                
                # Net Profit
                net_income = _safe_float(income.loc["Net Income", date]) if "Net Income" in income.index else None
                metrics["net_profit"][year] = _to_millions(net_income)
                
                # Loan Loss Provision
                for key in ["Provision For Loan Losses", "Provision For Credit Losses"]:
                    if key in income.index:
                        llp = _safe_float(income.loc[key, date])
                        if llp:
                            metrics["loan_loss_provision"][year] = _to_millions(llp)
                            break
                
                # Shares outstanding
                if "Diluted Average Shares" in income.index:
                    shares = _safe_float(income.loc["Diluted Average Shares", date])
                    if shares and shares > 0:
                        metrics["shares_outstanding"][year] = round(shares / 1_000_000, 2)
            else:
                # Regular company metrics
                # Revenue
                for key in ["Total Revenue", "Operating Revenue"]:
                    if key in income.index:
                        rev = _safe_float(income.loc[key, date])
                        if rev:
                            metrics["revenue"][year] = _to_millions(rev)
                            break

                # Operating margin
                if "Operating Income" in income.index and metrics["revenue"].get(year):
                    op_income = _safe_float(income.loc["Operating Income", date])
                    if op_income and metrics["revenue"][year]:
                        metrics["operating_margin"][year] = round(op_income / (metrics["revenue"][year] * 1_000_000) * 100, 2)

                # Income tax rate
                tax_expense = _safe_float(income.loc["Tax Provision", date]) if "Tax Provision" in income.index else None
                pretax = _safe_float(income.loc["Pretax Income", date]) if "Pretax Income" in income.index else None
                if tax_expense and pretax and pretax > 0:
                    metrics["income_tax_rate"][year] = round(tax_expense / pretax * 100, 2)

                # Net profit margin
                net_income = _safe_float(income.loc["Net Income", date]) if "Net Income" in income.index else None
                if net_income and metrics["revenue"].get(year):
                    metrics["net_profit_margin"][year] = round(net_income / (metrics["revenue"][year] * 1_000_000) * 100, 2)

                # Shares outstanding
                if "Diluted Average Shares" in income.index:
                    shares = _safe_float(income.loc["Diluted Average Shares", date])
                    if shares and shares > 0:
                        metrics["shares_outstanding"][year] = round(shares / 1_000_000, 2)

        # Process balance sheet
        primary_metric = "net_interest_income" if is_financial else "revenue"
        if balance is not None:
            for date in balance.columns:
                year = date.year
                if year not in metrics[primary_metric]:
                    continue

                if is_financial:
                    # Banking balance sheet metrics
                    # Total Assets
                    for key in ["Total Assets"]:
                        if key in balance.index:
                            ta = _safe_float(balance.loc[key, date])
                            if ta:
                                metrics["total_assets"][year] = _to_millions(ta)
                                break
                    
                    # Loans
                    for key in ["Total Loans", "Loans And Advances", "Gross Loans"]:
                        if key in balance.index:
                            loans = _safe_float(balance.loc[key, date])
                            if loans:
                                metrics["loans"][year] = _to_millions(loans)
                                break
                    
                    # Long-term debt
                    for key in ["Long Term Debt", "Total Long-Term Debt"]:
                        if key in balance.index:
                            ltd = _safe_float(balance.loc[key, date])
                            if ltd:
                                metrics["long_term_debt"][year] = _to_millions(ltd)
                                break
                    
                    # Equity for ROE
                    equity = None
                    for eq_key in ["Total Equity", "Stockholders Equity", "Common Stock Equity"]:
                        if eq_key in balance.index:
                            equity = _safe_float(balance.loc[eq_key, date])
                            if equity:
                                break
                    
                    # Net income for ROA/ROE
                    net_income_val = metrics["net_profit"].get(year)
                    if net_income_val is not None:
                        net_income_val = net_income_val * 1_000_000  # Convert back from millions
                    
                    # Total assets for ROA
                    total_assets_val = metrics["total_assets"].get(year)
                    if total_assets_val is not None:
                        total_assets_val = total_assets_val * 1_000_000
                    
                    # Return on Assets
                    if net_income_val and total_assets_val and total_assets_val > 0:
                        metrics["return_on_assets"][year] = round(net_income_val / total_assets_val * 100, 2)
                    
                    # Return on Equity
                    if net_income_val and equity and equity > 0:
                        metrics["return_on_equity"][year] = round(net_income_val / equity * 100, 2)
                else:
                    # Regular company balance sheet metrics
                    # PPE
                    for key in ["Net PPE", "Property Plant And Equipment Net"]:
                        if key in balance.index:
                            ppe = _safe_float(balance.loc[key, date])
                            if ppe:
                                metrics["ppe"][year] = _to_millions(ppe)
                                break

                    # Inventory
                    if "Inventory" in balance.index:
                        inv = _safe_float(balance.loc["Inventory", date])
                        if inv:
                            metrics["inventory"][year] = _to_millions(inv)

                    # Long-term debt
                    for key in ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"]:
                        if key in balance.index:
                            ltd = _safe_float(balance.loc[key, date])
                            if ltd:
                                metrics["long_term_debt"][year] = _to_millions(ltd)
                                break

        # Process cash flow for depreciation (only for non-financial)
        if not is_financial and cashflow is not None:
            for date in cashflow.columns:
                year = date.year
                if year not in metrics["revenue"]:
                    continue
                for key in ["Depreciation And Amortization", "Depreciation"]:
                    if key in cashflow.index:
                        dep = _safe_float(cashflow.loc[key, date])
                        if dep:
                            metrics["depreciation"][year] = _to_millions(dep)
                            break

        # Calculate return on capital (only for non-financial)
        if not is_financial:
            for year in metrics["revenue"].keys():
                npm = metrics["net_profit_margin"].get(year)
                rev = metrics["revenue"].get(year)
                if npm and rev:
                    net_income_val = rev * npm / 100 * 1_000_000
                    # Get equity from balance
                    equity = None
                    if balance is not None:
                        for eq_key in ["Total Equity", "Stockholders Equity", "Common Stock Equity"]:
                            if eq_key in balance.index:
                                equity = _safe_float(balance.loc[eq_key, balance.columns[0]])
                                if equity:
                                    break
                    
                    ltd_val = metrics["long_term_debt"].get(year)
                    if equity and (equity + max(ltd_val or 0, 0)) > 0:
                        metrics["return_on_capital"][year] = round(net_income_val / (equity + max(ltd_val or 0, 0)) * 100, 2)

        # Pad missing years
        all_years = sorted(metrics[primary_metric].keys())
        for metric_key in metrics:
            for year in all_years:
                if year not in metrics[metric_key]:
                    metrics[metric_key][year] = None

        financial_table = _metrics_to_table(metrics, is_financial=is_financial)
        if not financial_table:
            return None

        return {
            "profile": profile,
            "market_cap": market_cap,
            "financial_table": financial_table,
        }

    except Exception as e:
        print(f"Error fetching China stock (yfinance) {normalized}: {e}")
        return None


def fetch_asian_stock(ticker: str, years: int = DISPLAY_YEARS) -> Optional[Dict[str, Any]]:
    """Fetch financial data for HK/China stock."""
    if is_hk_ticker(ticker):
        return fetch_hk_stock_akshare(ticker, years)
    elif is_china_ticker(ticker):
        normalized = normalize_ticker(ticker)
        
        # Check cache first - if AKShare data was previously fetched, return it instantly
        cached = _get_asian_cache(normalized)
        if cached:
            print(f"Returning cached 10-year data for {normalized}")
            return cached
        
        # Start background AKShare fetch to populate cache for future requests
        # Use a longer timeout since this doesn't block the user response
        def background_akshare_fetch():
            # Avoid duplicate background fetches for the same ticker
            with _background_fetch_lock:
                if normalized in _background_fetch_in_progress:
                    return
                _background_fetch_in_progress.add(normalized)
            
            try:
                # Limit concurrent background fetches to prevent memory spikes
                acquired = _background_fetch_semaphore.acquire(timeout=5)
                if not acquired:
                    print(f"Too many background fetches, skipping {normalized}")
                    return
                try:
                    print(f"Background AKShare fetch started for {normalized}")
                    fetch_china_stock_akshare(ticker, years, timeout=180)
                finally:
                    _background_fetch_semaphore.release()
            except Exception as e:
                print(f"Background AKShare fetch failed for {normalized}: {e}")
            finally:
                with _background_fetch_lock:
                    _background_fetch_in_progress.discard(normalized)
        
        _background_thread_pool.submit(background_akshare_fetch)
        
        # Return yfinance data immediately for fast response (4 years)
        print(f"Returning fast yfinance data for {normalized} while AKShare fetches in background")
        return fetch_china_stock_yfinance(ticker, years)
    return None


# Row definitions matching SEC format
ROW_DEFS = [
    ("shares_outstanding", "Weighted Avg Diluted Shares (M)", "M"),
    ("revenue", "Revenue ($M)", "$M"),
    ("operating_margin", "Operating Margin (%)", "%"),
    ("depreciation", "Depreciation ($M)", "$M"),
    ("income_tax_rate", "Income Tax Rate (%)", "%"),
    ("net_profit_margin", "Net Profit Margin (%)", "%"),
    ("long_term_debt", "Long-Term Debt ($M)", "$M"),
    ("ppe", "Property, Plant & Equipment ($M)", "$M"),
    ("inventory", "Inventory ($M)", "$M"),
    ("return_on_capital", "Return on Capital (%)", "%"),
]

# Row definitions for banking and insurance companies
BANK_ROW_DEFS = [
    ("shares_outstanding", "Weighted Avg Diluted Shares (M)", "M"),
    ("total_assets", "Total Assets (M)", "M"),
    ("loans", "Loans (M)", "M"),
    ("net_interest_income", "Net Interest Income (M)", "M"),
    ("noninterest_revenue", "Noninterest Revenue (M)", "M"),
    ("noninterest_expense", "Noninterest Expense (M)", "M"),
    ("net_profit", "Total Net Profit (M)", "M"),
    ("loan_loss_provision", "Loan Loss Provision (M)", "M"),
    ("long_term_debt", "Long Term Debt (M)", "M"),
    ("return_on_assets", "Return on Assets (%)", "%"),
    ("return_on_equity", "Return on Equity (%)", "%"),
]


def _metrics_to_table(metrics: Dict[str, Dict[int, Optional[float]]], is_financial: bool = False) -> List[Dict[str, Any]]:
    """Convert metrics dict to financial table format."""
    row_defs = BANK_ROW_DEFS if is_financial else ROW_DEFS
    rows = []
    for key, display_name, unit in row_defs:
        year_data = metrics.get(key, {})
        if not year_data:
            continue

        values = []
        for year in sorted(year_data.keys()):
            val = year_data[year]
            values.append({"year": year, "value": val})

        if values:
            rows.append({
                "metric_name": display_name,
                "values": values,
                "unit": unit,
            })

    return rows


# Popular HK/China companies for name-based search
POPULAR_COMPANIES = [
    # HK stocks
    {"ticker": "0700.HK", "name": "Tencent Holdings Limited", "aliases": ["tencent", "腾讯"]},
    {"ticker": "9988.HK", "name": "Alibaba Group Holding Limited", "aliases": ["alibaba", "阿里巴巴", "ali"]},
    {"ticker": "0941.HK", "name": "China Mobile Limited", "aliases": ["china mobile", "中国移动"]},
    {"ticker": "1299.HK", "name": "AIA Group Limited", "aliases": ["aia", "友邦"]},
    {"ticker": "0005.HK", "name": "HSBC Holdings plc", "aliases": ["hsbc", "汇丰"]},
    {"ticker": "0388.HK", "name": "Hong Kong Exchanges and Clearing Limited", "aliases": ["hkex", "港交所"]},
    {"ticker": "2318.HK", "name": "Ping An Insurance", "aliases": ["ping an", "平安"]},
    {"ticker": "0939.HK", "name": "China Construction Bank", "aliases": ["ccb", "建设银行"]},
    {"ticker": "1398.HK", "name": "Industrial and Commercial Bank of China", "aliases": ["icbc", "工商银行"]},
    {"ticker": "3988.HK", "name": "Bank of China", "aliases": ["boc", "中国银行"]},
    {"ticker": "0883.HK", "name": "CNOOC Limited", "aliases": ["cnooc", "中海油"]},
    {"ticker": "1088.HK", "name": "China Shenhua Energy", "aliases": ["shenhua", "神华"]},
    # China A-shares
    {"ticker": "600519.SS", "name": "Kweichow Moutai Co., Ltd.", "aliases": ["moutai", "茅台", "贵州茅台"]},
    {"ticker": "000858.SZ", "name": "Wuliangye Yibin Co., Ltd.", "aliases": ["wuliangye", "五粮液"]},
    {"ticker": "601318.SS", "name": "Ping An Insurance (Group) Company", "aliases": ["ping an", "平安"]},
    {"ticker": "600036.SS", "name": "China Merchants Bank", "aliases": ["cmb", "招商银行"]},
    {"ticker": "000333.SZ", "name": "Midea Group Co., Ltd.", "aliases": ["midea", "美的"]},
    {"ticker": "600276.SS", "name": "Jiangsu Hengrui Medicine", "aliases": ["hengrui", "恒瑞"]},
    {"ticker": "002594.SZ", "name": "BYD Company Limited", "aliases": ["byd", "比亚迪"]},
    {"ticker": "601899.SS", "name": "Zijin Mining Group", "aliases": ["zijin", "紫金矿业"]},
]


def search_asian_companies(query: str, limit: int = 10) -> List[Dict[str, str]]:
    """Search for HK/China companies by ticker or name."""
    results = []
    query_lower = query.strip().lower()
    query_upper = query.strip().upper()

    # First, check if it's a direct ticker match
    if is_asian_ticker(query_upper):
        normalized = normalize_ticker(query_upper)
        try:
            stock = yf.Ticker(normalized)
            info = stock.info
            if info and info.get("longName"):
                results.append({
                    "ticker": normalized,
                    "name": info.get("longName"),
                    "exchange": get_exchange_name(query_upper),
                })
                return results  # Return early for exact ticker match
        except Exception:
            pass

    # Search in popular companies by name or alias
    for company in POPULAR_COMPANIES:
        # Check if query matches any alias
        matches_alias = any(query_lower in alias.lower() for alias in company["aliases"])
        matches_name = query_lower in company["name"].lower()
        matches_ticker = company["ticker"].upper().startswith(query_upper) or query_upper in company["ticker"].upper()
        
        if matches_alias or matches_name or matches_ticker:
            # Avoid duplicates
            if not any(r["ticker"] == company["ticker"] for r in results):
                results.append({
                    "ticker": company["ticker"],
                    "name": company["name"],
                    "exchange": get_exchange_name(company["ticker"]),
                })

    # Sort by relevance (exact matches first)
    def sort_key(item):
        # Exact ticker match
        if item["ticker"].upper() == query_upper:
            return (0, "")
        # Alias exact match
        for company in POPULAR_COMPANIES:
            if company["ticker"] == item["ticker"]:
                for alias in company["aliases"]:
                    if alias.lower() == query_lower:
                        return (1, "")
        return (2, item["name"].lower())

    results.sort(key=sort_key)
    return results[:limit]
