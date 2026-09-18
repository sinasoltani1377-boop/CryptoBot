import os
import logging
import asyncio
import threading
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from analysis import generate_signal


# =========================
# CONFIG
# =========================

TOKEN = os.getenv("BOT_TOKEN")

TOOBIT_KLINES_URL = "https://api.toobit.com/quote/v1/klines"
TOOBIT_TICKER_URL = "https://api.toobit.com/quote/v1/contract/ticker/price"

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
}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

_scan_lock = asyncio.Lock()


# =========================
# CANDLE NORMALIZATION
# =========================

def safe_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_candle(candle):
    """
    تبدیل کندل Toobit به فرمت مورد نیاز analysis.py
    """

    # اگر قبلاً dict باشد
    if isinstance(candle, dict):
        return {
            "timestamp": candle.get("timestamp", candle.get("time")),
            "open": safe_number(candle.get("open")),
            "high": safe_number(candle.get("high")),
            "low": safe_number(candle.get("low")),
            "close": safe_number(candle.get("close")),
            "volume": safe_number(candle.get("volume")),
        }

    # فرمت معمول Toobit:
    # [timestamp, open, high, low, close, volume, ...]
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

    # اگر string یا نوع ناشناخته بود، نادیده گرفته شود
    return None


def extract_candle_rows(data):
    """
    استخراج لیست کندل‌ها از فرمت‌های مختلف پاسخ API
    """

    # پاسخ مستقیم:
    # [[...], [...], [...]]
    if isinstance(data, list):
        return data

    # اگر پاسخ dict باشد
    if isinstance(data, dict):

        # حالت‌های رایج
        for key in ("data", "result", "rows", "klines", "candles"):
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

        # کندل ناقص نباید وارد analysis شود
        if (
            candle["open"] is None
            or candle["high"] is None
            or candle["low"] is None
            or candle["close"] is None
        ):
            continue

        candles.append(candle)

    return candles


# =========================
# TOOBIT MARKET DATA
# =========================

def get_klines(symbol, interval, limit=200):

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

    if not daily or not h4 or not h1:
        return None

    return {
        "1d": daily,
        "4h": h4,
        "1h": h1,
    }


# =========================
# PRICE
# =========================

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

            price = data.get("p")

            if price is None:
                price = data.get("price")

            if price is not None:
                return float(price)

        return None

    except Exception as e:
        logger.error(
            "Price error %s: %s",
            symbol,
            e,
        )
        return None


# =========================
# SIGNAL TEXT
# =========================

def signal_text(symbol, result):

    direction = result.get("direction", "UNKNOWN")

    emoji = "🟢" if direction == "LONG" else "🔴"

    text = (
        f"{emoji} <b>{symbol}</b>\n\n"
        f"🎯 Signal: <b>{direction}</b>\n"
        f"⭐ Quality: <b>{result.get('quality')}</b>\n"
        f"📊 Score: <b>{result.get('score')}</b>\n\n"
        f"📅 Daily: {result.get('daily')}\n"
        f"⏱ 4H: {result.get('4h')}\n"
        f"🕐 1H: {result.get('1h')}\n\n"
        f"💰 Entry: <b>{result.get('entry')}</b>\n"
        f"🛑 SL: <b>{result.get('sl')}</b>\n\n"
        f"🎯 TP1: <b>{result.get('tp1')}</b>\n"
        f"🎯 TP2: <b>{result.get('tp2')}</b>\n"
        f"🎯 TP3: <b>{result.get('tp3')}</b>\n\n"
        f"📏 Risk: {result.get('risk')}\n"
        f"⚖️ RR: {result.get('rr')}\n\n"
        f"🧠 Strategies:\n"
        f"{', '.join(result.get('strategy_matches', []))}"
    )

    return text


# =========================
# ANALYSIS
# =========================

def analyze_symbol(symbol):

    market_data = get_market_data(symbol)

    if market_data is None:
        return None

    result = generate_signal(
        market_data["1d"],
        market_data["4h"],
        market_data["1h"],
    )

    if not isinstance(result, dict):
        return None

    # فقط HIGH
    if result.get("quality") != "HIGH":
        return None

    # فقط LONG / SHORT
    if result.get("direction") not in ("LONG", "SHORT"):
        return None

    if result.get("signal") not in ("LONG", "SHORT"):
        return None

    return result


# =========================
# /START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 CryptoBot فعال است.\n\n"
        "دستورات:\n"
        "/price - قیمت BTC و SOL\n"
        "/signal - بررسی سیگنال‌های HIGH"
    )


# =========================
# /PRICE
# =========================

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):

    btc = get_price("BTC-SWAP-USDT")
    sol = get_price("SOL-SWAP-USDT")

    text = "💰 <b>CryptoBot Prices</b>\n\n"

    if btc is not None:
        text += f"₿ BTC: <b>{btc}</b>\n"
    else:
        text += "₿ BTC: unavailable\n"

    if sol is not None:
        text += f"◎ SOL: <b>{sol}</b>\n"
    else:
        text += "◎ SOL: unavailable\n"

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# =========================
# /SIGNAL
# =========================

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🔎 در حال بررسی بازار...\n"
        "فقط سیگنال‌های HIGH نمایش داده می‌شوند."
    )

    found = 0

    for symbol in SYMBOLS:

        try:
            result = await asyncio.to_thread(
                analyze_symbol,
                symbol,
            )

            if result:

                await update.message.reply_text(
                    signal_text(symbol, result),
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
            "⏳ در حال حاضر هیچ سیگنال HIGH معتبری پیدا نشد."
        )


# =========================
# AUTO SCANNER
# =========================
async def auto_signal(context: ContextTypes.DEFAULT_TYPE):

    if _scan_lock.locked():
        logger.warning("Previous scan still running. Skipping.")
        return

    async with _scan_lock:

        logger.info("Starting automatic market scan...")

        found = 0

        for symbol in SYMBOLS:

            try:
                result = await asyncio.to_thread(
                    analyze_symbol,
                    symbol,
                )

                if result:

                    found += 1

                    logger.info(
                        "HIGH signal found: %s %s",
                        symbol,
                        result.get("direction"),
                    )

                    chat_ids = context.application.bot_data.get(
                        "chat_ids",
                        set(),
                    )

                    for chat_id in chat_ids:

                        try:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=signal_text(symbol, result),
                                parse_mode="HTML",
                            )

                        except Exception:
                            logger.exception(
                                "Telegram send error for chat %s",
                                chat_id,
                            )

            except Exception:
                logger.exception(
                    "Scan error %s",
                    symbol,
                )

        if found == 0:
            logger.info("No HIGH signals.")

# =========================
# SAVE CHAT ID
# =========================

async def register_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_ids = context.application.bot_data.setdefault(
        "chat_ids",
        set(),
    )

    chat_ids.add(update.effective_chat.id)

    await update.message.reply_text(
        "✅ این چت برای دریافت سیگنال‌های خودکار ثبت شد."
    )


# =========================
# MAIN
# =========================

def main():

    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", register_chat)
    )

    application.add_handler(
        CommandHandler("price", price)
    )

    application.add_handler(
        CommandHandler("signal", signal)
    )

    # ثبت چت هنگام /start
    application.add_handler(
        CommandHandler("register", register_chat)
    )

    # Auto scanner - every 5 minutes
    application.job_queue.run_repeating(
        auto_signal,
        interval=300,
        first=10,
    )

    logger.info(
        "Auto scanner started: every 5 minutes"
    )

    logger.info(
        "CryptoBot started successfully."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
