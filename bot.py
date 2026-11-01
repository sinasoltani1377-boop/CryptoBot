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
from tracker import (
    register_signal,
    check_all_trades,
    get_open_trades,
    get_all_trades,
    get_stats,
    get_stats_by_strategy,
    mark_trend_alert,
    force_close_trade,
    update_trade_meta,
)
from toobit_executor import (
    open_position as toobit_open,
    close_fraction as toobit_close,
    is_enabled as toobit_enabled,
)

# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")

TOOBIT_KLINES_URL = "https://api.toobit.com/quote/v1/klines"
TOOBIT_TICKER_URL = "https://api.toobit.com/quote/v1/contract/ticker/price"

AUTO_INTERVAL = 300
TRACKER_INTERVAL = 30
NEWS_BLOCK_MINUTES = 120
NEWS_FETCH_LIMIT = 50

DEFAULT_LEVERAGE = 20
DEFAULT_MARGIN_USDT = 1.0   # 1 dollar

SIGNAL_TIMEOUT_HOURS     = float(os.getenv("SIGNAL_TIMEOUT_HOURS", "48"))
TIMEOUT_CHECK_INTERVAL   = int(os.getenv("TIMEOUT_CHECK_INTERVAL", "600"))
TIMEOUT_ENABLED          = os.getenv("TIMEOUT_ENABLED", "1") == "1"
TIMEOUT_CLOSE_IF_TP1_HIT = os.getenv("TIMEOUT_CLOSE_IF_TP1_HIT", "0") == "1"
TIMEOUT_CLOSE_AT         = os.getenv("TIMEOUT_CLOSE_AT", "MARKET").upper()

_scan_lock = asyncio.Lock()

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

SYMBOLS = get_symbols()
INTERVALS = {"1d": "1d", "4h": "4h", "1h": "1h", "15m": "15m", "5m": "5m"}

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
        if (candle["high"] < candle["low"] or candle["high"] <= 0
                or candle["low"] <= 0 or candle["close"] <= 0):
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
    entry = safe_number(entry); target = safe_number(target)
    leverage = safe_number(leverage); margin = safe_number(margin)
    if (entry is None or target is None or leverage is None or margin is None
            or entry <= 0 or target <= 0 or leverage <= 0 or margin <= 0):
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
    entry = result.get("entry"); direction = result.get("direction")
    roi = {}
    for label in ("tp1", "tp2", "tp3", "sl"):
        roi[label] = calculate_trade_roi(direction, entry, result.get(label))
    result["leverage_roi"] = roi
    return result

