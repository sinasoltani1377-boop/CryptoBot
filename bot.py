import os
import html
import math
import logging
import asyncio
import requests
import time
import pandas as pd
import numpy as np

from datetime import datetime, timezone, time as dt_time

from news import get_latest_news, news_diagnostics
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from analysis import generate_signal
from btc_context import fetch_btc_context
from watchlist import get_symbols
from market import get_futures_symbols

from tracker import (
    register_signal,
    check_all_trades,
    get_open_trades,
    get_stats,
    get_stats_by_strategy,
)


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")

TOOBIT_KLINES_URL = "https://api.toobit.com/quote/v1/klines"
TOOBIT_TICKER_URL = "https://api.toobit.com/quote/v1/contract/ticker/price"
TOOBIT_TICKER_24H_URL = "https://api.toobit.com/quote/v1/contract/ticker/24hr"

AUTO_INTERVAL = 300
TRACKER_INTERVAL = 30

NEWS_BLOCK_MINUTES = 120
NEWS_FETCH_LIMIT = 50

DEFAULT_LEVERAGE = 20
DEFAULT_MARGIN_USDT = 10.0

_scan_lock = asyncio.Lock()

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# BASIC HELPERS
# ============================================================

def safe_number(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
        if not math.isfinite(number):
            return default
        return number
    except (TypeError, ValueError, OverflowError):
        return default

def display_number(value, decimals=8):
    number = safe_number(value)
    if number is None:
        return "N/A"
    return f"{number:.{decimals}f}".rstrip("0").rstrip(".")

def safe_text(value, default="N/A"):
    if value is None:
        return default
    return html.escape(str(value))

def safe_list(value):
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if value is None:
        return []
    return [value]

# ============================================================
# SYMBOLS
# ============================================================

SYMBOLS = get_symbols()

INTERVALS = {
    "1d": "1d",
    "4h": "4h",
    "1h": "1h",
    "15m": "15m",
    "5m": "5m",
}

# ============================================================
# CANDLE NORMALIZATION
# ============================================================

def normalize_candle(candle):
    if isinstance(candle, dict):
        return {
            "timestamp": candle.get("timestamp") or candle.get("time") or candle.get("t"),
            "open": safe_number(candle.get("open", candle.get("o"))),
            "high": safe_number(candle.get("high", candle.get("h"))),
            "low": safe_number(candle.get("low", candle.get("l"))),
            "close": safe_number(candle.get("close", candle.get("c"))),
            "volume": safe_number(candle.get("volume", candle.get("v"))),
        }
    if isinstance(candle, (list, tuple)):
        if len(candle) < 5:
            return None
        return {
            "timestamp": candle[0],
            "open": safe_number(candle[1]),
            "high": safe_number(candle[2]),
            "low": safe_number(candle[3]),
            "close": safe_number(candle[4]),
            "volume": safe_number(candle[5]) if len(candle) > 5 else None,
        }
    return None

def extract_candle_rows(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "result", "rows", "klines", "candles"):
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for nested_key in ("data", "rows", "klines", "candles"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        return nested
    return []

def normalize_candles(data):
    rows = extract_candle_rows(data)
    candles = []
    for row in rows:
        candle = normalize_candle(row)
        if candle is None:
            continue
        required = ("open", "high", "low", "close")
        if any(candle.get(key) is None for key in required):
            continue
        if (candle["high"] < candle["low"] or candle["high"] <= 0 or candle["low"] <= 0 or candle["close"] <= 0):
            continue
        candles.append(candle)
    return candles

# ============================================================
# TOOBIT MARKET DATA
# ============================================================

def get_klines(symbol, interval, limit=200):
    try:
        response = requests.get(
            TOOBIT_KLINES_URL,
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=15,
        )
        response.raise_for_status()
        candles = normalize_candles(response.json())
        if len(candles) < 50:
            logger.warning("%s %s: insufficient candles: %s", symbol, interval, len(candles))
            return []
        return candles
    except Exception:
        logger.exception("Kline error %s %s", symbol, interval)
        return []

def get_market_data(symbol):
    daily = get_klines(symbol, INTERVALS["1d"], 200)
    h4 = get_klines(symbol, INTERVALS["4h"], 200)
    h1 = get_klines(symbol, INTERVALS["1h"], 200)
    m15 = get_klines(symbol, INTERVALS["15m"], 200)
    m5 = get_klines(symbol, INTERVALS["5m"], 200)

    if not all((daily, h4, h1, m15, m5)):
        logger.warning("MARKET_DATA_INCOMPLETE | %s", symbol)
        return None

    return {"1d": daily, "4h": h4, "1h": h1, "15m": m15, "5m": m5}

# ============================================================
# PRICE
# ============================================================

def get_price(symbol):
    try:
        response = requests.get(TOOBIT_TICKER_URL, params={"symbol": symbol}, timeout=10)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            price_value = data.get("p") or data.get("price") or data.get("lastPrice") or data.get("last")
            if price_value is not None:
                return float(price_value)

        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                item_symbol = item.get("symbol") or item.get("s")
                if item_symbol is not None and item_symbol != symbol:
                    continue
                price_value = item.get("p") or item.get("price") or item.get("lastPrice") or item.get("last")
                if price_value is not None:
                    return float(price_value)

        logger.warning("PRICE API | %s | Price not found", symbol)
        return None
    except Exception:
        logger.exception("Price error %s", symbol)
        return None

# ============================================================
# PROFIT / ROI ESTIMATION
# ============================================================

def calculate_trade_roi(direction, entry, target, leverage=DEFAULT_LEVERAGE, margin=DEFAULT_MARGIN_USDT):
    entry = safe_number(entry)
    target = safe_number(target)
    leverage = safe_number(leverage)
    margin = safe_number(margin)

    if (entry is None or target is None or leverage is None or margin is None or entry <= 0 or target <= 0 or leverage <= 0 or margin <= 0):
        return None

    direction = str(direction).upper()

    if direction == "LONG":
        price_change_pct = ((target - entry) / entry) * 100
    elif direction == "SHORT":
        price_change_pct = ((entry - target) / entry) * 100
    else:
        return None

    roi_pct = price_change_pct * leverage
    pnl_usdt = margin * roi_pct / 100

    return {"price_change_pct": price_change_pct, "roi_pct": roi_pct, "pnl_usdt": pnl_usdt}

def add_signal_context(result):
    if not isinstance(result, dict):
        return result

    result["leverage"] = DEFAULT_LEVERAGE
    result["margin_usdt"] = DEFAULT_MARGIN_USDT

    entry = result.get("entry")
    direction = result.get("direction")
    roi = {}

    for label in ("tp1", "tp2", "tp3", "sl"):
        roi[label] = calculate_trade_roi(direction, entry, result.get(label))

    result["leverage_roi"] = roi
    return result

def roi_line(label, roi_data):
    if not isinstance(roi_data, dict):
        return f"{label}: N/A"
    roi = safe_number(roi_data.get("roi_pct"))
    pnl = safe_number(roi_data.get("pnl_usdt"))
    if roi is None or pnl is None:
        return f"{label}: N/A"
    return f"{label}: {roi:+.2f}% ({pnl:+.2f} USDT)"

# ============================================================
# CRITICAL NEWS FILTER
# ============================================================

BEARISH_NEWS_TERMS = (
    "market crash", "crypto crash", "bitcoin crashes", "bitcoin plunges", "market plunges",
    "liquidation cascade", "flash crash", "stablecoin depeg", "stablecoin collapse",
    "exchange hacked", "exchange hack", "major crypto hack", "security breach", "bankruptcy",
    "insolvency", "etf rejected", "etf rejection", "sec rejects", "higher than expected",
    "hotter than expected", "above expectations", "above forecast", "unexpectedly high",
    "inflation accelerates", "inflation hotter", "ppi jumps", "cpi jumps", "producer prices surge",
    "inflation surges",
)

BULLISH_NEWS_TERMS = (
    "market-wide rally", "crypto market surges", "bitcoin surges", "bitcoin rallies",
    "lower than expected inflation", "cooler than expected", "below expectations",
    "below forecast", "inflation cools", "inflation slows", "unexpected rate cut",
    "fed cuts rates", "spot bitcoin etf approved", "spot ethereum etf approved", "sec approves spot etf",
)

MACRO_TERMS = ("ppi", "cpi", "inflation", "producer price", "consumer price", "federal reserve", "federal funds rate", "interest rate", "fed decision", "rate decision")

MACRO_SURPRISE_TERMS = (
    "higher than expected", "hotter than expected", "above expectations", "above forecast",
    "unexpectedly high", "inflation accelerates", "inflation hotter", "ppi jumps", "cpi jumps",
    "producer prices surge", "lower than expected inflation", "cooler than expected",
    "below expectations", "below forecast", "inflation cools", "inflation slows", "unexpected rate cut",
)

CRITICAL_EVENT_TERMS = (
    "exchange hacked", "exchange hack", "major crypto hack", "security breach", "stablecoin depeg",
    "stablecoin collapse", "liquidation cascade", "flash crash", "market crash", "crypto crash",
    "bitcoin plunges", "bitcoin crashes", "bankruptcy", "insolvency",
)

BULLISH_CRITICAL_TERMS = ("spot bitcoin etf approved", "spot ethereum etf approved", "sec approves spot etf", "unexpected rate cut", "fed cuts rates")

BEARISH_CRITICAL_TERMS = (
    "etf rejected", "etf rejection", "sec rejects", "market crash", "crypto crash", "bitcoin plunges",
    "bitcoin crashes", "liquidation cascade", "flash crash", "stablecoin depeg", "stablecoin collapse",
    "exchange hacked", "exchange hack", "major crypto hack", "security breach", "bankruptcy", "insolvency",
)

def article_datetime(article):
    published = article.get("published")
    if not published:
        return None
    try:
        value = str(published).strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None

def article_text(article):
    title = str(article.get("title") or "")
    summary = str(article.get("summary") or "")
    return f"{title} {summary}".lower()

def contains_any(text, terms):
    return any(term in text for term in terms)

def is_market_wide_news(text):
    market_terms = (
        "crypto market", "cryptocurrency market", "global crypto", "bitcoin crash", "bitcoin plunges",
        "market crash", "crypto crash", "liquidation cascade", "flash crash", "federal reserve",
        "interest rate", "rate decision", "inflation", "producer price", "consumer price", "ppi", "cpi",
    )
    return contains_any(text, market_terms)

def news_direction(text):
    bearish = contains_any(text, BEARISH_NEWS_TERMS)
    bullish = contains_any(text, BULLISH_NEWS_TERMS)
    if bearish and not bullish:
        return "BEARISH"
    if bullish and not bearish:
        return "BULLISH"
    return None

def is_critical_news(text, importance):
    if contains_any(text, CRITICAL_EVENT_TERMS):
        return True
    macro_news = contains_any(text, MACRO_TERMS)
    macro_surprise = contains_any(text, MACRO_SURPRISE_TERMS)
    if macro_news and macro_surprise:
        return True
    if contains_any(text, BULLISH_CRITICAL_TERMS):
        return True
    if contains_any(text, BEARISH_CRITICAL_TERMS):
        return True
    return importance == "CRITICAL" and news_direction(text) is not None

def news_applies_to_symbol(article, symbol, text):
    if is_market_wide_news(text):
        return True
    asset = str(article.get("asset") or "UNKNOWN").upper()
    symbol_upper = symbol.upper()
    if asset == "MARKET":
        return True
    if asset == "BTC":
        return "BTC" in symbol_upper
    if asset == "ETH":
        return "ETH" in symbol_upper
    return False

async def check_critical_news(symbol, direction):
    if direction not in ("LONG", "SHORT"):
        return False, "فیلتر خبر رد شد: جهت نامعتبر است."
    try:
        articles = await get_latest_news(limit=NEWS_FETCH_LIMIT)
        if not articles:
            logger.warning("NEWS_FILTER_UNAVAILABLE | %s | No articles", symbol)
            return False, "⚠️ اخبار در دسترس نیست؛ فیلتر خبری بررسی کامل انجام نداد."
        
        now = datetime.now(timezone.utc)
        for article in articles:
            if not isinstance(article, dict):
                continue
            published_at = article_datetime(article)
            if published_at is None:
                continue
            age_minutes = (now - published_at).total_seconds() / 60
            if age_minutes < 0 or age_minutes > NEWS_BLOCK_MINUTES:
                continue
            
            text = article_text(article)
            importance = str(article.get("importance") or "NORMAL").upper()
            
            if not is_critical_news(text, importance):
                continue
            if not news_applies_to_symbol(article, symbol, text):
                continue
            
            direction_of_news = news_direction(text)
            if direction_of_news is None:
                continue
            
            conflict = (direction == "LONG" and direction_of_news == "BEARISH") or (direction == "SHORT" and direction_of_news == "BULLISH")
            if not conflict:
                continue
            
            title = str(article.get("title") or "Critical news")
            source = str(article.get("source") or "Unknown")
            
            logger.warning("SIGNAL_BLOCKED_BY_NEWS | %s | Direction=%s | NewsDirection=%s | Age=%.1f | Source=%s | Title=%s",
                symbol, direction, direction_of_news, age_minutes, source, title)
            return True, f"⛔ سیگنال به دلیل خبر بحرانی متناقض مسدود شد.\nجهت معامله: {direction}\nجهت خبر: {direction_of_news}\nخبر: {title}"
        
        logger.info("NEWS_FILTER_PASS | %s | Direction=%s", symbol, direction)
        return False, "✅ خبر بحرانی متناقض شناسایی نشد."
    except Exception:
        logger.exception("NEWS_FILTER_ERROR | %s", symbol)
        return False, "⚠️ فیلتر خبری موقتاً در دسترس نیست."

# ============================================================
# TRACKER HELPERS
# ============================================================
def already_tracking(symbol, direction):
    try:
        open_trades = get_open_trades()
        
        if len(open_trades) >= 40:
            logger.warning(
                "MAX_OPEN_TRADES_REACHED | %s | Existing=%d",
                symbol, len(open_trades),
            )
            return True
        
        same_dir_count = sum(
            1 for t in open_trades
            if str(t.get("direction", "")).upper() == direction
        )
        if same_dir_count >= 2:
            logger.warning(
                "MAX_SAME_DIRECTION | %s | %s count=%d",
                symbol, direction, same_dir_count,
            )
            return True
        
        for trade in open_trades:
            if (trade.get("symbol") == symbol and 
                str(trade.get("direction", "")).upper() == direction):
                return True
        
        return False
    except Exception:
        logger.exception("Tracker duplicate-check error")
        return False

def is_valid_high_signal(result):
    if not isinstance(result, dict):
        return False
    if str(result.get("quality", "")).upper() != "HIGH":
        return False

    direction = str(result.get("direction") or "").upper()
    signal_value = str(result.get("signal") or "").upper()
    score = safe_number(result.get("score"))

    if direction not in ("LONG", "SHORT") or signal_value != direction:
        return False

    if score is None or score < 10:
        return False

    for key in ("entry", "sl", "tp1", "tp2", "tp3"):
        value = safe_number(result.get(key))
        if value is None or value <= 0:
            logger.info("SIGNAL_REJECTED | Missing/invalid %s=%s", key, result.get(key))
            return False

    entry = float(result["entry"])
    sl = float(result["sl"])
    tp1 = float(result["tp1"])
    tp2 = float(result["tp2"])
    tp3 = float(result["tp3"])

    if direction == "LONG":
        levels_valid = (sl < entry < tp1 <= tp2 <= tp3)
    else:
        levels_valid = (sl > entry > tp1 >= tp2 >= tp3)

    if not levels_valid:
        logger.warning("SIGNAL_REJECTED | Invalid level ordering | Direction=%s Entry=%s SL=%s TP1=%s TP2=%s TP3=%s",
            direction, entry, sl, tp1, tp2, tp3)
        return False

    return True

def register_high_signal(symbol, result):
    if not is_valid_high_signal(result):
        return None
    direction = str(result.get("direction")).upper()
    if already_tracking(symbol, direction):
        logger.info("TRACKER | ALREADY OPEN | %s | %s", symbol, direction)
        return None

    payload = dict(result)
    payload["symbol"] = symbol
    payload["direction"] = direction
    payload["signal"] = direction
    payload["leverage"] = DEFAULT_LEVERAGE
    payload["margin"] = DEFAULT_MARGIN_USDT
    payload["margin_usdt"] = DEFAULT_MARGIN_USDT

    try:
        registered = register_signal(payload)
        if not registered:
            logger.warning("TRACKER | REGISTRATION FAILED | %s | %s", symbol, direction)
            return None
        logger.info("TRACKER | REGISTERED | %s | %s | Score=%s | Entry=%s | SL=%s | TP1=%s | TP2=%s | TP3=%s",
            symbol, direction, result.get("score"), result.get("entry"), result.get("sl"), result.get("tp1"), result.get("tp2"), result.get("tp3"))
        return payload
    except Exception:
        logger.exception("TRACKER_REGISTER_ERROR | %s", symbol)
        return None

# ============================================================
# STRATEGY DIAGNOSTICS
# ============================================================

def log_strategy_details(symbol, result):
    diagnostics = result.get("strategy_diagnostics")
    if isinstance(diagnostics, dict):
        parts = []
        for strategy in ("TREND_FOLLOWING", "PULLBACK", "BREAKOUT", "REVERSAL", "RANGE_TRADING", "BB_REVERSION"):
            value = diagnostics.get(strategy)
            if value is None:
                parts.append(f"{strategy}=NO_DATA")
                continue
            if isinstance(value, dict):
                matched = value.get("matched")
                reason = value.get("reason") or value.get("blocked_reason") or value.get("failure_reason") or value.get("fail_reason") or value.get("status") or ""
                status = "PASS" if matched is True else "FAIL"
                if reason:
                    status = f"{status}:{reason}"
                parts.append(f"{strategy}={status}")
            elif isinstance(value, bool):
                parts.append(f"{strategy}={'PASS' if value else 'FAIL'}")
            else:
                parts.append(f"{strategy}={value}")
        logger.info("STRATEGY_CHECK | %s | %s", symbol, " | ".join(parts))
        return

def log_signal_diagnostic(symbol, result):
    if not isinstance(result, dict):
        return
    daily = result.get("daily", "UNKNOWN")
    h4 = result.get("4h", "UNKNOWN")
    h1 = result.get("1h", "UNKNOWN")
    direction = result.get("direction", "UNKNOWN")
    signal_value = result.get("signal", "UNKNOWN")
    score = result.get("score", "UNKNOWN")
    quality = result.get("quality", "UNKNOWN")
    reason = result.get("reason") or result.get("blocked_reason") or "UNKNOWN"
    strategies = result.get("strategy_matches") or result.get("strategies") or []
    
    if isinstance(strategies, (list, tuple, set)):
        strategies_text = ", ".join(str(item) for item in strategies) if strategies else "NONE"
    else:
        strategies_text = str(strategies)
        
    logger.info("DIAGNOSTIC | %s | Daily=%s | 4H=%s | 1H=%s | Direction=%s | Signal=%s | Score=%s | Quality=%s | Reason=%s | Strategies=%s",
        symbol, daily, h4, h1, direction, signal_value, score, quality, reason, strategies_text)
    
    rsi_15m = result.get("15m_rsi", result.get("rsi_15m"))
    logger.info("FILTERS | %s | 15M_RSI=%s | ADX_1H=%s | ADX_15M=%s | MTF_15M=%s | VolumeSpike=%s | Confirmation=%s",
        symbol, rsi_15m, result.get("adx_1h"), result.get("adx_15m"), result.get("mtf_confirmation", result.get("mtf_confirmed")), result.get("volume_spike"), result.get("confirmation"))
    
    log_strategy_details(symbol, result)

# ============================================================
# SIGNAL MESSAGE
# ============================================================

def signal_text(symbol, result):
    direction = str(result.get("direction", "UNKNOWN")).upper()
    emoji = "🟢" if direction == "LONG" else "🔴" if direction == "SHORT" else "⚪"
    strategies = result.get("strategy_matches") or result.get("strategies") or []
    strategies = safe_list(strategies)
    strategy_text = ", ".join(str(item) for item in strategies) if strategies else "NONE"
    roi = result.get("leverage_roi") or {}
    news_note = result.get("_news_note", "بررسی نشده")

    btc_dir = result.get("btc_dir", "UNKNOWN")
    btc_relation = result.get("btc_relation", "NEUTRAL")
    btc_warning = result.get("btc_warning", False)
    btc_adx = result.get("btc_adx", 0.0)

    if btc_relation == "ALIGNED":
        alignment_text = "✅ هم‌جهت با روند بیت‌کوین"
    elif btc_relation == "OPPOSED":
        alignment_text = f"⚠️ خلاف جهت روند بیت‌کوین (ADX: {btc_adx})"
        if btc_warning:
            alignment_text = "🚨 " + alignment_text + " - احتیاط!"
    else:
        alignment_text = "➖ روند بیت‌کوین خنثی یا ترکیبی"

    return (
        f"{emoji} <b>{safe_text(symbol)}</b>\n\n"
        f"🎯 Signal: <b>{safe_text(direction)}</b>\n"
        f"⭐ Quality: <b>{safe_text(result.get('quality'))}</b>\n"
        f"📊 Score: <b>{safe_text(result.get('score'))}</b>\n\n"
        f"📅 Daily: {safe_text(result.get('daily'))}\n"
        f"⏱ 4H: {safe_text(result.get('4h'))}\n"
        f"🕐 1H: {safe_text(result.get('1h'))}\n"
        f"⏱ 15M RSI: {safe_text(result.get('15m_rsi', result.get('rsi_15m')))}\n"
        f"📊 ADX 1H: {safe_text(result.get('adx_1h'))}\n"
        f"📊 ADX 15M: {safe_text(result.get('adx_15m'))}\n"
        f"✅ MTF 15M: {safe_text(result.get('mtf_confirmation', result.get('mtf_confirmed')))}\n\n"
        f"₿ BTC Trend: <b>{safe_text(btc_dir)}</b>\n"
        f"{alignment_text}\n\n"
        f"💰 Entry: <b>{display_number(result.get('entry'))}</b>\n"
        f"🛑 SL: <b>{display_number(result.get('sl'))}</b>\n"
        f"🎯 TP1: <b>{display_number(result.get('tp1'))}</b>\n"
        f"🎯 TP2: <b>{display_number(result.get('tp2'))}</b>\n"
        f"🎯 TP3: <b>{display_number(result.get('tp3'))}</b>\n\n"
        f"📏 Risk: {safe_text(result.get('risk'))}\n"
        f"⚖️ RR: {safe_text(result.get('rr'))}\n\n"
        f"💵 Margin: {DEFAULT_MARGIN_USDT:.2f} USDT\n"
        f"⚡ Leverage: {DEFAULT_LEVERAGE}x\n"
        f"📈 تخمین سود/زیان ناخالص:\n"
        f"  {roi_line('TP1', roi.get('tp1'))}\n"
        f"  {roi_line('TP2', roi.get('tp2'))}\n"
        f"  {roi_line('TP3', roi.get('tp3'))}\n"
        f"  {roi_line('SL', roi.get('sl'))}\n\n"
        f"🧠 Strategy:\n<b>{safe_text(strategy_text)}</b>\n\n"
        f"📝 Reason:\n{safe_text(result.get('reason', 'N/A'))}\n\n"
        f"📰 News Filter:\n{safe_text(news_note)}\n\n"
        f"⚠️ تخمین قبل از کارمزد و فاندینگ؛ سود واقعی ممکن است متفاوت باشد."
    )

# ============================================================
# RAW ANALYSIS (With BTC Context)
# ============================================================

def analyze_symbol_raw(symbol, btc_context):
    market_data = get_market_data(symbol)
    if market_data is None:
        return None

    result = generate_signal(
        market_data["1d"],
        market_data["4h"],
        market_data["1h"],
        market_data["15m"],
        market_data["5m"],
        btc_context=btc_context
    )
    
    if not isinstance(result, dict):
        logger.warning("ANALYSIS_INVALID_RESULT | %s", symbol)
        return None
    return result

# ============================================================
# COMMON SIGNAL PREPARATION (With BTC Context)
# ============================================================

async def prepare_signal(symbol, btc_context):
    result = await asyncio.to_thread(analyze_symbol_raw, symbol, btc_context)
    if result is None:
        return None, False, "No analysis result"

    log_signal_diagnostic(symbol, result)

    if not is_valid_high_signal(result):
        return result, False, "Not a valid HIGH signal"

    blocked, news_note = await check_critical_news(symbol, result.get("direction"))
    if blocked:
        return result, True, news_note

    result["_news_note"] = news_note
    result = await asyncio.to_thread(add_signal_context, result)

    return result, False, news_note

# ============================================================
# /START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_ids = context.application.bot_data.setdefault("chat_ids", set())
    chat_ids.add(update.effective_chat.id)
    await update.effective_message.reply_text(
        f"🤖 CryptoBot فعال است.\n"
        f"📊 تعداد ارزهای در حال اسکن: {len(SYMBOLS)}\n\n"
        "دستورات:\n"
        "/price - قیمت BTC و SOL\n"
        "/signal - بررسی سیگنال‌های HIGH\n"
        "/register - دریافت سیگنال خودکار\n"
        "/stats - آمار تریدها\n"
        "/news - آخرین اخبار کریپتو\n"
        "/news_test - آزمایش منابع خبری\n"
        "/backtest - تست استراتژی روی دیتای تاریخی\n"
        "/report - گزارش روزانه استراتژی‌ها (دستی)"
    )

# ============================================================
# /PRICE
# ============================================================

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    btc = await asyncio.to_thread(get_price, "BTC-SWAP-USDT")
    sol = await asyncio.to_thread(get_price, "SOL-SWAP-USDT")

    message = "💰 <b>CryptoBot Prices</b>\n\n"
    if btc is not None:
        message += f"₿ BTC: <b>{display_number(btc)}</b>\n"
    else:
        message += "₿ BTC: unavailable\n"
    if sol is not None:
        message += f"◎ SOL: <b>{display_number(sol)}</b>\n"
    else:
        message += "◎ SOL: unavailable\n"

    await update.effective_message.reply_text(message, parse_mode="HTML")

# ============================================================
# /SIGNAL
# ============================================================

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        f"🔎 در حال بررسی {len(SYMBOLS)} ارز...\n"
        "Daily → 4H → 1H → 15M → 5M\n\n"
        "فقط سیگنال‌های HIGH با امتیاز بالا.\n"
        "خبرهای بحرانی و روند بیت‌کوین بررسی می‌شوند.\n"
        "این کار ممکن است چند دقیقه طول بکشد."
    )

    btc_context = await asyncio.to_thread(fetch_btc_context, get_klines)

    found = 0
    blocked_by_news = 0
    registration_failed = 0

    for symbol in SYMBOLS:
        try:
            result, blocked, note = await prepare_signal(symbol, btc_context)

            if result is None:
                continue
            if blocked:
                blocked_by_news += 1
                continue
            if not is_valid_high_signal(result):
                continue

            trade = register_high_signal(symbol, result)
            if trade is None:
                registration_failed += 1
                continue

            await update.effective_message.reply_text(
                signal_text(symbol, result),
                parse_mode="HTML",
            )
            found += 1
        except Exception:
            logger.exception("Signal error %s", symbol)

    if found == 0:
        await update.effective_message.reply_text(
            f"⏳ هیچ سیگنال HIGH جدیدی برای ارسال پیدا نشد.\n"
            f"🔍 تعداد ارزهای بررسی‌شده: {len(SYMBOLS)}\n"
            f"⛔ مسدودشده توسط خبر: {blocked_by_news}\n"
            f"📌 ثبت ناموفق یا معامله تکراری: {registration_failed}\n\n"
            "جزئیات تشخیص در لاگ Belmo ثبت شد."
        )

# ============================================================
# AUTOMATIC SIGNAL SCANNER
# ============================================================

async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    if _scan_lock.locked():
        logger.warning("Previous scan still running. Skipping.")
        return

    async with _scan_lock:
        logger.info("Starting automatic market scan across %s symbols", len(SYMBOLS))

        btc_context = await asyncio.to_thread(fetch_btc_context, get_klines)

        found = 0
        blocked_by_news = 0

        for symbol in SYMBOLS:
            try:
                result, blocked, note = await prepare_signal(symbol, btc_context)

                if result is None:
                    continue
                if blocked:
                    blocked_by_news += 1
                    logger.warning("AUTO_SIGNAL_BLOCKED_BY_NEWS | %s", symbol)
                    continue
                if not is_valid_high_signal(result):
                    continue

                trade = register_high_signal(symbol, result)
                if trade is None:
                    continue

                found += 1
                logger.info("NEW HIGH SIGNAL | %s | %s | Score=%s | Strategy=%s",
                    symbol, result.get("direction"), result.get("score"), result.get("strategy"))

                chat_ids = context.application.bot_data.get("chat_ids", set())
                for chat_id in list(chat_ids):
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=signal_text(symbol, result),
                            parse_mode="HTML",
                        )
                    except Exception:
                        logger.exception("Telegram send error for chat %s", chat_id)
            except Exception:
                logger.exception("Auto scan error %s", symbol)

        logger.info("Automatic scan completed. New signals=%s | Blocked by news=%s", found, blocked_by_news)

