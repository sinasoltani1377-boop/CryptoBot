import requests
from analysis import generate_signal
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os

TOKEN = os.getenv("BOT_TOKEN")


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
        "📊 برای دریافت قیمت BTC و SOL دستور زیر را بفرست:\n"
        "/price\n\n"
        "📈 برای دریافت تحلیل:\n"
        "/signal"
    )


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        btc = get_price("BTC-SWAP-USDT")
        sol = get_price("SOL-SWAP-USDT")

        message = (
            "📊 Toobit Futures\n\n"
            f"₿ BTC: ${btc:,.2f}\n"
            f"◎ SOL: ${sol:,.2f}"
        )

        await update.message.reply_text(message)

    except Exception as e:
        await update.message.reply_text(
            f"❌ خطا در دریافت قیمت: {e}"
        )


async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from market import get_market_data

        btc_data = get_market_data("BTC-SWAP-USDT")
        sol_data = get_market_data("SOL-SWAP-USDT")

        btc_signal = generate_signal(btc_data)
        sol_signal = generate_signal(sol_data)

        btc_strategies = ", ".join(
            btc_signal.get("strategy_matches", [])
        )

        sol_strategies = ", ".join(
            sol_signal.get("strategy_matches", [])
        )

        message = (
            "🤖 CryptoBot Signal\n\n"

            "₿ BTC:\n"
            f"📅 Daily: {btc_signal.get('daily', 'UNKNOWN')}\n"
            f"⏱ 4H: {btc_signal.get('4h', 'UNKNOWN')}\n"
            f"🕐 1H: {btc_signal.get('1h', 'UNKNOWN')}\n"
            f"📊 Score: {btc_signal.get('score', 0)}\n"
            f"⭐ Quality: {btc_signal.get('quality', 'LOW')}\n"
            f"🎯 Signal: {btc_signal.get('signal', 'NO_TRADE')}\n"
            f"⚠️ Reason: {btc_signal.get('reason', 'UNKNOWN')}\n"
            f"🧠 Strategies: {btc_strategies}\n\n"

            "◎ SOL:\n"
            f"📅 Daily: {sol_signal.get('daily', 'UNKNOWN')}\n"
            f"⏱ 4H: {sol_signal.get('4h', 'UNKNOWN')}\n"
            f"🕐 1H: {sol_signal.get('1h', 'UNKNOWN')}\n"
            f"📊 Score: {sol_signal.get('score', 0)}\n"
            f"⭐ Quality: {sol_signal.get('quality', 'LOW')}\n"
            f"🎯 Signal: {sol_signal.get('signal', 'NO_TRADE')}\n"
            f"⚠️ Reason: {sol_signal.get('reason', 'UNKNOWN')}\n"
            f"🧠 Strategies: {sol_strategies}"
        )

        await update.message.reply_text(message)

    except Exception as e:
        await update.message.reply_text(
            f"❌ خطا: {e}"
        )


async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    try:
        from market import get_market_data

        for symbol in ["BTC-SWAP-USDT", "SOL-SWAP-USDT"]:

            data = get_market_data(symbol)

            result = generate_signal(data)

            print(symbol, result)

            if result["signal"] in ["LONG", "SHORT"]:

                await context.bot.send_message(
    chat_id=6912201079,
    text=(
        f"🚨 {symbol}\n\n"
        f"🎯 سیگنال: {result['signal']}\n"
        f"⭐ کیفیت: {result.get('quality', 'UNKNOWN')}\n"
        f"📊 امتیاز: {result.get('score', 0)}\n\n"
        f"💰 Entry: {result.get('entry', 'N/A')}\n"
        f"🛑 SL: {result.get('sl', 'N/A')}\n\n"
        f"🎯 TP1: {result.get('tp1', 'N/A')}\n"
        f"🎯 TP2: {result.get('tp2', 'N/A')}\n"
        f"🎯 TP3: {result.get('tp3', 'N/A')}\n\n"
        f"📐 Risk: {result.get('risk', 'N/A')}\n"
        f"⚖️ RR: 1:{result.get('rr', 'N/A')}"
    )
)

    except Exception as e:
        print("AUTO_SIGNAL_ERROR:", e)


app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("price", price))
app.add_handler(CommandHandler("signal", signal))

app.job_queue.run_repeating(
    auto_signal,
    interval=300,
    first=10
)

app.run_polling()
