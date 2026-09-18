import requests
import os

from analysis import generate_signal

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


TOKEN = os.getenv("BOT_TOKEN")

CHAT_ID = 6912201079


def get_price(symbol):
    url = "https://api.toobit.com/quote/v1/contract/ticker/price"

    response = requests.get(
        url,
        params={"symbol": symbol},
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    return float(data[0]["p"])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 ربات ترید فعال است!\n\n"
        "📊 برای دریافت قیمت دستور زیر را بفرست:\n"
        "/price\n\n"
        "📈 برای اسکن بازار:\n"
        "/signal"
    )


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:

        from market import get_futures_symbols

        symbols = get_futures_symbols()

        message = "📊 Toobit USDT-M Futures\n\n"

        # فقط چند ارز اول برای جلوگیری از پیام خیلی بزرگ
        for symbol in symbols[:20]:

            try:

                price = get_price(symbol)

                message += (
                    f"🔹 {symbol}: "
                    f"${price:,.6f}\n"
                )

            except Exception:
                continue

        await update.message.reply_text(message)

    except Exception as e:

        await update.message.reply_text(
            f"❌ خطا در دریافت قیمت:\n{e}"
        )


async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:

        from market import get_futures_symbols
        from market import get_market_data

        symbols = get_futures_symbols()

        message_parts = [
            "🤖 CryptoBot Market Scan\n"
        ]

        scanned = 0
        signals_found = 0

        for symbol in symbols:

            try:

                data = get_market_data(symbol)

                result = generate_signal(data)

                scanned += 1

                signal_type = result.get(
                    "signal",
                    "NO_TRADE"
                )

                # فقط سیگنال‌های واقعی نمایش داده شوند
                if signal_type in ["LONG", "SHORT"]:

                    signals_found += 1

                    strategies = ", ".join(
                        result.get(
                            "strategy_matches",
                            []
                        )
                    )

                    message_parts.append(
                        f"🚨 {symbol}\n"
                        f"🎯 Signal: {signal_type}\n"
                        f"⭐ Quality: "
                        f"{result.get('quality', 'LOW')}\n"
                        f"📊 Score: "
                        f"{result.get('score', 0)}\n\n"
                        f"💰 Entry: "
                        f"{result.get('entry', 'N/A')}\n"
                        f"🛑 SL: "
                        f"{result.get('sl', 'N/A')}\n\n"
                        f"🎯 TP1: "
                        f"{result.get('tp1', 'N/A')}\n"
                        f"🎯 TP2: "
                        f"{result.get('tp2', 'N/A')}\n"
                        f"🎯 TP3: "
                        f"{result.get('tp3', 'N/A')}\n\n"
                        f"📐 Risk: "
                        f"{result.get('risk', 'N/A')}\n"
                        f"⚖️ RR: "
                        f"1:{result.get('rr', 'N/A')}\n"
                        f"🧠 Strategies: "
                        f"{strategies}\n"
                    )

            except Exception as e:

                print(
                    f"SIGNAL_ERROR {symbol}: {e}"
                )

        if signals_found == 0:

            message_parts.append(
                "⚪ در حال حاضر سیگنال معتبری "
                "پیدا نشد.\n\n"
                f"🔎 Symbols scanned: {scanned}"
            )

        final_message = "\n".join(
            message_parts
        )

        # جلوگیری از عبور پیام تلگرام از محدودیت
        if len(final_message) > 3900:

            final_message = (
                final_message[:3900]
                + "\n\n⚠️ پیام کوتاه شد."
            )

        await update.message.reply_text(
            final_message
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ خطا در اسکن بازار:\n{e}"
        )


async def auto_signal(
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        from market import get_futures_symbols
        from market import get_market_data

        symbols = get_futures_symbols()

        for symbol in symbols:

            try:

                data = get_market_data(symbol)

                result = generate_signal(data)

                print(
                    symbol,
                    result
                )

                if result.get("signal") in [
                    "LONG",
                    "SHORT"
                ]:

                    strategies = ", ".join(
                        result.get(
                            "strategy_matches",
                            []
                        )
                    )

                    await context.bot.send_message(

                        chat_id=CHAT_ID,

                        text=(

                            f"🚨 {symbol}\n\n"

                            f"🎯 سیگنال: "
                            f"{result['signal']}\n"

                            f"⭐ کیفیت: "
                            f"{result.get('quality', 'UNKNOWN')}\n"

                            f"📊 امتیاز: "
                            f"{result.get('score', 0)}\n\n"

                            f"💰 Entry: "
                            f"{result.get('entry', 'N/A')}\n"

                            f"🛑 SL: "
                            f"{result.get('sl', 'N/A')}\n\n"

                            f"🎯 TP1: "
                            f"{result.get('tp1', 'N/A')}\n"

                            f"🎯 TP2: "
                            f"{result.get('tp2', 'N/A')}\n"

                            f"🎯 TP3: "
                            f"{result.get('tp3', 'N/A')}\n\n"

                            f"📐 Risk: "
                            f"{result.get('risk', 'N/A')}\n"

                            f"⚖️ RR: "
                            f"1:{result.get('rr', 'N/A')}\n\n"

                            f"🧠 Strategies: "
                            f"{strategies}"
                        )
                    )

            except Exception as e:

                print(
                    f"AUTO_SYMBOL_ERROR "
                    f"{symbol}: {e}"
                )

    except Exception as e:

        print(
            "AUTO_SIGNAL_ERROR:",
            e
        )


app = (
    Application
    .builder()
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
        price
    )
)


app.add_handler(
    CommandHandler(
        "signal",
        signal
    )
)


app.job_queue.run_repeating(

    auto_signal,

    interval=300,

    first=10
)


app.run_polling()