# ============================================================
# TRACK OPEN TRADES
# ============================================================

async def track_open_trades(context: ContextTypes.DEFAULT_TYPE):
    try:
        open_trades = await asyncio.to_thread(get_open_trades)
        if not open_trades:
            logger.info("TRACKER CHECK | No open trades")
            return

        logger.info("TRACKER CHECK | Open trades=%s", len(open_trades))

        events = await asyncio.to_thread(check_all_trades, get_price)
        if not events:
            return

        chat_ids = context.application.bot_data.get("chat_ids", set())

        for event in events:
            if not isinstance(event, dict):
                continue

            event_name = str(event.get("event", "UNKNOWN")).upper()
            symbol = event.get("symbol", "UNKNOWN")
            direction = event.get("direction", "UNKNOWN")
            strategy_name = event.get("strategy", "UNKNOWN")
            price_now = event.get("price")
            entry = event.get("entry")
            sl = event.get("sl")
            tp1 = event.get("tp1")
            tp2 = event.get("tp2")
            tp3 = event.get("tp3")
            pnl = safe_number(event.get("realized_pnl"), 0.0)
            roi_pct = safe_number(event.get("roi_percent"), 0.0)
            margin = safe_number(event.get("margin"), DEFAULT_MARGIN_USDT)
            leverage = safe_number(event.get("leverage"), DEFAULT_LEVERAGE)

            title_map = {
                "TP1": "🎯 تارگت اول لمس شد",
                "TP2": "🎯 تارگت دوم لمس شد",
                "TP3": "🏆 تارگت سوم لمس شد",
                "SL": "🛑 حد ضرر لمس شد",
                "BE": "⚖️ خروج در نقطه سربه‌سر",
                "BREAKEVEN": "⚖️ خروج در نقطه سربه‌سر (بدون ضرر)",
                "TP1_PROTECTED": "✅ حد ضرر در تارگت اول (سود قفل شد)",
            }
            title = title_map.get(event_name, f"📊 رویداد Tracker: {event_name}")

            message = (
                f"<b>{title}</b>\n\n"
                f"🪙 {safe_text(symbol)}\n"
                f"📈 Direction: <b>{safe_text(direction)}</b>\n"
                f"🧠 Strategy: <b>{safe_text(strategy_name)}</b>\n\n"
                f"💰 Current Price: <b>{display_number(price_now)}</b>\n"
                f"📌 Entry: {display_number(entry)}\n"
                f"🛑 SL فعلی: {display_number(sl)}\n"
                f"🎯 TP1: {display_number(tp1)}\n"
                f"🎯 TP2: {display_number(tp2)}\n"
                f"🎯 TP3: {display_number(tp3)}\n\n"
                f"💵 مارجین: {margin:.2f} USDT\n"
                f"⚡ اهرم: {leverage:g}x\n"
                f"💹 PnL تحقق‌یافته ثبت‌شده: {pnl:+.4f} USDT\n"
                f"📊 ROI ثبت‌شده: {roi_pct:+.2f}%\n"
                f"📍 وضعیت: <b>{safe_text(event_name)}</b>"
            )

            for chat_id in list(chat_ids):
                try:
                    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
                except Exception:
                    logger.exception("Tracker Telegram error for chat %s", chat_id)

            logger.info("TRACKER | %s | %s | Price=%s | PnL=%s | ROI=%s", symbol, event_name, price_now, pnl, roi_pct)

    except Exception:
        logger.exception("Tracker error")

