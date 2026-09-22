import os
import logging
import asyncio
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from analysis import generate_signal

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


SYMBOLS = [
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


INTERVALS = {
    "1d": "1d",
    "4h": "4h",
    "1h": "1h",
    "15m": "15m",
    "5m": "5m",
}


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

_scan_lock = asyncio.Lock()


# ============================================================
# CANDLE NORMALIZATION
# ============================================================

def safe_number(value):

    try:
        return float(value)

    except (TypeError, ValueError):
        return None


def normalize_candle(candle):

    if isinstance(candle, dict):

        return {
            "timestamp": candle.get(
                "timestamp",
                candle.get("time"),
            ),
            "open": safe_number(
                candle.get("open")
            ),
            "high": safe_number(
                candle.get("high")
            ),
            "low": safe_number(
                candle.get("low")
            ),
            "close": safe_number(
                candle.get("close")
            ),
            "volume": safe_number(
                candle.get("volume")
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

    return []


def normalize_candles(data):

    rows = extract_candle_rows(data)

    candles = []

    for row in rows:

        candle = normalize_candle(row)

        if candle is None:
            continue

        if (
            candle["open"] is None
            or candle["high"] is None
            or candle["low"] is None
            or candle["close"] is None
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

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }

        response = requests.get(
            TOOBIT_KLINES_URL,
            params=params,
            timeout=15,
        )

        response.raise_for_status()

        data = response.json()

        candles = normalize_candles(data)

        if len(candles) < 50:

            logger.warning(
                "%s %s: insufficient candles: %s",
                symbol,
                interval,
                len(candles),
            )

            return []

        return candles

    except Exception as e:

        logger.error(
            "Kline error %s %s: %s",
            symbol,
            interval,
            e,
        )

        return []


def get_market_data(symbol):

    daily = get_klines(
        symbol,
        INTERVALS["1d"],
        200,
    )

    h4 = get_klines(
        symbol,
        INTERVALS["4h"],
        200,
    )

    h1 = get_klines(
        symbol,
        INTERVALS["1h"],
        200,
    )

    m15 = get_klines(
        symbol,
        INTERVALS["15m"],
        200,
    )

    m5 = get_klines(
        symbol,
        INTERVALS["5m"],
        200,
    )

    if (
        not daily
        or not h4
        or not h1
        or not m15
        or not m5
    ):
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
            params={
                "symbol": symbol
            },
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        logger.info(
            "PRICE API | %s | %s",
            symbol,
            data,
        )

        # Response is a dictionary
        if isinstance(data, dict):

            price = (
                data.get("p")
                or data.get("price")
                or data.get("lastPrice")
                or data.get("last")
            )

            if price is not None:
                return float(price)

        # Response is a list
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

                price = (
                    item.get("p")
                    or item.get("price")
                    or item.get("lastPrice")
                    or item.get("last")
                )

                if price is not None:
                    return float(price)

        logger.warning(
            "PRICE API | %s | Price not found | Response=%s",
            symbol,
            data,
        )

        return None

    except Exception as e:

        logger.error(
            "Price error %s: %s",
            symbol,
            e,
        )

        return None
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

    if direction not in (
        "LONG",
        "SHORT",
    ):
        return None

    # Prevent duplicate tracking
    if already_tracking(
        symbol,
        direction,
    ):

        logger.info(
            "TRACKER | ALREADY OPEN | "
            "%s | %s",
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
            "TRACKER | REGISTERED | "
            "%s | %s | Entry=%s | SL=%s | "
            "TP1=%s | TP2=%s | TP3=%s",
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
# STRATEGY DIAGNOSTIC
# ============================================================

def log_strategy_details(
    symbol,
    result,
):

    details = result.get(
        "strategy_details"
    )

    if not isinstance(details, dict):
        return

    strategy_status = []

    for name, value in details.items():

        if isinstance(value, dict):

            matched = value.get(
                "matched",
                False,
            )

            direction = value.get(
                "direction"
            )

            if matched and direction:

                status = (
                    f"YES({direction})"
                )

            else:

                status = (
                    "YES"
                    if matched
                    else "NO"
                )

        else:

            status = (
                "YES"
                if bool(value)
                else "NO"
            )

        strategy_status.append(
            f"{name}={status}"
        )

    if strategy_status:

        logger.info(
            "%s | STRATEGIES | %s",
            symbol,
            " | ".join(
                strategy_status
            ),
        )


# ============================================================
# FULL DIAGNOSTIC
# ============================================================

def log_signal_diagnostic(
    symbol,
    result,
):

    if not isinstance(result, dict):
        return

    daily = result.get(
        "daily",
        "UNKNOWN",
    )

    h4 = result.get(
        "4h",
        "UNKNOWN",
    )

    h1 = result.get(
        "1h",
        "UNKNOWN",
    )

    direction = result.get(
        "direction",
        "UNKNOWN",
    )

    signal = result.get(
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

    reason = result.get(
        "reason",
        result.get(
            "blocked_reason",
            "UNKNOWN",
        ),
    )

    strategies = (
        result.get(
            "strategy_matches"
        )
        or result.get(
            "strategies"
        )
        or []
    )

    if isinstance(
        strategies,
        (list, tuple),
    ):

        strategies_text = (
            ", ".join(
                str(x)
                for x in strategies
            )
            if strategies
            else "NONE"
        )

    else:

        strategies_text = str(
            strategies
        )

    logger.info(
        "DIAGNOSTIC | %s | "
        "Daily=%s | 4H=%s | 1H=%s | "
        "Direction=%s | Signal=%s | "
        "Score=%s | Quality=%s | "
        "Reason=%s | Strategies=%s",
        symbol,
        daily,
        h4,
        h1,
        direction,
        signal,
        score,
        quality,
        reason,
        strategies_text,
    )

    logger.info(
        "FILTERS | %s | "
        "15M_RSI=%s | "
        "VolumeSpike=%s | "
        "Confirmation=%s",
        symbol,
        result.get("rsi_15m"),
        result.get("volume_spike"),
        result.get("confirmation"),
    )

    log_strategy_details(
        symbol,
        result,
    )


# ============================================================
# SIGNAL TEXT
# ============================================================

def signal_text(
    symbol,
    result,
):

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
        result.get(
            "strategy_matches"
        )
        or result.get(
            "strategies"
        )
        or []
    )

    if not isinstance(
        strategies,
        (list, tuple),
    ):

        strategies = [
            strategies
        ]

    strategy_text = (
        ", ".join(
            str(x)
            for x in strategies
        )
        if strategies
        else "NONE"
    )

    return (
        f"{emoji} <b>{symbol}</b>\n\n"

        f"🎯 Signal: "
        f"<b>{result.get('signal')}</b>\n"

        f"⭐ Quality: "
        f"<b>{result.get('quality')}</b>\n"

        f"📊 Score: "
        f"<b>{result.get('score')}</b>\n\n"

        f"📅 Daily: "
        f"{result.get('daily')}\n"

        f"⏱ 4H: "
        f"{result.get('4h')}\n"

        f"🕐 1H: "
        f"{result.get('1h')}\n"

        f"⏱ 15M RSI: "
        f"{result.get('rsi_15m')}\n\n"

        f"💰 Entry: "
        f"<b>{result.get('entry')}</b>\n"

        f"🛑 SL: "
        f"<b>{result.get('sl')}</b>\n\n"

        f"🎯 TP1: "
        f"<b>{result.get('tp1')}</b>\n"

        f"🎯 TP2: "
        f"<b>{result.get('tp2')}</b>\n"

        f"🎯 TP3: "
        f"<b>{result.get('tp3')}</b>\n\n"

        f"📏 Risk: "
        f"{result.get('risk')}\n"

        f"⚖️ RR: "
        f"{result.get('rr')}\n\n"

        f"🧠 Strategy:\n"
        f"<b>{strategy_text}</b>\n\n"

        f"📝 Reason:\n"
        f"{result.get('reason', 'N/A')}"
    )


# ============================================================
# RAW ANALYSIS
# ============================================================

def analyze_symbol_raw(symbol):

    market_data = get_market_data(
        symbol
    )

    if market_data is None:
        return None

    result = generate_signal(
        market_data["1d"],
        market_data["4h"],
        market_data["1h"],
        market_data["15m"],
        market_data["5m"],
    )

    if not isinstance(
        result,
        dict,
    ):
        return None

    return result


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_ids = (
        context.application
        .bot_data
        .setdefault(
            "chat_ids",
            set(),
        )
    )

    chat_ids.add(
        update.effective_chat.id
    )

    await update.message.reply_text(
        "🤖 CryptoBot فعال است.\n\n"
        "دستورات:\n"
        "/price - قیمت BTC و SOL\n"
        "/signal - بررسی سیگنال‌های HIGH\n"
        "/register - ثبت دریافت سیگنال خودکار"
    )


# ============================================================
# /PRICE
# ============================================================

async def price(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    btc = get_price(
        "BTC-SWAP-USDT"
    )

    sol = get_price(
        "SOL-SWAP-USDT"
    )

    text = (
        "💰 <b>CryptoBot Prices</b>\n\n"
    )

    if btc is not None:

        text += (
            f"₿ BTC: "
            f"<b>{btc}</b>\n"
        )

    else:

        text += (
            "₿ BTC: unavailable\n"
        )

    if sol is not None:

        text += (
            f"◎ SOL: "
            f"<b>{sol}</b>\n"
        )

    else:

        text += (
            "◎ SOL: unavailable\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# /SIGNAL
# ============================================================

async def signal(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "🔎 در حال بررسی بازار...\n"
        "Daily → 4H → 1H → 15M → 5M\n\n"
        "فقط سیگنال‌های HIGH نمایش داده می‌شوند."
    )

    found = 0

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

            if result.get(
                "quality"
            ) != "HIGH":
                continue

            if result.get(
                "direction"
            ) not in (
                "LONG",
                "SHORT",
            ):
                continue

            if result.get(
                "signal"
            ) not in (
                "LONG",
                "SHORT",
            ):
                continue

            # Register only once
            trade = register_high_signal(
                symbol,
                result,
            )

            if trade is not None:

                logger.info(
                    "Manual signal registered | "
                    "%s",
                    symbol,
                )

            await update.message.reply_text(
                signal_text(
                    symbol,
                    result,
                ),
                parse_mode="HTML",
            )

            found += 1

        except Exception:

            logger.exception(
                "Signal error %s",
                symbol,
            )

    if found == 0:

        await update.message.reply_text(
            "⏳ در حال حاضر هیچ "
            "سیگنال HIGH معتبری پیدا نشد.\n\n"
            "🔍 جزئیات تشخیص در لاگ ثبت شد."
        )


# ============================================================
# AUTO SCANNER
# ============================================================

async def auto_signal(
    context: ContextTypes.DEFAULT_TYPE,
):

    if _scan_lock.locked():

        logger.warning(
            "Previous scan still running. "
            "Skipping."
        )

        return

    async with _scan_lock:

        logger.info(
            "Starting automatic market scan..."
        )

        found = 0

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

                if result.get(
                    "quality"
                ) != "HIGH":
                    continue

                if result.get(
                    "direction"
                ) not in (
                    "LONG",
                    "SHORT",
                ):
                    continue

                if result.get(
                    "signal"
                ) not in (
                    "LONG",
                    "SHORT",
                ):
                    continue

                # Register HIGH signal
                # only if it is not already open.
                trade = register_high_signal(
                    symbol,
                    result,
                )

                if trade is not None:

                    logger.info(
                        "HIGH SIGNAL REGISTERED | "
                        "%s | %s | Score=%s",
                        symbol,
                        result.get(
                            "direction"
                        ),
                        result.get(
                            "score"
                        ),
                    )

                found += 1

                logger.info(
                    "HIGH SIGNAL FOUND | "
                    "%s | %s | Score=%s",
                    symbol,
                    result.get(
                        "direction"
                    ),
                    result.get(
                        "score"
                    ),
                )

                chat_ids = (
                    context.application
                    .bot_data
                    .get(
                        "chat_ids",
                        set(),
                    )
                )

                for chat_id in chat_ids:

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
                            "Telegram send error "
                            "for chat %s",
                            chat_id,
                        )

            except Exception:

                logger.exception(
                    "Scan error %s",
                    symbol,
                )

        if found == 0:

            logger.info(
                "No HIGH signals."
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

        # Log current price of every open trade
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
                "TRACKER CHECK | "
                "%s | %s | "
                "Current=%s | Entry=%s | "
                "SL=%s | TP1=%s | "
                "TP2=%s | TP3=%s",
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

        chat_ids = (
            context.application
            .bot_data
            .get(
                "chat_ids",
                set(),
            )
        )

        for event in events:

            trade = event.get(
                "trade",
                {},
            )

            result = event.get(
                "event",
                "UNKNOWN",
            )

            price_now = event.get(
                "price"
            )

            symbol = trade.get(
                "symbol",
                "UNKNOWN",
            )

            direction = trade.get(
                "direction",
                "UNKNOWN",
            )

            strategy = trade.get(
                "strategy",
                "UNKNOWN",
            )

            message = (
                "📊 <b>TRACKER UPDATE</b>\n\n"

                f"🪙 {symbol}\n"

                f"📈 Direction: "
                f"<b>{direction}</b>\n"

                f"🧠 Strategy: "
                f"<b>{strategy}</b>\n\n"

                f"💰 Current Price: "
                f"<b>{price_now}</b>\n\n"

                f"📌 Entry: "
                f"{trade.get('entry')}\n"

                f"🛑 SL: "
                f"{trade.get('sl')}\n"

                f"🎯 TP1: "
                f"{trade.get('tp1')}\n"

                f"🎯 TP2: "
                f"{trade.get('tp2')}\n"

                f"🎯 TP3: "
                f"{trade.get('tp3')}\n\n"

                f"📍 RESULT: "
                f"<b>{result}</b>"
            )

            for chat_id in chat_ids:

                try:

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="HTML",
                    )

                except Exception:

                    logger.exception(
                        "Tracker Telegram error "
                        "for chat %s",
                        chat_id,
                    )

            logger.info(
                "TRACKER | %s | %s | Price=%s",
                symbol,
                result,
                price_now,
            )

    except Exception:

        logger.exception(
            "Tracker error"
        )


# ============================================================
# /REGISTER
# ============================================================

async def register_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_ids = (
        context.application
        .bot_data
        .setdefault(
            "chat_ids",
            set(),
        )
    )

    chat_ids.add(
        update.effective_chat.id
    )

    await update.message.reply_text(
        "✅ این چت برای دریافت "
        "سیگنال‌های خودکار ثبت شد."
    )


# ============================================================
# TRACKER STATS
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

            f"📌 Total Signals: "
            f"{stats.get('total', 0)}\n"

            f"⏳ Open: "
            f"{stats.get('open', 0)}\n"

            f"🔒 Closed: "
            f"{stats.get('closed', 0)}\n\n"

            f"🎯 TP1 Hit: "
            f"{stats.get('tp1', 0)}\n"

            f"🎯 TP2 Hit: "
            f"{stats.get('tp2', 0)}\n"

            f"🎯 TP3 Hit: "
            f"{stats.get('tp3', 0)}\n"

            f"🛑 SL Hit: "
            f"{stats.get('sl', 0)}"
        )

        await update.message.reply_text(
            message,
            parse_mode="HTML",
        )

    except Exception:

        logger.exception(
            "Tracker stats error"
        )

        await update.message.reply_text(
            "❌ خطا در دریافت آمار Tracker."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable "
            "is missing."
        )

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "price",
            price,
        )
    )

    application.add_handler(
        CommandHandler(
            "signal",
            signal,
        )
    )

    application.add_handler(
        CommandHandler(
            "register",
            register_chat,
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            tracker_stats,
        )
    )

    # --------------------------------------------------------
    # AUTO SIGNAL SCANNER
    # --------------------------------------------------------

    application.job_queue.run_repeating(
        auto_signal,
        interval=300,
        first=10,
    )

    # --------------------------------------------------------
    # TRADE TRACKER
    # --------------------------------------------------------

    application.job_queue.run_repeating(
        track_open_trades,
        interval=30,
        first=30,
    )
    logger.info("Trade tracker started: every 30 seconds")
    logger.info("Trade tracker started: every 30 seconds")

    logger.info(
        "CryptoBot started successfully."
    )

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
