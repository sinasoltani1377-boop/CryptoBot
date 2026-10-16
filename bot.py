import os
import logging
import asyncio
import requests

from datetime import datetime, timezone

from news import get_latest_news, news_diagnostics

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from analysis import generate_signal
from market import get_futures_symbols

from tracker import (
    register_signal,
    check_all_trades,
    get_open_trades,
    get_stats,
)


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")

TOOBIT_KLINES_URL = (
    "https://api.toobit.com/quote/v1/klines"
)

TOOBIT_TICKER_URL = (
    "https://api.toobit.com/quote/v1/contract/ticker/price"
)

TOOBIT_TICKER_24H_URL = (
    "https://api.toobit.com/quote/v1/contract/ticker/24hr"
)

AUTO_INTERVAL = 300
TRACKER_INTERVAL = 30

MIN_VOLUME_USDT = 50_000_000
MAX_SYMBOLS = 30

NEWS_BLOCK_MINUTES = 120
NEWS_FETCH_LIMIT = 50

_scan_lock = asyncio.Lock()


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format=(
        "%(asctime)s - %(name)s - "
        "%(levelname)s - %(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# SYMBOLS
# ============================================================

def load_symbols(
    min_volume_usdt=10_000_000,
    max_symbols=30,
):
    try:
        all_symbols = get_futures_symbols()

        if not all_symbols:
            logger.warning(
                "No symbols returned from Toobit"
            )
            return []

        logger.info(
            "Fetched %s symbols from Toobit",
            len(all_symbols),
        )

        candidates = []

        for symbol in all_symbols:
            try:
                response = requests.get(
                    TOOBIT_TICKER_24H_URL,
                    params={"symbol": symbol},
                    timeout=5,
                )

                if response.status_code != 200:
                    continue

                data = response.json()
                volume = 0.0

                if isinstance(data, dict):
                    raw = (
                        data.get("quoteVolume")
                        or data.get("volume")
                        or data.get("q")
                        or data.get("v")
                        or 0
                    )

                    volume = float(raw) if raw else 0.0

                elif isinstance(data, list):
                    for item in data:
                        if not isinstance(item, dict):
                            continue

                        item_symbol = (
                            item.get("symbol")
                            or item.get("s")
                        )

                        if (
                            item_symbol
                            and item_symbol != symbol
                        ):
                            continue

                        raw = (
                            item.get("quoteVolume")
                            or item.get("volume")
                            or item.get("q")
                            or item.get("v")
                            or 0
                        )

                        volume = (
                            float(raw) if raw else 0.0
                        )
                        break

                if volume >= min_volume_usdt:
                    candidates.append(
                        (symbol, volume)
                    )

            except Exception:
                logger.debug(
                    "Volume check failed for %s",
                    symbol,
                    exc_info=True,
                )
                continue

        candidates.sort(
            key=lambda item: item[1],
            reverse=True,
        )

        selected = [
            symbol
            for symbol, _ in candidates[:max_symbols]
        ]

        logger.info(
            "Filtered %s/%s symbols, selected top %s",
            len(candidates),
            len(all_symbols),
            len(selected),
        )

        if selected:
            return selected

        logger.warning(
            "No symbols passed liquidity filter. "
            "Using fallback symbols."
        )

    except Exception:
        logger.exception("Failed to load symbols")

    return [
        "BTC-SWAP-USDT",
        "ETH-SWAP-USDT",
        "SOL-SWAP-USDT",
        "BNB-SWAP-USDT",
        "XRP-SWAP-USDT",
        "DOGE-SWAP-USDT",
        "ADA-SWAP-USDT",
        "AVAX-SWAP-USDT",
        "LINK-SWAP-USDT",
        "DOT-SWAP-USDT",
    ]


SYMBOLS = load_symbols(
    min_volume_usdt=MIN_VOLUME_USDT,
    max_symbols=MAX_SYMBOLS,
)


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

def safe_number(value):
    try:
        if value is None:
            return None

        return float(value)

    except (TypeError, ValueError):
        return None


def normalize_candle(candle):
    if isinstance(candle, dict):
        return {
            "timestamp": (
                candle.get("timestamp")
                or candle.get("time")
                or candle.get("t")
            ),
            "open": safe_number(
                candle.get("open", candle.get("o"))
            ),
            "high": safe_number(
                candle.get("high", candle.get("h"))
            ),
            "low": safe_number(
                candle.get("low", candle.get("l"))
            ),
            "close": safe_number(
                candle.get("close", candle.get("c"))
            ),
            "volume": safe_number(
                candle.get("volume", candle.get("v"))
            ),
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
            "volume": (
                safe_number(candle[5])
                if len(candle) > 5
                else None
            ),
        }

    return None


def extract_candle_rows(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in (
            "data",
            "result",
            "rows",
            "klines",
            "candles",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for nested_key in (
                    "data",
                    "rows",
                    "klines",
                    "candles",
                ):
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

        required = (
            "open",
            "high",
            "low",
            "close",
        )

        if any(
            candle.get(key) is None
            for key in required
        ):
            continue

        candles.append(candle)

    return candles


# ============================================================
# TOOBIT MARKET DATA
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=200,
):
    try:
        response = requests.get(
            TOOBIT_KLINES_URL,
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            },
            timeout=15,
        )

        response.raise_for_status()

        candles = normalize_candles(
            response.json()
        )

        if len(candles) < 50:
            logger.warning(
                "%s %s: insufficient candles: %s",
                symbol,
                interval,
                len(candles),
            )
            return []

        return candles

    except Exception:
        logger.exception(
            "Kline error %s %s",
            symbol,
            interval,
        )
        return []


def get_market_data(symbol):
    daily = get_klines(symbol, INTERVALS["1d"], 200)
    h4 = get_klines(symbol, INTERVALS["4h"], 200)
    h1 = get_klines(symbol, INTERVALS["1h"], 200)
    m15 = get_klines(symbol, INTERVALS["15m"], 200)
    m5 = get_klines(symbol, INTERVALS["5m"], 200)

    if not all((daily, h4, h1, m15, m5)):
        logger.warning(
            "MARKET_DATA_INCOMPLETE | %s",
            symbol,
        )
        return None

    return {
        "1d": daily,
        "4h": h4,
        "1h": h1,
        "15m": m15,
        "5m": m5,
    }


# ============================================================
# PRICE
# ============================================================

def get_price(symbol):
    try:
        response = requests.get(
            TOOBIT_TICKER_URL,
            params={"symbol": symbol},
            timeout=10,
        )

        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            price_value = (
                data.get("p")
                or data.get("price")
                or data.get("lastPrice")
                or data.get("last")
            )

            if price_value is not None:
                return float(price_value)

        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue

                item_symbol = (
                    item.get("symbol")
                    or item.get("s")
                )

                if (
                    item_symbol is not None
                    and item_symbol != symbol
                ):
                    continue

                price_value = (
                    item.get("p")
                    or item.get("price")
                    or item.get("lastPrice")
                    or item.get("last")
                )

                if price_value is not None:
                    return float(price_value)

        logger.warning(
            "PRICE API | %s | Price not found",
            symbol,
        )

        return None

    except Exception:
        logger.exception("Price error %s", symbol)
        return None


# ============================================================
# CRITICAL NEWS FILTER
# ============================================================

BEARISH_NEWS_TERMS = (
    "market crash",
    "crypto crash",
    "bitcoin crashes",
    "bitcoin plunges",
    "market plunges",
    "liquidation cascade",
    "flash crash",
    "stablecoin depeg",
    "stablecoin collapse",
    "exchange hacked",
    "exchange hack",
    "major crypto hack",
    "security breach",
    "bankruptcy",
    "insolvency",
    "etf rejected",
    "etf rejection",
    "sec rejects",
    "higher than expected",
    "hotter than expected",
    "above expectations",
    "above forecast",
    "unexpectedly high",
    "inflation accelerates",
    "inflation hotter",
    "ppi jumps",
    "cpi jumps",
    "producer prices surge",
    "inflation surges",
)

BULLISH_NEWS_TERMS = (
    "market-wide rally",
    "crypto market surges",
    "bitcoin surges",
    "bitcoin rallies",
    "lower than expected inflation",
    "cooler than expected",
    "below expectations",
    "below forecast",
    "inflation cools",
    "inflation slows",
    "unexpected rate cut",
    "fed cuts rates",
    "spot bitcoin etf approved",
    "spot ethereum etf approved",
    "sec approves spot etf",
)

MACRO_TERMS = (
    "ppi",
    "cpi",
    "inflation",
    "producer price",
    "consumer price",
    "federal reserve",
    "federal funds rate",
    "interest rate",
    "fed decision",
    "rate decision",
)

MACRO_SURPRISE_TERMS = (
    "higher than expected",
    "hotter than expected",
    "above expectations",
    "above forecast",
    "unexpectedly high",
    "inflation accelerates",
    "inflation hotter",
    "ppi jumps",
    "cpi jumps",
    "producer prices surge",
    "lower than expected inflation",
    "cooler than expected",
    "below expectations",
    "below forecast",
    "inflation cools",
    "inflation slows",
    "unexpected rate cut",
)

CRITICAL_EVENT_TERMS = (
    "exchange hacked",
    "exchange hack",
    "major crypto hack",
    "security breach",
    "stablecoin depeg",
    "stablecoin collapse",
    "liquidation cascade",
    "flash crash",
    "market crash",
    "crypto crash",
    "bitcoin plunges",
    "bitcoin crashes",
    "bankruptcy",
    "insolvency",
)

BULLISH_CRITICAL_TERMS = (
    "spot bitcoin etf approved",
    "spot ethereum etf approved",
    "sec approves spot etf",
    "unexpected rate cut",
    "fed cuts rates",
)

BEARISH_CRITICAL_TERMS = (
    "etf rejected",
    "etf rejection",
    "sec rejects",
    "market crash",
    "crypto crash",
    "bitcoin plunges",
    "bitcoin crashes",
    "liquidation cascade",
    "flash crash",
    "stablecoin depeg",
    "stablecoin collapse",
    "exchange hacked",
    "exchange hack",
    "major crypto hack",
    "security breach",
    "bankruptcy",
    "insolvency",
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
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed.astimezone(timezone.utc)

    except (TypeError, ValueError):
        return None


def article_text(article):
    title = str(article.get("title") or "")
    summary = str(article.get("summary") or "")

    return f"{title} {summary}".lower()


def contains_any(text, terms):
    return any(
        term in text
        for term in terms
    )


def is_market_wide_news(text):
    market_terms = (
        "crypto market",
        "cryptocurrency market",
        "global crypto",
        "bitcoin crash",
        "bitcoin plunges",
        "market crash",
        "crypto crash",
        "liquidation cascade",
        "flash crash",
        "federal reserve",
        "interest rate",
        "rate decision",
        "inflation",
        "producer price",
        "consumer price",
        "ppi",
        "cpi",
    )

    return contains_any(
        text,
        market_terms,
    )


def news_direction(text):
    bearish = contains_any(
        text,
        BEARISH_NEWS_TERMS,
    )

    bullish = contains_any(
        text,
        BULLISH_NEWS_TERMS,
    )

    if bearish and not bullish:
        return "BEARISH"

    if bullish and not bearish:
        return "BULLISH"

    return None


def is_critical_news(text, importance):
    if contains_any(
        text,
        CRITICAL_EVENT_TERMS,
    ):
        return True

    macro_news = contains_any(
        text,
        MACRO_TERMS,
    )

    macro_surprise = contains_any(
        text,
        MACRO_SURPRISE_TERMS,
    )

    if macro_news and macro_surprise:
        return True

    if contains_any(
        text,
        BULLISH_CRITICAL_TERMS,
    ):
        return True

    if contains_any(
        text,
        BEARISH_CRITICAL_TERMS,
    ):
        return True

    return (
        importance == "CRITICAL"
        and news_direction(text) is not None
    )


def news_applies_to_symbol(
    article,
    symbol,
    text,
):
    if is_market_wide_news(text):
        return True

    asset = str(
        article.get("asset") or "UNKNOWN"
    ).upper()

    symbol_upper = symbol.upper()

    if asset == "MARKET":
        return True

    if asset == "BTC":
        return "BTC" in symbol_upper

    if asset == "ETH":
        return "ETH" in symbol_upper

    return False


async def check_critical_news(
    symbol,
    direction,
):
    """
    فقط خبر بحرانی، تازه، مرتبط و متناقض می‌تواند
    سیگنال را مسدود کند.

    اگر منابع خبری از کار بیفتند، فیلتر به‌صورت
    fail-open عمل می‌کند و سیگنال را به خاطر
    خطای خبر مسدود نمی‌کند.
    """

    if direction not in ("LONG", "SHORT"):
        return (
            False,
            "News filter skipped: invalid direction.",
        )

    try:
        articles = await get_latest_news(
            limit=NEWS_FETCH_LIMIT
        )

        if not articles:
            logger.warning(
                "NEWS_FILTER_UNAVAILABLE | %s | "
                "No articles received",
                symbol,
            )

            return (
                False,
                "⚠️ اخبار در دسترس نیست؛ "
                "فیلتر خبری نتوانست بررسی کامل انجام دهد.",
            )

        now = datetime.now(timezone.utc)

        for article in articles:
            if not isinstance(article, dict):
                continue

            published_at = article_datetime(
                article
            )

            if published_at is None:
                continue

            age_minutes = (
                now - published_at
            ).total_seconds() / 60

            if age_minutes < 0:
                continue

            if age_minutes > NEWS_BLOCK_MINUTES:
                continue

            text = article_text(article)

            importance = str(
                article.get("importance") or "NORMAL"
            ).upper()

            if not is_critical_news(
                text,
                importance,
            ):
                continue

            if not news_applies_to_symbol(
                article,
                symbol,
                text,
            ):
                continue

            direction_of_news = news_direction(
                text
            )

            if direction_of_news is None:
                continue

            conflict = (
                direction == "LONG"
                and direction_of_news == "BEARISH"
            ) or (
                direction == "SHORT"
                and direction_of_news == "BULLISH"
            )

            if not conflict:
                continue

            title = str(
                article.get("title")
                or "Critical news"
            )

            source = str(
                article.get("source")
                or "Unknown"
            )

            logger.warning(
                "SIGNAL_BLOCKED_BY_NEWS | "
                "%s | Direction=%s | "
                "NewsDirection=%s | "
                "AgeMinutes=%.1f | Source=%s | "
                "Title=%s",
                symbol,
                direction,
                direction_of_news,
                age_minutes,
                source,
                title,
            )

            return (
                True,
                (
                    "⛔ سیگنال به دلیل خبر بحرانی "
                    "متناقض مسدود شد.\n"
                    f"جهت معامله: {direction}\n"
                    f"جهت خبر: {direction_of_news}\n"
                    f"خبر: {title}"
                ),
            )

        logger.info(
            "NEWS_FILTER_PASS | %s | Direction=%s",
            symbol,
            direction,
        )

        return (
            False,
            "✅ خبر بحرانی متناقض شناسایی نشد.",
        )

    except Exception:
        logger.exception(
            "NEWS_FILTER_ERROR | %s",
            symbol,
        )

        return (
            False,
            "⚠️ فیلتر خبری موقتاً در دسترس نیست.",
        )


# ============================================================
# TRACKER HELPERS
# ============================================================

def already_tracking(symbol, direction):
    try:
        open_trades = get_open_trades()

        for trade in open_trades:
            if (
                trade.get("symbol") == symbol
                and trade.get("direction") == direction
            ):
                return True

        return False

    except Exception:
        logger.exception(
            "Tracker duplicate-check error"
        )
        return False


def register_high_signal(symbol, result):
    if not isinstance(result, dict):
        return None

    if result.get("quality") != "HIGH":
        return None

    direction = result.get("direction")

    if direction not in ("LONG", "SHORT"):
        return None

    if already_tracking(symbol, direction):
        logger.info(
            "TRACKER | ALREADY OPEN | %s | %s",
            symbol,
            direction,
        )
        return None

    trade = register_signal(
        symbol,
        result,
    )

    if trade:
        logger.info(
            "TRACKER | REGISTERED | %s | %s | "
            "Entry=%s | SL=%s | TP1=%s | "
            "TP2=%s | TP3=%s",
            symbol,
            direction,
            result.get("entry"),
            result.get("sl"),
            result.get("tp1"),
            result.get("tp2"),
            result.get("tp3"),
        )

    return trade


# ============================================================
# STRATEGY DIAGNOSTICS
# ============================================================

def log_strategy_details(symbol, result):
    diagnostics = result.get(
        "strategy_diagnostics"
    )

    if isinstance(diagnostics, dict):
        parts = []

        for strategy in (
            "TREND_FOLLOWING",
            "PULLBACK",
            "BREAKOUT",
            "REVERSAL",
            "RANGE_TRADING",
        ):
            value = diagnostics.get(strategy)

            if value is None:
                parts.append(
                    f"{strategy}=NO_DATA"
                )
                continue

            if isinstance(value, dict):
                matched = value.get("matched")

                reason = (
                    value.get("reason")
                    or value.get("blocked_reason")
                    or value.get("failure_reason")
                    or value.get("fail_reason")
                    or value.get("status")
                    or ""
                )

                status = (
                    "PASS"
                    if matched is True
                    else "FAIL"
                )

                if reason:
                    status = f"{status}:{reason}"

                parts.append(
                    f"{strategy}={status}"
                )

            elif isinstance(value, bool):
                parts.append(
                    f"{strategy}="
                    f"{'PASS' if value else 'FAIL'}"
                )

            else:
                parts.append(
                    f"{strategy}={value}"
                )

        logger.info(
            "STRATEGY_CHECK | %s | %s",
            symbol,
            " | ".join(parts),
        )
        return

    details = result.get("strategy_details")

    if not isinstance(details, dict):
        logger.info(
            "STRATEGY_CHECK | %s | "
            "No strategy diagnostics returned",
            symbol,
        )
        return

    parts = []

    for name, value in details.items():
        if isinstance(value, dict):
            matched = value.get(
                "matched",
                False,
            )

            direction = value.get("direction")

            reason = (
                value.get("reason")
                or value.get("blocked_reason")
                or value.get("failure_reason")
                or ""
            )

            if matched and direction:
                status = f"PASS({direction})"
            elif matched:
                status = "PASS"
            elif reason:
                status = f"FAIL:{reason}"
            else:
                status = "FAIL"

        else:
            status = (
                "PASS"
                if bool(value)
                else "FAIL"
            )

        parts.append(
            f"{name}={status}"
        )

    if parts:
        logger.info(
            "STRATEGY_CHECK | %s | %s",
            symbol,
            " | ".join(parts),
        )


# ============================================================
# FULL SIGNAL DIAGNOSTIC
# ============================================================

def log_signal_diagnostic(symbol, result):
    if not isinstance(result, dict):
        return

    daily = result.get("daily", "UNKNOWN")
    h4 = result.get("4h", "UNKNOWN")
    h1 = result.get("1h", "UNKNOWN")

    direction = result.get(
        "direction",
        "UNKNOWN",
    )

    signal_value = result.get(
        "signal",
        "UNKNOWN",
    )

    score = result.get(
        "score",
        "UNKNOWN",
    )

    quality = result.get(
        "quality",
        "UNKNOWN",
    )

    reason = (
        result.get("reason")
        or result.get("blocked_reason")
        or "UNKNOWN"
    )

    strategies = (
        result.get("strategy_matches")
        or result.get("strategies")
        or []
    )

    if isinstance(
        strategies,
        (list, tuple, set),
    ):
        strategies_text = (
            ", ".join(
                str(item)
                for item in strategies
            )
            if strategies
            else "NONE"
        )
    else:
        strategies_text = str(strategies)

    logger.info(
        "DIAGNOSTIC | %s | Daily=%s | 4H=%s | "
        "1H=%s | Direction=%s | Signal=%s | "
        "Score=%s | Quality=%s | Reason=%s | "
        "Strategies=%s",
        symbol,
        daily,
        h4,
        h1,
        direction,
        signal_value,
        score,
        quality,
        reason,
        strategies_text,
    )

    rsi_15m = result.get(
        "15m_rsi",
        result.get("rsi_15m"),
    )

    logger.info(
        "FILTERS | %s | 15M_RSI=%s | "
        "ADX_1H=%s | ADX_15M=%s | "
        "MTF_15M=%s | VolumeSpike=%s | "
        "Confirmation=%s",
        symbol,
        rsi_15m,
        result.get("adx_1h"),
        result.get("adx_15m"),
        result.get(
            "mtf_confirmation",
            result.get("mtf_confirmed"),
        ),
        result.get("volume_spike"),
        result.get("confirmation"),
    )

    log_strategy_details(
        symbol,
        result,
    )


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def signal_text(symbol, result):
    direction = result.get(
        "direction",
        "UNKNOWN",
    )

    if direction == "LONG":
        emoji = "🟢"
    elif direction == "SHORT":
        emoji = "🔴"
    else:
        emoji = "⚪"

    strategies = (
        result.get("strategy_matches")
        or result.get("strategies")
        or []
    )

    if not isinstance(
        strategies,
        (list, tuple),
    ):
        strategies = [strategies]

    strategy_text = (
        ", ".join(
            str(item)
            for item in strategies
        )
        if strategies
        else "NONE"
    )

    rsi_15m = result.get(
        "15m_rsi",
        result.get("rsi_15m"),
    )

    news_note = result.get(
        "_news_note",
        "بررسی نشده",
    )

    return (
        f"{emoji} <b>{symbol}</b>\n\n"
        f"🎯 Signal: <b>{result.get('signal')}</b>\n"
        f"⭐ Quality: <b>{result.get('quality')}</b>\n"
        f"📊 Score: <b>{result.get('score')}</b>\n\n"
        f"📅 Daily: {result.get('daily')}\n"
        f"⏱ 4H: {result.get('4h')}\n"
        f"🕐 1H: {result.get('1h')}\n"
        f"⏱ 15M RSI: {rsi_15m}\n"
        f"📊 ADX 1H: {result.get('adx_1h')}\n"
        f"📊 ADX 15M: {result.get('adx_15m')}\n"
        f"✅ MTF 15M: "
        f"{result.get('mtf_confirmation', result.get('mtf_confirmed'))}\n\n"
        f"💰 Entry: <b>{result.get('entry')}</b>\n"
        f"🛑 SL: <b>{result.get('sl')}</b>\n\n"
        f"🎯 TP1: <b>{result.get('tp1')}</b>\n"
        f"🎯 TP2: <b>{result.get('tp2')}</b>\n"
        f"🎯 TP3: <b>{result.get('tp3')}</b>\n\n"
        f"📏 Risk: {result.get('risk')}\n"
        f"⚖️ RR: {result.get('rr')}\n\n"
        f"🧠 Strategy:\n<b>{strategy_text}</b>\n\n"
        f"📝 Reason:\n{result.get('reason', 'N/A')}\n\n"
        f"📰 News Filter:\n{news_note}"
    )


# ============================================================
# RAW ANALYSIS
# ============================================================

def analyze_symbol_raw(symbol):
    market_data = get_market_data(symbol)

    if market_data is None:
        return None

    result = generate_signal(
        market_data["1d"],
        market_data["4h"],
        market_data["1h"],
        market_data["15m"],
        market_data["5m"],
    )

    if not isinstance(result, dict):
        logger.warning(
            "ANALYSIS_INVALID_RESULT | %s",
            symbol,
        )
        return None

    return result


# ============================================================
# COMMON SIGNAL VALIDATION
# ============================================================

def is_valid_high_signal(result):
    if not isinstance(result, dict):
        return False

    if result.get("quality") != "HIGH":
        return False

    if result.get("direction") not in (
        "LONG",
        "SHORT",
    ):
        return False

    if result.get("signal") not in (
        "LONG",
        "SHORT",
    ):
        return False

    if result.get("signal") != result.get("direction"):
        return False

    return True


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    chat_ids = context.application.bot_data.setdefault(
        "chat_ids",
        set(),
    )

    chat_ids.add(
        update.effective_chat.id
    )

    await update.effective_message.reply_text(
        f"🤖 CryptoBot فعال است.\n"
        f"📊 تعداد ارزهای در حال اسکن: {len(SYMBOLS)}\n\n"
        "دستورات:\n"
        "/price - قیمت BTC و SOL\n"
        "/signal - بررسی سیگنال‌های HIGH\n"
        "/register - دریافت سیگنال خودکار\n"
        "/stats - آمار تریدها\n"
        "/news - آخرین اخبار کریپتو\n"
        "/news_test - آزمایش منابع خبری"
    )


# ============================================================
# /PRICE
# ============================================================

async def price(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    btc = await asyncio.to_thread(
        get_price,
        "BTC-SWAP-USDT",
    )

    sol = await asyncio.to_thread(
        get_price,
        "SOL-SWAP-USDT",
    )

    message = "💰 <b>CryptoBot Prices</b>\n\n"

    if btc is not None:
        message += f"₿ BTC: <b>{btc}</b>\n"
    else:
        message += "₿ BTC: unavailable\n"

    if sol is not None:
        message += f"◎ SOL: <b>{sol}</b>\n"
    else:
        message += "◎ SOL: unavailable\n"

    await update.effective_message.reply_text(
        message,
        parse_mode="HTML",
    )


# ============================================================
# /SIGNAL
# ============================================================

async def signal(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.effective_message.reply_text(
        f"🔎 در حال بررسی {len(SYMBOLS)} ارز...\n"
        "Daily → 4H → 1H → 15M → 5M\n\n"
        "فقط سیگنال‌های HIGH نمایش داده می‌شوند.\n"
        "خبرهای بحرانی نیز بررسی می‌شوند.\n"
        "این کار ممکن است چند دقیقه طول بکشد."
    )

    found = 0
    blocked_by_news = 0

    for symbol in SYMBOLS:
        try:
            result = await asyncio.to_thread(
                analyze_symbol_raw,
                symbol,
            )

            if result is None:
                continue

            log_signal_diagnostic(
                symbol,
                result,
            )

            if not is_valid_high_signal(result):
                continue

            blocked, news_note = await check_critical_news(
                symbol,
                result.get("direction"),
            )

            if blocked:
                blocked_by_news += 1
                continue

            result["_news_note"] = news_note

            await update.effective_message.reply_text(
                signal_text(symbol, result),
                parse_mode="HTML",
            )

            found += 1

            trade = register_high_signal(
                symbol,
                result,
            )

            if trade is not None:
                logger.info(
                    "Manual signal registered | %s",
                    symbol,
                )

        except Exception:
            logger.exception(
                "Signal error %s",
                symbol,
            )

    if found == 0:
        await update.effective_message.reply_text(
            f"⏳ هیچ سیگنال HIGH قابل‌ارسالی "
            f"در {len(SYMBOLS)} ارز پیدا نشد.\n"
            f"⛔ مسدودشده توسط خبر: {blocked_by_news}\n\n"
            "🔍 جزئیات تشخیص در لاگ Belmo ثبت شد."
        )


# ============================================================
# AUTOMATIC SIGNAL SCANNER
# ============================================================

async def auto_signal(
    context: ContextTypes.DEFAULT_TYPE,
):
    if _scan_lock.locked():
        logger.warning(
            "Previous scan still running. Skipping."
        )
        return

    async with _scan_lock:
        logger.info(
            "Starting automatic market scan "
            "across %s symbols",
            len(SYMBOLS),
        )

        found = 0
        blocked_by_news = 0

        for symbol in SYMBOLS:
            try:
                result = await asyncio.to_thread(
                    analyze_symbol_raw,
                    symbol,
                )

                if result is None:
                    logger.warning(
                        "DIAGNOSTIC | %s | "
                        "No analysis result",
                        symbol,
                    )
                    continue

                log_signal_diagnostic(
                    symbol,
                    result,
                )

                if not is_valid_high_signal(result):
                    continue

                blocked, news_note = await check_critical_news(
                    symbol,
                    result.get("direction"),
                )

                if blocked:
                    blocked_by_news += 1
                    logger.warning(
                        "AUTO_SIGNAL_BLOCKED_BY_NEWS | %s",
                        symbol,
                    )
                    continue

                result["_news_note"] = news_note

                # ثبت فقط پس از عبور از فیلتر خبر
                trade = register_high_signal(
                    symbol,
                    result,
                )

                if trade is None:
                    logger.info(
                        "HIGH SIGNAL | %s | %s | "
                        "Already tracked or registration failed",
                        symbol,
                        result.get("direction"),
                    )
                    continue

                found += 1

                logger.info(
                    "NEW HIGH SIGNAL | %s | %s | "
                    "Score=%s | Strategy=%s",
                    symbol,
                    result.get("direction"),
                    result.get("score"),
                    result.get("strategy"),
                )

                chat_ids = context.application.bot_data.get(
                    "chat_ids",
                    set(),
                )

                for chat_id in list(chat_ids):
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=signal_text(
                                symbol,
                                result,
                            ),
                            parse_mode="HTML",
                        )

                    except Exception:
                        logger.exception(
                            "Telegram send error for chat %s",
                            chat_id,
                        )

            except Exception:
                logger.exception(
                    "Auto scan error %s",
                    symbol,
                )

        logger.info(
            "Automatic scan completed. "
            "New signals=%s | Blocked by news=%s",
            found,
            blocked_by_news,
        )


# ============================================================
# TRACK OPEN TRADES
# ============================================================

async def track_open_trades(
    context: ContextTypes.DEFAULT_TYPE,
):
    try:
        open_trades = await asyncio.to_thread(
            get_open_trades
        )

        if not open_trades:
            logger.info(
                "TRACKER CHECK | No open trades"
            )
            return

        logger.info(
            "TRACKER CHECK | Open trades=%s",
            len(open_trades),
        )

        events = await asyncio.to_thread(
            check_all_trades,
            get_price,
        )

        for trade in open_trades:
            symbol = trade.get(
                "symbol",
                "UNKNOWN",
            )

            direction = trade.get(
                "direction",
                "UNKNOWN",
            )

            current_price = await asyncio.to_thread(
                get_price,
                symbol,
            )

            logger.info(
                "TRACKER CHECK | %s | %s | "
                "Current=%s | Entry=%s | "
                "SL=%s | TP1=%s | TP2=%s | TP3=%s",
                symbol,
                direction,
                current_price,
                trade.get("entry"),
                trade.get("sl"),
                trade.get("tp1"),
                trade.get("tp2"),
                trade.get("tp3"),
            )

        if not events:
            return

        chat_ids = context.application.bot_data.get(
            "chat_ids",
            set(),
        )

        for event in events:
            trade = event.get("trade", {})
            event_name = event.get("event", "UNKNOWN")
            price_now = event.get("price")

            symbol = trade.get("symbol", "UNKNOWN")
            direction = trade.get("direction", "UNKNOWN")
            strategy_name = trade.get("strategy", "UNKNOWN")

            message = (
                "📊 <b>TRACKER UPDATE</b>\n\n"
                f"🪙 {symbol}\n"
                f"📈 Direction: <b>{direction}</b>\n"
                f"🧠 Strategy: <b>{strategy_name}</b>\n\n"
                f"💰 Current Price: <b>{price_now}</b>\n\n"
                f"📌 Entry: {trade.get('entry')}\n"
                f"🛑 SL: {trade.get('sl')}\n"
                f"🎯 TP1: {trade.get('tp1')}\n"
                f"🎯 TP2: {trade.get('tp2')}\n"
                f"🎯 TP3: {trade.get('tp3')}\n\n"
                f"📍 RESULT: <b>{event_name}</b>"
            )

            for chat_id in list(chat_ids):
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="HTML",
                    )

                except Exception:
                    logger.exception(
                        "Tracker Telegram error for chat %s",
                        chat_id,
                    )

            logger.info(
                "TRACKER | %s | %s | Price=%s",
                symbol,
                event_name,
                price_now,
            )

    except Exception:
        logger.exception("Tracker error")


# ============================================================
# /REGISTER
# ============================================================

async def register_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    chat_ids = context.application.bot_data.setdefault(
        "chat_ids",
        set(),
    )

    chat_ids.add(
        update.effective_chat.id
    )

    await update.effective_message.reply_text(
        "✅ این چت برای دریافت "
        "سیگنال‌های خودکار ثبت شد."
    )


# ============================================================
# /STATS
# ============================================================

async def tracker_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    try:
        stats = await asyncio.to_thread(
            get_stats
        )

        message = (
            "📊 <b>Tracker Statistics</b>\n\n"
            f"📌 Total Signals: {stats.get('total', 0)}\n"
            f"⏳ Open: {stats.get('open', 0)}\n"
            f"🔒 Closed: {stats.get('closed', 0)}\n\n"
            f"🎯 TP1 Hit: {stats.get('tp1', 0)}\n"
            f"🎯 TP2 Hit: {stats.get('tp2', 0)}\n"
            f"🎯 TP3 Hit: {stats.get('tp3', 0)}\n"
            f"🛑 SL Hit: {stats.get('sl', 0)}"
        )

        await update.effective_message.reply_text(
            message,
            parse_mode="HTML",
        )

    except Exception:
        logger.exception("Tracker stats error")

        await update.effective_message.reply_text(
            "❌ خطا در دریافت آمار Tracker."
        )


# ============================================================
# /NEWS
# ============================================================

async def news_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = await update.effective_message.reply_text(
        "📰 در حال دریافت اخبار کریپتو..."
    )

    try:
        articles = await get_latest_news(limit=8)

        if not articles:
            await message.edit_text(
                "⚠️ در حال حاضر خبری دریافت نشد.\n"
                "ممکن است منابع RSS در دسترس نباشند."
            )
            return

        lines = ["📰 آخرین اخبار کریپتو\n"]

        for index, article in enumerate(
            articles,
            start=1,
        ):
            importance = article.get(
                "importance",
                "NORMAL",
            )

            emoji = {
                "CRITICAL": "🔴",
                "HIGH": "🟠",
                "NORMAL": "🟢",
            }.get(importance, "⚪")

            title = str(
                article.get("title", "بدون عنوان")
            )

            source = str(
                article.get("source", "Unknown")
            )

            asset = str(
                article.get("asset", "UNKNOWN")
            )

            link = str(
                article.get("link", "")
            )

            item = (
                f"{index}. {emoji} {title}\n"
                f"📡 منبع: {source}\n"
                f"🪙 دارایی: {asset}\n"
            )

            if link.startswith(("https://", "http://")):
                item += f"🔗 {link}\n"

            lines.append(item)

        output = "\n".join(lines)

        if len(output) > 4000:
            output = (
                output[:3900]
                + "\n\nادامه اخبار در اجرای بعدی."
            )

        await message.edit_text(
            output,
            disable_web_page_preview=True,
        )

    except Exception:
        logger.exception("NEWS_COMMAND_ERROR")

        await message.edit_text(
            "❌ خطا هنگام دریافت اخبار.\n"
            "لاگ Belmo را بررسی کن."
        )


# ============================================================
# /NEWS_TEST
# ============================================================

async def news_test_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = await update.effective_message.reply_text(
        "🔎 در حال آزمایش منابع خبری..."
    )

    try:
        result = await news_diagnostics()

        lines = [
            "📊 گزارش آزمایش منابع خبری\n",
            f"📰 مجموع اخبار: {result['total']}",
            f"🔴 اخبار CRITICAL: {result['critical_count']}",
            f"🟠 اخبار HIGH: {result['high_count']}",
            "",
            "وضعیت منابع:",
        ]

        for source, status in result["sources"].items():
            icon = "✅" if status.get("ok") else "❌"

            count = status.get("count", 0)

            lines.append(
                f"{icon} {source}: {count} خبر"
            )

        await message.edit_text(
            "\n".join(lines)
        )

    except Exception:
        logger.exception("NEWS_TEST_ERROR")

        await message.edit_text(
            "❌ آزمایش منابع خبری ناموفق بود.\n"
            "لاگ Belmo را بررسی کن."
        )


# ============================================================
# MAIN
# ============================================================

def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    logger.info("=" * 60)
    logger.info("CryptoBot starting...")
    logger.info("Symbols to scan: %s", len(SYMBOLS))
    logger.info(
        "Automatic scan interval: %s seconds",
        AUTO_INTERVAL,
    )
    logger.info(
        "Tracker interval: %s seconds",
        TRACKER_INTERVAL,
    )
    logger.info(
        "Critical news window: %s minutes",
        NEWS_BLOCK_MINUTES,
    )
    logger.info("=" * 60)

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("price", price)
    )

    application.add_handler(
        CommandHandler("signal", signal)
    )

    application.add_handler(
        CommandHandler("register", register_chat)
    )

    application.add_handler(
        CommandHandler("stats", tracker_stats)
    )

    application.add_handler(
        CommandHandler("news", news_command)
    )

    application.add_handler(
        CommandHandler("news_test", news_test_command)
    )

    application.job_queue.run_repeating(
        track_open_trades,
        interval=TRACKER_INTERVAL,
        first=TRACKER_INTERVAL,
    )

    logger.info(
        "Trade tracker scheduled every %s seconds",
        TRACKER_INTERVAL,
    )

    application.job_queue.run_repeating(
        auto_signal,
        interval=AUTO_INTERVAL,
        first=60,
    )

    logger.info(
        "Automatic signal scanner scheduled every %s seconds",
        AUTO_INTERVAL,
    )

    logger.info("CryptoBot started successfully.")

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