# ============================================================
# /REGISTER
# ============================================================

async def register_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_ids = context.application.bot_data.setdefault("chat_ids", set())
    chat_ids.add(update.effective_chat.id)
    await update.effective_message.reply_text("✅ این چت برای دریافت سیگنال‌های خودکار ثبت شد.")

# ============================================================
# /STATS
# ============================================================

async def tracker_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stats = await asyncio.to_thread(get_stats)
        realized_pnl = safe_number(stats.get("realized_pnl"), 0.0)
        realized_roi = safe_number(stats.get("realized_roi"), 0.0)
        closed_pnl = safe_number(stats.get("closed_realized_pnl", stats.get("realized_pnl")), 0.0)
        closed_roi = safe_number(stats.get("closed_roi", stats.get("realized_roi")), 0.0)

        message = (
            "📊 <b>Tracker Statistics</b>\n\n"
            f"📌 Total Signals: {stats.get('total', 0)}\n"
            f"⏳ Open: {stats.get('open', 0)}\n"
            f"🔒 Closed: {stats.get('closed', 0)}\n\n"
            f"🎯 TP1 Hit: {stats.get('tp1', 0)}\n"
            f"🎯 TP2 Hit: {stats.get('tp2', 0)}\n"
            f"🎯 TP3 Hit: {stats.get('tp3', 0)}\n"
            f"🛑 SL Hit: {stats.get('sl', 0)}\n"
            f"⚖️ Breakeven: {stats.get('breakeven', 0)}\n"
            f"✅ TP1 Protected: {stats.get('tp1_protected', 0)}\n\n"
            f"💵 Realized PnL: {realized_pnl:+.4f} USDT\n"
            f"📈 Realized ROI: {realized_roi:+.2f}%\n"
            f"🔒 Closed PnL: {closed_pnl:+.4f} USDT\n"
            f"📊 Closed ROI: {closed_roi:+.2f}%"
        )
        await update.effective_message.reply_text(message, parse_mode="HTML")
    except Exception:
        logger.exception("Tracker stats error")
        await update.effective_message.reply_text("❌ خطا در دریافت آمار Tracker.")

