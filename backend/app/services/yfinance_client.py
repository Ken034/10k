"""Fetch real-time market data from Yahoo Finance."""
import yfinance as yf
from typing import Optional, Dict


def get_market_cap(ticker: str) -> Optional[float]:
    """
    Get current market cap for a ticker from Yahoo Finance.
    Returns market cap in USD, or None if unavailable.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        market_cap = info.get("marketCap")
        if market_cap and market_cap > 0:
            return float(market_cap)
        return None
    except Exception:
        return None


def get_stock_info(ticker: str) -> Dict[str, Optional[float]]:
    """
    Get current stock info from Yahoo Finance.
    Returns dict with market_cap, current_price, etc.
    """
    result: Dict[str, Optional[float]] = {
        "market_cap": None,
        "current_price": None,
    }
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        mc = info.get("marketCap")
        if mc and mc > 0:
            result["market_cap"] = float(mc)
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price and price > 0:
            result["current_price"] = float(price)
    except Exception:
        pass
    return result
