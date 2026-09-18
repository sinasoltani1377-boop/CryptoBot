import os
import asyncio
import logging
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from analysis import generate_signal


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = 6912201079

AUTO_INTERVAL = 300  # 5 minutes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

_scan_lock = asyncio.Lock()


# ============================================================
# SYMBOLS
# ============================================================

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


# ============================================================
# TOOBIT KLINES
# ============================================================

def normalize_candle(candle):
    """
    Toobit normally returns candles as arrays:

    [
        timestamp,
        open,
        high,
        low,
        close,
        volume,
        ...
    ]

    analysis.py expects dictionaries.
    """

    if isinstance(candle, dict):
        return {
            "open": candle.get("open"),
            "high": candle.get("high"),
            "low": candle.get("low"),
            "close": candle.get("close"),
            "volume": candle.get("volume"),
            "timestamp": candle.get("timestamp"),
        }

    if isinstance(candle, (list, tuple)):

        if len(candle) < 5:
            return None

        return {
            "timestamp": candle[0],
            "open": candle[1],
            "high": candle[2],
            "low": candle[3],
            "close": candle[4],
            "volume": candle[5] if len(candle) > 5 else None,
        }

    return None


def normalize_candles(candles):

    if not isinstance(candles, list):
        return []

    normalized = []

    for candle in candles:

        converted = normalize_candle(candle)

        if converted is not None:
            normalized.append(converted)

    return normalized


def get_klines(symbol, interval, limit=200):

    url = "https://api.toobit.com/quote/v1/klines"

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=15,
        )

        response.raise_for_status()

        data = response.json()

        if not data:
            return []

        candles = normalize_candles(data)

        if not candles:
            logger.error(
                f"No valid candles for {symbol} {interval}"
            )

        return candles

    except Exception as e:

        logger.error(
            f"Klines error {symbol} {interval}: {e}"
        )

        return []


# ============================================================
# MARKET DATA
# ============================================================

def get_market_data(symbol):

    return {
        "1d": get_klines(
            symbol,
            "1d",
            200
        ),

        "4h": get_klines(
            symbol,
            "4h",
            200
        ),

        "1h": get_klines(
            symbol,
            "1h",
            200
        ),
    }


# ============================================================
# PRICE
# ============================================================

def get_price(symbol):

    url = (
        "https://api.toobit.com/"
        "quote/v1/contract/ticker/price"
    )

    try:

        response = requests.get(
            url,
            params={
                "symbol": symbol
            },
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        return float(data["p"])

    except Exception as e:

        logger.error(
            f"Price error {symbol}: {e}"
        )

        return None


# ============================================================
# SIGNAL TEXT
# ============================================================

def signal_text(symbol, result):

    direction = result.get(
        "signal",
        "NO_TRADE"
    )

    quality = result.get(
        "quality",
        "LOW"
    )

    score = result.get(
        "score",
        0
    )

    entry = result.get("entry")
    sl = result.get("sl")

    tp1 = result.get("tp1")
    tp2 = result.get("tp2")
    tp3 = result.get("tp3")

    risk = result.get("risk")
    rr = result.get("rr")

    strategies = result.get(
        "strategy_matches",
        []
    )

    if strategies:
        strategy_text = ", ".join(
            strategies
        )
    else:
        strategy_text = "N/A"

    daily = result.get(
        "daily",
        "N/A"
    )

    four_h = result.get(
        "4h",
        "N/A"
    )

    one_h = result.get(
        "1h",
        "N/A"
    )

    emoji = (
        "🟢"
        if direction == "LONG"
        else "🔴"
    )

    return (
        "🚨 CryptoBot HIGH SIGNAL\n\n"

        f"💎 {symbol}\n"

        f"{emoji} Signal: {direction}\n"

        f"⭐ Quality: {quality}\n"

        f"📊 Score: {score}/10\n\n"

        f"📅 Daily: {daily}\n"

        f"⏱ 4H: {four_h}\n"

        f"🕐 1H: {one_h}\n\n"

        f"💰 Entry: {entry}\n"

        f"🛑 SL: {sl}\n\n"

        f"🎯 TP1: {tp1}\n"

        f"🎯 TP2: {tp2}\n"

        f"🎯 TP3: {tp3}\n\n"

        f"⚠️ Risk: {risk}\n"

        f"📈 RR: {rr}\n\n"

        f"🧠 Strategies:\n"
        f"{strategy_text}\n\n"

        "⏱ Generated: 5m scanner"
    )


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "🤖 CryptoBot فعال است.\n\n"

        "دستورات:\n"

        "/price - قیمت‌ها\n"

        "/signal - بررسی سیگنال‌ها\n\n"

        "⚡ فقط سیگنال‌های HIGH ارسال می‌شوند."
    )