def roi_line(label, roi_data):
    if not isinstance(roi_data, dict):
        return f"{label}: N/A"
    roi = safe_number(roi_data.get("roi_pct")); pnl = safe_number(roi_data.get("pnl_usdt"))
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
MACRO_TERMS = ("ppi", "cpi", "inflation", "producer price", "consumer price", "federal reserve",
               "federal funds rate", "interest rate", "fed decision", "rate decision")
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
BULLISH_CRITICAL_TERMS = ("spot bitcoin etf approved", "spot ethereum etf approved",
                          "sec approves spot etf", "unexpected rate cut", "fed cuts rates")
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
    if contains_any(text, MACRO_TERMS) and contains_any(text, MACRO_SURPRISE_TERMS):
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
            conflict = ((direction == "LONG" and direction_of_news == "BEARISH")
                        or (direction == "SHORT" and direction_of_news == "BULLISH"))
            if not conflict:
                continue
            title = str(article.get("title") or "Critical news")
            return True, f"⛔ سیگنال به دلیل خبر بحرانی مسدود شد.\nجهت معامله: {direction}\nجهت خبر: {direction_of_news}\nخبر: {title}"
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
            return True
        same_dir_count = sum(1 for t in open_trades if str(t.get("direction", "")).upper() == direction)
        if same_dir_count >= 2:
            return True
        for trade in open_trades:
            if (trade.get("symbol") == symbol
                    and str(trade.get("direction", "")).upper() == direction):
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
            return False
    entry = float(result["entry"]); sl = float(result["sl"])
    tp1 = float(result["tp1"]); tp2 = float(result["tp2"]); tp3 = float(result["tp3"])
    if direction == "LONG":
        return sl < entry < tp1 <= tp2 <= tp3
    return sl > entry > tp1 >= tp2 >= tp3

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

    extra = {}
    if toobit_enabled():
        ex = toobit_open(symbol, direction, result["entry"])
        if not ex:
            logger.warning("EXECUTOR | OPEN FAILED | %s | %s", symbol, direction)
            return None
        extra = {
            "toobit_order_id": ex["order_id"],
            "toobit_amount": ex["amount"],
            "toobit_leverage": ex["leverage"],
            "toobit_margin": ex["margin_usdt"],
            "toobit_closed_fraction": 0.0,
        }
        logger.info("EXECUTOR | OPENED | %s | %s | amt=%s", symbol, direction, ex["amount"])

    try:
        registered = register_signal(payload, extra=extra)
        if not registered:
            logger.error("TRACKER REGISTRATION FAILED AFTER OPEN | %s | %s", symbol, direction)
            return None
        return payload
    except Exception:
        logger.exception("TRACKER_REGISTER_ERROR | %s", symbol)
        return None

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
            alignment_text = "🚨 " + alignment_text
    else:
        alignment_text = "➖ روند بیت‌کوین خنثی"

    return (
        f"{emoji} <b>{safe_text(symbol)}</b>\n\n"
        f"🎯 Signal: <b>{safe_text(direction)}</b>\n"
        f"⭐ Quality: <b>{safe_text(result.get('quality'))}</b>\n"
        f"📊 Score: <b>{safe_text(result.get('score'))}</b>\n\n"
        f"📅 Daily: {safe_text(result.get('daily'))}\n"
        f"⏱ 4H: {safe_text(result.get('4h'))}\n"
        f"🕐 1H: {safe_text(result.get('1h'))}\n\n"
        f"₿ BTC: <b>{safe_text(btc_dir)}</b>\n{alignment_text}\n\n"
        f"💰 Entry: <b>{display_number(result.get('entry'))}</b>\n"
        f"🛑 SL: <b>{display_number(result.get('sl'))}</b>\n"
        f"🎯 TP1: <b>{display_number(result.get('tp1'))}</b>\n"
        f"🎯 TP2: <b>{display_number(result.get('tp2'))}</b>\n"
        f"🎯 TP3: <b>{display_number(result.get('tp3'))}</b>\n\n"
        f"⚖️ RR: {safe_text(result.get('rr'))}\n\n"
        f"💵 Margin: {DEFAULT_MARGIN_USDT:.2f} USDT\n"
        f"⚡ Leverage: {DEFAULT_LEVERAGE}x\n"
        f"📈 تخمین PnL:\n"
        f"  {roi_line('TP1', roi.get('tp1'))}\n"
        f"  {roi_line('TP2', roi.get('tp2'))}\n"
        f"  {roi_line('TP3', roi.get('tp3'))}\n"
        f"  {roi_line('SL', roi.get('sl'))}\n\n"
        f"🧠 Strategy:\n<b>{safe_text(strategy_text)}</b>\n\n"
        f"📰 News:\n{safe_text(news_note)}"
    )

# ============================================================
# SIGNAL PREPARATION
# ============================================================

def analyze_symbol_raw(symbol, btc_context):
    market_data = get_market_data(symbol)
    if market_data is None:
        return None
    result = generate_signal(
        market_data["1d"], market_data["4h"], market_data["1h"],
        market_data["15m"], market_data["5m"], btc_context=btc_context
    )
    if not isinstance(result, dict):
        return None
    return result

async def prepare_signal(symbol, btc_context):
    result = await asyncio.to_thread(analyze_symbol_raw, symbol, btc_context)
    if result is None:
        return None, False, "No analysis result"
    if not is_valid_high_signal(result):
        return result, False, "Not valid HIGH"
    blocked, news_note = await check_critical_news(symbol, result.get("direction"))
    if blocked:
        return result, True, news_note
    result["_news_note"] = news_note
    result = await asyncio.to_thread(add_signal_context, result)
    return result, False, news_note