# ============================================================
# /NEWS
# ============================================================

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await update.effective_message.reply_text("📰 در حال دریافت اخبار کریپتو...")
    try:
        articles = await get_latest_news(limit=8)
        if not articles:
            await message.edit_text("⚠️ در حال حاضر خبری دریافت نشد.\nممکن است منابع RSS در دسترس نباشند.")
            return

        lines = ["📰 آخرین اخبار کریپتو\n"]
        for index, article in enumerate(articles, start=1):
            importance = article.get("importance", "NORMAL")
            emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "NORMAL": "🟢"}.get(importance, "⚪")
            title = str(article.get("title", "بدون عنوان"))
            source = str(article.get("source", "Unknown"))
            asset = str(article.get("asset", "UNKNOWN"))
            link = str(article.get("link", ""))
            
            item = f"{index}. {emoji} {title}\n📡 منبع: {source}\n🪙 دارایی: {asset}\n"
            if link.startswith(("https://", "http://")):
                item += f"🔗 {link}\n"
            lines.append(item)

        output = "\n".join(lines)
        if len(output) > 4000:
            output = output[:3900] + "\n\nادامه اخبار در اجرای بعدی."
        await message.edit_text(output, disable_web_page_preview=True)
    except Exception:
        logger.exception("NEWS_COMMAND_ERROR")
        await message.edit_text("❌ خطا هنگام دریافت اخبار.\nلاگ Belmo را بررسی کن.")

