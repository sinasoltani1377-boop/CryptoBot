# ============================================================
# btc_context.py — Fetch BTC candles and build context dict
# ============================================================

from typing import Any, Dict
from analysis import closed, market_structure, adx

def fetch_btc_context(fetcher) -> Dict[str, Any]:
    try:
        btc_daily = closed(fetcher("BTC-SWAP-USDT", "1d", 200))
        btc_h4    = closed(fetcher("BTC-SWAP-USDT", "4h", 200))
        btc_h1    = closed(fetcher("BTC-SWAP-USDT", "1h", 200))
        btc_m15   = closed(fetcher("BTC-SWAP-USDT", "15m", 200))
    except Exception as e:
        return {
            "daily": "RANGE", "h4": "RANGE", "h1": "RANGE", "m15": "RANGE",
            "adx_daily": 0.0, "adx_h4": 0.0, "adx_h1": 0.0, "adx_m15": 0.0,
            "error": str(e),
        }

    return {
        "daily": market_structure(btc_daily) if len(btc_daily) >= 50 else "RANGE",
        "h4":    market_structure(btc_h4)    if len(btc_h4)    >= 50 else "RANGE",
        "h1":    market_structure(btc_h1)    if len(btc_h1)    >= 50 else "RANGE",
        "m15":   market_structure(btc_m15)   if len(btc_m15)   >= 50 else "RANGE",
        "adx_daily": adx(btc_daily) if len(btc_daily) >= 30 else 0.0,
        "adx_h4":    adx(btc_h4)    if len(btc_h4)    >= 30 else 0.0,
        "adx_h1":    adx(btc_h1)    if len(btc_h1)    >= 30 else 0.0,
        "adx_m15":   adx(btc_m15)   if len(btc_m15)   >= 30 else 0.0,
    }