# ============================================================
# COMMANDS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_ids = context.application.bot_data.setdefault("chat_ids", set())
    chat_ids.add(update.effective_chat.id)
    timeout_status = (
        f"⏱ تایم‌اوت: {SIGNAL_TIMEOUT_HOURS:.0f} ساعت"
        if TIMEOUT_ENABLED else "⏱ تایم‌اوت: غیرفعال"
    )
    toobit_status = "🔵 Toobit: فعال" if toobit_enabled() else "⚪ Toobit: غیرفعال"
    await update.effective_message.reply_text(
        f"🤖 CryptoBot فعال است.\n"
        f"📊 ارزهای اسکن: {len(SYMBOLS)}\n"
        f"{timeout_status}\n{toobit_status}\n\n"
        "دستورات:\n"
        "/price /signal /register /stats /open /close /news /report"
    )

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    btc = await asyncio.to_thread(get_price, "BTC-SWAP-USDT")
    sol = await asyncio.to_thread(get_price, "SOL-SWAP-USDT")
    msg = "💰 <b>Prices</b>\n\n"
    msg += f"₿ BTC: <b>{display_number(btc)}</b>\n" if btc else "₿ BTC: unavailable\n"
    msg += f"◎ SOL: <b>{display_number(sol)}</b>\n" if sol else "◎ SOL: unavailable\n"
    await update.effective_message.reply_text(msg, parse_mode="HTML")

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f"🔎 بررسی {len(SYMBOLS)} ارز...")
    btc_context = await asyncio.to_thread(fetch_btc_context, get_klines)
    found = blocked_by_news = registration_failed = 0
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
            await update.effective_message.reply_text(signal_text(symbol, result), parse_mode="HTML")
            found += 1
        except Exception:
            logger.exception("Signal error %s", symbol)
    if found == 0:
        await update.effective_message.reply_text(
            f"⏳ سیگنال HIGH جدیدی نیست.\n"
            f"⛔ مسدود خبر: {blocked_by_news}\n"
            f"📌 ثبت ناموفق: {registration_failed}"
        )

async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    if _scan_lock.locked():
        return
    async with _scan_lock:
        btc_context = await asyncio.to_thread(fetch_btc_context, get_klines)
        found = 0
        for symbol in SYMBOLS:
            try:
                result, blocked, note = await prepare_signal(symbol, btc_context)
                if result is None or blocked or not is_valid_high_signal(result):
                    continue
                trade = register_high_signal(symbol, result)
                if trade is None:
                    continue
                found += 1
                chat_ids = context.application.bot_data.get("chat_ids", set())
                for chat_id in list(chat_ids):
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id, text=signal_text(symbol, result), parse_mode="HTML"
                        )
                    except Exception:
                        logger.exception("Telegram send error")
            except Exception:
                logger.exception("Auto scan error %s", symbol)

async def track_open_trades(context: ContextTypes.DEFAULT_TYPE):
    try:
        open_trades = await asyncio.to_thread(get_open_trades)
        if not open_trades:
            return
        events = await asyncio.to_thread(check_all_trades, get_price)
        if not events:
            return
        chat_ids = context.application.bot_data.get("chat_ids", set())
        for event in events:
            event_name = str(event.get("event", "UNKNOWN")).upper()
            symbol = event.get("symbol", "UNKNOWN")
            direction = event.get("direction", "UNKNOWN")

            # 🔵 بستن روی صرافی Toobit
            if toobit_enabled():
                trade_id = event.get("id")
                if trade_id:
                    all_trades = await asyncio.to_thread(get_all_trades)
                    tr = next((t for t in all_trades if t.get("id") == trade_id), None)
                    if tr:
                        toobit_amt = float(tr.get("toobit_amount") or 0)
                        realized = float(tr.get("realized_fraction") or 0)
                        already = float(tr.get("toobit_closed_fraction") or 0)
                        to_close = max(0.0, realized - already)
                        if toobit_amt > 0 and to_close > 0:
                            px = float(event.get("price") or event.get("entry") or 0)
                            if px > 0:
                                ok = await asyncio.to_thread(
                                    toobit_close, symbol, direction, toobit_amt, to_close, px,
                                )
                                if ok:
                                    await asyncio.to_thread(
                                        update_trade_meta, trade_id,
                                        {"toobit_closed_fraction": realized},
                                    )
                                    logger.info("EXECUTOR | CLOSED %.0f%% | %s | %s", to_close*100, symbol, event_name)

            title_map = {
                "TP1": "🎯 TP1 لمس شد", "TP2": "🎯 TP2 لمس شد",
                "TP3": "🏆 TP3 لمس شد", "SL": "🛑 SL لمس شد",
                "BREAKEVEN": "⚖️ Breakeven", "TP1_PROTECTED": "✅ TP1 Protected",
            }
            title = title_map.get(event_name, f"📊 {event_name}")
            pnl = safe_number(event.get("realized_pnl"), 0.0)
            roi = safe_number(event.get("roi_percent"), 0.0)
            message = (
                f"<b>{title}</b>\n\n"
                f"🪙 {safe_text(symbol)}\n"
                f"📈 {safe_text(direction)}\n\n"
                f"💰 Price: {display_number(event.get('price'))}\n"
                f"📌 Entry: {display_number(event.get('entry'))}\n"
                f"💹 PnL: {pnl:+.4f} USDT\n"
                f"📊 ROI: {roi:+.2f}%"
            )
            for chat_id in list(chat_ids):
                try:
                    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
                except Exception:
                    logger.exception("Tracker send error")
    except Exception:
        logger.exception("Tracker error")