# ============================================================
# /PRICE
# ============================================================

async def price_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    messages = []

    for symbol in SYMBOLS:

        price = get_price(symbol)

        if price is not None:

            messages.append(
                f"💎 {symbol}: {price}"
            )

    if not messages:

        await update.message.reply_text(
            "❌ دریافت قیمت‌ها ناموفق بود."
        )

        return

    await update.message.reply_text(
        "\n".join(messages)
    )


# ============================================================
# SCAN
# ============================================================

async def scan_symbols():

    results = []

    for symbol in SYMBOLS:

        try:

            market_data = get_market_data(
                symbol
            )

            daily_candles = market_data["1d"]
            h4_candles = market_data["4h"]
            h1_candles = market_data["1h"]

            if not daily_candles:
                logger.warning(
                    f"No Daily data: {symbol}"
                )
                continue

            if not h4_candles:
                logger.warning(
                    f"No 4H data: {symbol}"
                )
                continue

            if not h1_candles:
                logger.warning(
                    f"No 1H data: {symbol}"
                )
                continue

            # analysis.py v3 expects:
            #
            # generate_signal(
            #     daily_candles,
            #     h4_candles,
            #     h1_candles
            # )

            result = generate_signal(
                daily_candles,
                h4_candles,
                h1_candles,
            )

            if not isinstance(
                result,
                dict
            ):
                logger.error(
                    f"Invalid result: {symbol}"
                )
                continue

            # فقط LONG / SHORT
            if result.get(
                "signal"
            ) not in [
                "LONG",
                "SHORT",
            ]:
                continue

            # فقط HIGH
            if result.get(
                "quality"
            ) != "HIGH":
                continue

            results.append(
                (
                    symbol,
                    result
                )
            )

        except Exception as e:

            logger.error(
                f"Scan error {symbol}: {e}"
            )

    return results


# ============================================================
# /SIGNAL
# ============================================================

async def signal_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    async with _scan_lock:

        await update.message.reply_text(
            "🔎 در حال بررسی بازار...\n"
            "فقط HIGH QUALITY بررسی می‌شود."
        )

        results = await scan_symbols()

    if not results:

        await update.message.reply_text(
            "⚪ در حال حاضر هیچ "
            "سیگنال HIGH معتبری پیدا نشد."
        )

        return

    for symbol, result in results:

        await update.message.reply_text(
            signal_text(
                symbol,
                result
            )
        )


# ============================================================
# AUTO SIGNAL
# ============================================================

async def auto_signal(
    context: ContextTypes.DEFAULT_TYPE
):

    if _scan_lock.locked():

        logger.info(
            "Scanner already running."
        )

        return

    async with _scan_lock:

        try:

            results = await scan_symbols()

            if not results:

                logger.info(
                    "No HIGH signals."
                )

                return

            for symbol, result in results:

                try:

                    await context.bot.send_message(

                        chat_id=CHAT_ID,

                        text=signal_text(
                            symbol,
                            result
                        ),
                    )

                except Exception as e:

                    logger.error(
                        f"Telegram send error: {e}"
                    )

        except Exception as e:

            logger.error(
                f"Auto scanner error: {e}"
            )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Telegram error: %s",
        context.error,
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

    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "price",
            price_command
        )
    )

    app.add_handler(
        CommandHandler(
            "signal",
            signal_command
        )
    )

    app.add_error_handler(
        error_handler
    )

    if app.job_queue:

        app.job_queue.run_repeating(

            auto_signal,

            interval=AUTO_INTERVAL,

            first=10,

            name="auto_signal",
        )

        logger.info(
            "Auto scanner started: every 5 minutes"
        )

    else:

        logger.error(
            "JobQueue is not available."
        )

    logger.info(
        "CryptoBot started successfully."
    )

    app.run_polling()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
