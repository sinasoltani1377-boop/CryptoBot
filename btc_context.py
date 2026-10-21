# ============================================================
# btc_context.py — Fetch BTC candles and build context dict
#
# bot.py calls fetch_btc_context() ONCE per scan cycle, then
# passes the result to every generate_signal() call.
# ============================================================

from typing import Any, Dict

# توجه: اسم فایل تو analysis.py است، پس ایمپورت این‌طور اصلاح شد:
from analysis import (
    closed,
    market_structure,
    adx,
)


def fetch_btc_context(fetcher) -> Dict[str, Any]:
    """
    fetcher: callable(symbol, timeframe, limit) -> list of candles
             (should be the SAME function your bot already uses)

    Returns:
        {
          "daily": "BULLISH|BEARISH|RANGE",
          "h4":    "BULLISH|BEARISH|RANGE",
          "h1":    "BULLISH|BEARISH|RANGE",
          "adx_daily": float,
          "adx_h4":    float,
          "adx_h1":    float,
        }

    If BTC fetch fails, returns a neutral context (all RANGE) so
    altcoin signals can still be generated.
    """
    try:
        btc_daily = closed(fetcher("BTCUSDT", "1d", 200))
        btc_h4    = closed(fetcher("BTCUSDT", "4h", 200))
        btc_h1    = closed(fetcher("BTCUSDT", "1h", 200))
    except Exception as e:
        return {
            "daily": "RANGE", "h4": "RANGE", "h1": "RANGE",
            "adx_daily": 0.0, "adx_h4": 0.0, "adx_h1": 0.0,
            "error": str(e),
        }

    return {
        "daily": market_structure(btc_daily) if len(btc_daily) >= 50 else "RANGE",
        "h4":    market_structure(btc_h4)    if len(btc_h4)    >= 50 else "RANGE",
        "h1":    market_structure(btc_h1)    if len(btc_h1)    >= 50 else "RANGE",
        "adx_daily": adx(btc_daily) if len(btc_daily) >= 30 else 0.0,
        "adx_h4":    adx(btc_h4)    if len(btc_h4)    >= 30 else 0.0,
        "adx_h1":    adx(btc_h1)    if len(btc_h1)    >= 30 else 0.0,
}