# ============================================================
# /NEWS_TEST
# ============================================================

async def news_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await update.effective_message.reply_text("🔎 در حال آزمایش منابع خبری...")
    try:
        result = await news_diagnostics()
        lines = [
            "📊 گزارش آزمایش منابع خبری\n",
            f"📰 مجموع اخبار: {result.get('total', 0)}",
            f"🔴 اخبار CRITICAL: {result.get('critical_count', 0)}",
            f"🟠 اخبار HIGH: {result.get('high_count', 0)}",
            "",
            "وضعیت منابع:",
        ]
        for source, status in result.get("sources", {}).items():
            icon = "✅" if status.get("ok") else "❌"
            count = status.get("count", 0)
            lines.append(f"{icon} {source}: {count} خبر")
        await message.edit_text("\n".join(lines))
    except Exception:
        logger.exception("NEWS_TEST_ERROR")
        await message.edit_text("❌ آزمایش منابع خبری ناموفق بود.\nلاگ Belmo را بررسی کن.")

# ============================================================
# /DAILY_REPORT (auto + /report manual)
# ============================================================

async def daily_strategy_report(context: ContextTypes.DEFAULT_TYPE):
    """
    Daily report broken down by strategy.
    Runs automatically every day at 20:30 UTC (00:00 Tehran).
    """
    try:
        strategy_stats = await asyncio.to_thread(get_stats_by_strategy)
        overall = await asyncio.to_thread(get_stats)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if not strategy_stats:
            message = (
                f"📊 <b>گزارش روزانه استراتژی‌ها</b>\n"
                f"📅 {today}\n\n"
                "هنوز هیچ معامله‌ای ثبت نشده است."
            )
        else:
            sorted_strats = sorted(
                strategy_stats.items(),
                key=lambda x: x[1]["total"],
                reverse=True,
            )

            lines = [
                f"📊 <b>گزارش روزانه استراتژی‌ها</b>",
                f"📅 {today}",
                "=" * 30,
                "",
            ]

            for name, s in sorted_strats:
                if s["realized_pnl"] > 0:
                    emoji = "🏆"
                elif s["realized_pnl"] < 0:
                    emoji = "❌"
                else:
                    emoji = "⚖️"

                lines.append(f"{emoji} <b>{name}</b>")
                lines.append(f"   📌 کل سیگنال: <b>{s['total']}</b>")
                lines.append(f"   ⏳ باز: {s['open']} | 🔒 بسته: {s['closed']}")
                lines.append(
                    f"   🎯 TP1: {s['tp1']} | TP2: {s['tp2']} | TP3: {s['tp3']}"
                )
                lines.append(
                    f"   🛑 SL: {s['sl']} | ⚖️ BE: {s['breakeven']}"
                )
                if s["tp1_protected"] > 0:
                    lines.append(f"   ✅ TP1 Protected: {s['tp1_protected']}")
                lines.append(
                    f"   💰 PnL: <b>{s['realized_pnl']:+.4f} USDT</b>"
                )
                lines.append("")

            lines.append("=" * 30)
            lines.append(f"💵 <b>مجموع PnL:</b> {overall['realized_pnl']:+.4f} USDT")
            lines.append(f"📈 <b>ROI:</b> {overall['realized_roi']:+.2f}%")
            lines.append(
                f"🎯 <b>TP1:</b> {overall['tp1']} | "
                f"<b>TP2:</b> {overall['tp2']} | "
                f"<b>TP3:</b> {overall['tp3']}"
            )
            lines.append(
                f"🛑 <b>SL:</b> {overall['sl']} | "
                f"⚖️ <b>BE:</b> {overall['breakeven']} | "
                f"✅ <b>TP1 Prot:</b> {overall.get('tp1_protected', 0)}"
            )

            message = "\n".join(lines)

        chat_ids = context.application.bot_data.get("chat_ids", set())
        if not chat_ids:
            logger.warning("DAILY_REPORT | No chat_ids registered. Skipping send.")
            return

        for chat_id in list(chat_ids):
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                )
                logger.info("DAILY_REPORT_SENT | chat_id=%s", chat_id)
            except Exception:
                logger.exception("Daily report send error for chat %s", chat_id)

    except Exception:
        logger.exception("Daily strategy report error")