async def register_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_ids = context.application.bot_data.setdefault("chat_ids", set())
    chat_ids.add(update.effective_chat.id)
    await update.effective_message.reply_text("✅ ثبت شد.")

async def tracker_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stats = await asyncio.to_thread(get_stats)
        message = (
            "📊 <b>Stats</b>\n\n"
            f"📌 Total: {stats.get('total', 0)}\n"
            f"⏳ Open: {stats.get('open', 0)}\n"
            f"🔒 Closed: {stats.get('closed', 0)}\n\n"
            f"🎯 TP1: {stats.get('tp1', 0)} | TP2: {stats.get('tp2', 0)} | TP3: {stats.get('tp3', 0)}\n"
            f"🛑 SL: {stats.get('sl', 0)} | ⚖️ BE: {stats.get('breakeven', 0)}\n\n"
            f"💵 PnL: {stats.get('realized_pnl', 0):+.4f} USDT\n"
            f"📈 ROI: {stats.get('realized_roi', 0):+.2f}%"
        )
        await update.effective_message.reply_text(message, parse_mode="HTML")
    except Exception:
        logger.exception("Stats error")
        await update.effective_message.reply_text("❌ خطا در آمار.")

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await update.effective_message.reply_text("📰 دریافت اخبار...")
    try:
        articles = await get_latest_news(limit=8)
        if not articles:
            await message.edit_text("⚠️ خبری نیست.")
            return
        lines = ["📰 اخبار کریپتو\n"]
        for i, a in enumerate(articles, 1):
            imp = a.get("importance", "NORMAL")
            emoji = {"CRITICAL": "🔴", "HIGH": "🟠"}.get(imp, "🟢")
            lines.append(f"{i}. {emoji} {a.get('title', 'بدون عنوان')}\n")
        await message.edit_text("\n".join(lines), disable_web_page_preview=True)
    except Exception:
        logger.exception("News error")
        await message.edit_text("❌ خطا در اخبار.")

async def report_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("⏳ ساخت گزارش...")
    await daily_strategy_report(context)

async def daily_strategy_report(context: ContextTypes.DEFAULT_TYPE):
    try:
        strategy_stats = await asyncio.to_thread(get_stats_by_strategy)
        overall = await asyncio.to_thread(get_stats)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not strategy_stats:
            message = f"📊 گزارش {today}\nهنوز معامله‌ای نیست."
        else:
            lines = [f"📊 <b>گزارش استراتژی‌ها — {today}</b>", ""]
            for name, s in sorted(strategy_stats.items(), key=lambda x: x[1]["total"], reverse=True):
                emoji = "🏆" if s["realized_pnl"] > 0 else "❌" if s["realized_pnl"] < 0 else "⚖️"
                lines.append(f"{emoji} <b>{name}</b>")
                lines.append(f"  کل: {s['total']} | باز: {s['open']} | بسته: {s['closed']}")
                lines.append(f"  TP1:{s['tp1']} TP2:{s['tp2']} TP3:{s['tp3']} SL:{s['sl']}")
                lines.append(f"  💰 PnL: <b>{s['realized_pnl']:+.4f} USDT</b>\n")
            lines.append("=" * 25)
            lines.append(f"💵 مجموع: {overall['realized_pnl']:+.4f} USDT")
            lines.append(f"📈 ROI: {overall['realized_roi']:+.2f}%")
            message = "\n".join(lines)
        chat_ids = context.application.bot_data.get("chat_ids", set())
        for chat_id in list(chat_ids):
            try:
                await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
            except Exception:
                logger.exception("Daily report error")
    except Exception:
        logger.exception("Daily report error")

async def open_trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = await asyncio.to_thread(get_open_trades)
    if not trades:
        await update.effective_message.reply_text("هیچ معامله باز نیست ✅")
        return
    lines = [f"📋 <b>Open ({len(trades)})</b>\n"]
    for t in trades:
        lines.append(
            f"#{t.get('id')}\n"
            f"  {t.get('symbol')} {t.get('direction')}\n"
            f"  Entry:{display_number(t.get('entry'))} SL:{display_number(t.get('sl'))}\n"
        )
    await update.effective_message.reply_text("\n".join(lines)[:4000], parse_mode="HTML")

async def close_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("فرمت: /close <id>")
        return
    trade_id = str(context.args[0]).strip().lstrip("#")
    open_trades = await asyncio.to_thread(get_open_trades)
    target = next((t for t in open_trades if str(t.get("id")) == trade_id), None)
    if target is None:
        await update.effective_message.reply_text(f"❌ پیدا نشد: {trade_id}")
        return
    symbol = target.get("symbol"); direction = target.get("direction")
    price_val = await asyncio.to_thread(get_price, symbol)
    if price_val is None:
        await update.effective_message.reply_text("❌ قیمت در دسترس نیست.")
        return
    closed = await asyncio.to_thread(force_close_trade, trade_id, price_val, "MANUAL_CLOSE")
    if not closed:
        await update.effective_message.reply_text("❌ بستن ناموفق.")
        return

    # 🔵 بستن روی صرافی
    if toobit_enabled():
        orig_amt = float(target.get("toobit_amount") or 0)
        if orig_amt > 0:
            already = float(target.get("toobit_closed_fraction") or 0)
            frac = max(0.0, 1.0 - already)
            if frac > 0:
                ok = await asyncio.to_thread(
                    toobit_close, symbol, direction, orig_amt, frac, price_val,
                )
                if ok:
                    await asyncio.to_thread(
                        update_trade_meta, trade_id, {"toobit_closed_fraction": 1.0}
                    )

    await update.effective_message.reply_text(
        f"🔒 <b>بسته شد</b>\n{safe_text(symbol)} {safe_text(direction)}\nPrice: {display_number(price_val)}",
        parse_mode="HTML",
    )

# ============================================================
# TIMEOUT CHECKER
# ============================================================

def _trade_age_hours(trade):
    created = trade.get("created_at")
    if not created:
        return None
    try:
        s = str(created).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return None

def _trade_tp1_hit(trade):
    return bool(trade.get("tp1_hit")) or (float(trade.get("realized_pnl") or 0) != 0)

async def check_signal_timeouts(context: ContextTypes.DEFAULT_TYPE):
    if not TIMEOUT_ENABLED:
        return
    try:
        open_trades = await asyncio.to_thread(get_open_trades)
    except Exception:
        return
    if not open_trades:
        return
    chat_ids = context.application.bot_data.get("chat_ids", set())
    for trade in open_trades:
        try:
            trade_id = trade.get("id")
            symbol = trade.get("symbol", "UNKNOWN")
            direction = str(trade.get("direction", "")).upper()
            if direction not in ("LONG", "SHORT"):
                continue
            if _trade_tp1_hit(trade) and not TIMEOUT_CLOSE_IF_TP1_HIT:
                continue
            age_hours = _trade_age_hours(trade)
            if age_hours is None or age_hours < SIGNAL_TIMEOUT_HOURS:
                continue
            current_price = await asyncio.to_thread(get_price, symbol)
            if current_price is None:
                continue
            entry_price = safe_number(trade.get("entry"))
            close_price = entry_price if TIMEOUT_CLOSE_AT == "ENTRY" and entry_price else current_price
            closed = await asyncio.to_thread(force_close_trade, trade_id, close_price, "TIMEOUT")
            if not closed:
                continue

            # 🔵 بستن روی صرافی
            if toobit_enabled():
                orig_amt = float(trade.get("toobit_amount") or 0)
                if orig_amt > 0:
                    already = float(trade.get("toobit_closed_fraction") or 0)
                    frac = max(0.0, 1.0 - already)
                    if frac > 0:
                        await asyncio.to_thread(
                            toobit_close, symbol, direction, orig_amt, frac, close_price,
                        )
                        await asyncio.to_thread(
                            update_trade_meta, trade_id, {"toobit_closed_fraction": 1.0}
                        )

            for chat_id in list(chat_ids):
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⌛ <b>تایم‌اوت</b>\n{safe_text(symbol)} {safe_text(direction)}\n"
                             f"⏱ {age_hours:.1f}h | Close: {display_number(close_price)}",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.exception("Timeout send error")
        except Exception:
            logger.exception("Timeout trade error")