async def report_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual trigger for the daily report (for testing)."""
    await update.effective_message.reply_text("⏳ در حال ساخت گزارش...")
    await daily_strategy_report(context)

# ============================================================
# /BACKTEST (v24 - 5000 Candles, 4 Symbols, 7 Months)
# ============================================================

async def backtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await update.effective_message.reply_text(
        "⏳ بک‌تست تاییدیه شروع شد...\n\n"
        "📊 ۴ ارز: BTC, ETH, SOL, BNB\n"
        "📉 ۵۰۰۰ کندل ۱ ساعته برای هر ارز (~۷ ماه)\n"
        "🔢 مجموع: ۲۰۰۰۰ کندل\n"
        "⏱ زمان تخمینی: ۳ تا ۵ دقیقه\n\n"
        "لطفاً صبر کنید...",
    )
    
    def run_bt():
        import requests, time, pandas as pd, numpy as np
        
        TOOBIT_URL = "https://api.toobit.com/quote/v1/klines"
        symbols = ["BTC-SWAP-USDT", "ETH-SWAP-USDT", "SOL-SWAP-USDT", "BNB-SWAP-USDT"]
        
        results = {
            name: {"wins": 0, "losses": 0, "r_sum": 0.0}
            for name in ["TREND_FOLLOWING", "PULLBACK", "BREAKOUT",
                         "BB_REVERSION", "RANGE_TRADING", "REVERSAL"]
        }
        
        def calc_adx(df, period=14):
            high, low, close = df['high'], df['low'], df['close']
            plus_dm = high.diff()
            minus_dm = -low.diff()
            plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
            minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
            tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
            atr = tr.ewm(alpha=1/period, adjust=False).mean()
            plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan))
            minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan))
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
            return dx.ewm(alpha=1/period, adjust=False).mean()
        
        def calc_rsi(df, period=14):
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0).ewm(alpha=1/period, adjust=False).mean()
            loss = -delta.where(delta < 0, 0).ewm(alpha=1/period, adjust=False).mean()
            rs = gain / loss.replace(0, np.nan)
            return 100 - (100 / (1 + rs))
        
        details = []
        
        for symbol in symbols:
            all_c = []
            end_ts = int(time.time() * 1000)
            current_ts = end_ts - (5000 * 60 * 60 * 1000)
            
            attempts = 0
            while len(all_c) < 5000 and attempts < 8:
                try:
                    res = requests.get(TOOBIT_URL, params={
                        "symbol": symbol, "interval": "1h",
                        "startTime": current_ts, "limit": 1000
                    }, timeout=20)
                    data = res.json()
                    if not isinstance(data, list) or not data:
                        break
                    for row in data:
                        all_c.append({
                            "time": row[0], "open": float(row[1]),
                            "high": float(row[2]), "low": float(row[3]),
                            "close": float(row[4]), "volume": float(row[5])
                        })
                    if len(data) < 1000:
                        break
                    current_ts = data[-1][0] + 1
                    time.sleep(0.05)
                except Exception:
                    break
                attempts += 1
            
            if len(all_c) < 500:
                details.append(f"⚠️ {symbol}: فقط {len(all_c)} کندل.")
                continue
            
            df = pd.DataFrame(all_c)
            df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
            df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
            df['sma20'] = df['close'].rolling(20).mean()
            df['std'] = df['close'].rolling(20).std()
            df['bb_upper'] = df['sma20'] + 2 * df['std']
            df['bb_lower'] = df['sma20'] - 2 * df['std']
            df['rsi'] = calc_rsi(df, 14)
            df['adx'] = calc_adx(df, 14)
            df['high20_prev'] = df['high'].rolling(20).max().shift(1)
            df['low20_prev'] = df['low'].rolling(20).min().shift(1)
            
            position = None
            entry_price = 0.0
            sl_price = 0.0
            tp_price = 0.0
            active_strategy = None
            
            for i in range(60, len(df)):
                c_close = df['close'].iloc[i]
                c_high = df['high'].iloc[i]
                c_low = df['low'].iloc[i]
                
                if position is not None:
                    hit_sl = False
                    hit_tp = False
                    if position == "LONG":
                        if c_low <= sl_price:
                            hit_sl = True
                        elif c_high >= tp_price:
                            hit_tp = True
                    elif position == "SHORT":
                        if c_high >= sl_price:
                            hit_sl = True
                        elif c_low <= tp_price:
                            hit_tp = True
                    
                    if hit_sl or hit_tp:
                        if hit_tp:
                            results[active_strategy]["wins"] += 1
                            results[active_strategy]["r_sum"] += 2.0
                        else:
                            results[active_strategy]["losses"] += 1
                            results[active_strategy]["r_sum"] -= 1.0
                        position = None
                        active_strategy = None
                    continue
                
                adx_val = df['adx'].iloc[i]
                rsi_val = df['rsi'].iloc[i]
                
                if pd.isna(adx_val) or pd.isna(rsi_val):
                    continue
                
                if adx_val < 22:
                    bb_lower = df['bb_lower'].iloc[i]
                    bb_upper = df['bb_upper'].iloc[i]
                    bb_mid = df['sma20'].iloc[i]
                    
                    if pd.isna(bb_lower) or pd.isna(bb_mid):
                        continue
                    
                    if c_close <= bb_lower and rsi_val <= 32:
                        position = "LONG"; active_strategy = "BB_REVERSION"
                        entry_price = c_close; sl_price = entry_price * 0.98; tp_price = bb_mid
                    elif c_close >= bb_upper and rsi_val >= 68:
                        position = "SHORT"; active_strategy = "BB_REVERSION"
                        entry_price = c_close; sl_price = entry_price * 1.02; tp_price = bb_mid
                    elif rsi_val <= 28:
                        position = "LONG"; active_strategy = "RANGE_TRADING"
                        entry_price = c_close; sl_price = entry_price * 0.98; tp_price = entry_price * 1.02
                    elif rsi_val >= 72:
                        position = "SHORT"; active_strategy = "RANGE_TRADING"
                        entry_price = c_close; sl_price = entry_price * 1.02; tp_price = entry_price * 0.98
                else:
                    ema20 = df['ema20'].iloc[i]
                    ema50 = df['ema50'].iloc[i]
                    high20_prev = df['high20_prev'].iloc[i]
                    low20_prev = df['low20_prev'].iloc[i]
                    
                    if pd.isna(ema20) or pd.isna(ema50):
                        continue
                    
                    if c_close > ema20 > ema50 and rsi_val < 70:
                        position = "LONG"; active_strategy = "TREND_FOLLOWING"
                        entry_price = c_close; sl_price = entry_price * 0.98; tp_price = entry_price * 1.04
                    elif c_close < ema20 < ema50 and rsi_val > 30:
                        position = "SHORT"; active_strategy = "TREND_FOLLOWING"
                        entry_price = c_close; sl_price = entry_price * 1.02; tp_price = entry_price * 0.96
                    elif c_close > ema50 and abs(c_close - ema20) / c_close < 0.01 and 40 <= rsi_val <= 60:
                        position = "LONG"; active_strategy = "PULLBACK"
                        entry_price = c_close; sl_price = entry_price * 0.98; tp_price = entry_price * 1.04
                    elif not pd.isna(high20_prev) and c_close > high20_prev and rsi_val < 72:
                        position = "LONG"; active_strategy = "BREAKOUT"
                        entry_price = c_close; sl_price = entry_price * 0.985; tp_price = entry_price * 1.03
                    elif not pd.isna(low20_prev) and c_close < low20_prev and rsi_val > 28:
                        position = "SHORT"; active_strategy = "BREAKOUT"
                        entry_price = c_close; sl_price = entry_price * 1.015; tp_price = entry_price * 0.97
            
            details.append(f"✅ {symbol}: {len(df)} کندل.")
        
        return (results, details), None
    
    try:
        result, err = await asyncio.to_thread(run_bt)
        
        if err:
            await message.edit_text(f"❌ خطا: {err}")
            return
        
        results, details = result
        
        report = "📊 <b>نتیجه بک‌تست v24</b>\n\n"
        report += "".join(f"{d}\n" for d in details)
        report += f"\n📈 <b>آمار کلی</b>\n"
        report += "=" * 25 + "\n\n"
        
        sorted_results = []
        for name, data in results.items():
            total = data["wins"] + data["losses"]
            if total > 0:
                wr = (data["wins"] / total) * 100
                avg_r = data["r_sum"] / total
                sorted_results.append((name, total, data["wins"], data["losses"], wr, avg_r))
        
        sorted_results.sort(key=lambda x: x[4], reverse=True)
        
        for name, total, wins, losses, wr, avg_r in sorted_results:
            emoji = "🏆" if wr >= 55 else "✅" if wr >= 45 else "⚠️" if wr >= 35 else "❌"
            report += (
                f"{emoji} <b>{name}</b>\n"
                f"   📊 معاملات: {total} (✅{wins} / ❌{losses})\n"
                f"   🎯 وین‌ریت: <b>{wr:.1f}%</b>\n"
                f"   💰 میانگین R: <b>{avg_r:+.2f}R</b>\n\n"
            )
        
        report += "=" * 25 + "\n"
        report += "📌 وین‌ریت > 50٪ و R مثبت = سودده"
        
        await message.edit_text(report)
        
    except Exception as e:
        logger.exception("Backtest error")
        try:
            await message.edit_text(f"❌ خطای داخلی: {str(e)}")
        except Exception:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ خطای داخلی در بک‌تست: {str(e)}"
            )

# ============================================================
# MAIN
# ============================================================

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing.")

    logger.info("=" * 60)
    logger.info("CryptoBot starting...")
    logger.info("Symbols to scan: %s", len(SYMBOLS))
    logger.info("Automatic scan interval: %s seconds", AUTO_INTERVAL)
    logger.info("Tracker interval: %s seconds", TRACKER_INTERVAL)
    logger.info("Critical news window: %s minutes", NEWS_BLOCK_MINUTES)
    logger.info("Signal policy: HIGH quality, score >= 10")
    logger.info("Estimated PnL settings: margin %.2f USDT, leverage %sx", DEFAULT_MARGIN_USDT, DEFAULT_LEVERAGE)
    logger.info("=" * 60)

    application = Application.builder().token(TOKEN).build()

    # ---- Commands ----
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("signal", signal))
    application.add_handler(CommandHandler("register", register_chat))
    application.add_handler(CommandHandler("stats", tracker_stats))
    application.add_handler(CommandHandler("news", news_command))
    application.add_handler(CommandHandler("news_test", news_test_command))
    application.add_handler(CommandHandler("backtest", backtest_command))
    application.add_handler(CommandHandler("report", report_now))

    # ---- Repeating jobs ----
    application.job_queue.run_repeating(
        track_open_trades,
        interval=TRACKER_INTERVAL,
        first=TRACKER_INTERVAL,
        job_kwargs={"max_instances": 1, "coalesce": True},
    )
    logger.info("Trade tracker scheduled every %s seconds", TRACKER_INTERVAL)

    application.job_queue.run_repeating(
        auto_signal,
        interval=AUTO_INTERVAL,
        first=60,
        job_kwargs={"max_instances": 1, "coalesce": True},
    )
    logger.info("Automatic signal scanner scheduled every %s seconds", AUTO_INTERVAL)

    # ---- Daily report at 20:30 UTC (00:00 Tehran) ----
    application.job_queue.run_daily(
        daily_strategy_report,
        time=dt_time(hour=20, minute=30, tzinfo=timezone.utc),
        name="daily_strategy_report",
    )
    logger.info("Daily strategy report scheduled at 20:30 UTC (00:00 Tehran)")

    logger.info("CryptoBot started successfully.")
    application.run_polling(drop_pending_updates=True)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