# ============================================================
# BTC TREND ALERTS
# ============================================================

async def check_btc_trend_changes(context: ContextTypes.DEFAULT_TYPE):
    try:
        open_trades = await asyncio.to_thread(get_open_trades)
        if not open_trades:
            return
        btc_context = await asyncio.to_thread(fetch_btc_context, get_klines)
        current_h1 = btc_context.get("h1") or "RANGE"
        current_adx = float(btc_context.get("adx_h1") or 0.0)
        chat_ids = context.application.bot_data.get("chat_ids", set())
        for trade in open_trades:
            if trade.get("trend_change_alerted"):
                continue
            direction = str(trade.get("direction", "")).upper()
            if direction not in ("LONG", "SHORT"):
                continue
            expected = "BULLISH" if direction == "LONG" else "BEARISH"
            if current_h1 in ("BULLISH", "BEARISH") and current_h1 != expected and current_adx >= 22:
                symbol = trade.get("symbol", "UNKNOWN")
                for chat_id in list(chat_ids):
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"🚨 <b>تغییر روند BTC</b>\n{safe_text(symbol)} {safe_text(direction)}\n"
                                 f"BTC 1H: {current_h1} (ADX: {current_adx:.1f})",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                await asyncio.to_thread(mark_trend_alert, trade.get("id"))
    except Exception:
        logger.exception("BTC trend error")

# ============================================================
# MAIN
# ============================================================

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is missing.")

    logger.info("=" * 60)
    logger.info("CryptoBot starting...")
    logger.info("Symbols: %s", len(SYMBOLS))
    logger.info("Margin: %.2f USDT | Leverage: %sx", DEFAULT_MARGIN_USDT, DEFAULT_LEVERAGE)
    logger.info("Toobit enabled: %s", toobit_enabled())
    logger.info("Timeout: %s h", SIGNAL_TIMEOUT_HOURS if TIMEOUT_ENABLED else "disabled")
    logger.info("=" * 60)

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("signal", signal))
    application.add_handler(CommandHandler("register", register_chat))
    application.add_handler(CommandHandler("stats", tracker_stats))
    application.add_handler(CommandHandler("news", news_command))
    application.add_handler(CommandHandler("report", report_now))
    application.add_handler(CommandHandler("open", open_trades_command))
    application.add_handler(CommandHandler("close", close_command))

    application.job_queue.run_repeating(
        track_open_trades, interval=TRACKER_INTERVAL, first=TRACKER_INTERVAL,
        job_kwargs={"max_instances": 1, "coalesce": True},
    )
    application.job_queue.run_repeating(
        auto_signal, interval=AUTO_INTERVAL, first=60,
        job_kwargs={"max_instances": 1, "coalesce": True},
    )
    application.job_queue.run_repeating(
        check_btc_trend_changes, interval=300, first=120,
        job_kwargs={"max_instances": 1, "coalesce": True},
    )
    if TIMEOUT_ENABLED:
        application.job_queue.run_repeating(
            check_signal_timeouts, interval=TIMEOUT_CHECK_INTERVAL, first=240,
            job_kwargs={"max_instances": 1, "coalesce": True},
        )
    application.job_queue.run_daily(
        daily_strategy_report,
        time=dt_time(hour=20, minute=30, tzinfo=timezone.utc),
    )

    logger.info("CryptoBot started.")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
