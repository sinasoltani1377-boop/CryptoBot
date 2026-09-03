import requests
from analysis import generate_signal
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue
with open("token.txt", "r") as f:
    TOKEN = f.read().strip()


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
        "/price"
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
            "❌ خطا در دریافت قیمت."
        )

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from market import get_market_data

        btc_data = get_market_data("BTC-SWAP-USDT")
        sol_data = get_market_data("SOL-SWAP-USDT")

        btc_signal = generate_signal(btc_data)
        sol_signal = generate_signal(sol_data)

        message = (
    "🤖 CryptoBot Signal\n\n"
    f"₿ BTC:\n"
    f"📅 Daily: {btc_signal['daily']}\n"
    f"⏱ 4H: {btc_signal['4h']}\n"
    f"🕐 1H: {btc_signal['1h']}\n"
    f"🔀 BOS: {btc_signal['bos']}\n"
    f"↩️ Pullback: {btc_signal['pullback']}\n"
    f"🕯 Confirmation: {btc_signal['confirmation']}\n"
    f"🎯 Signal: {btc_signal['signal']}\n"
    f"⚠️ Reason: {btc_signal['reason']}\n\n"
    f"◎ SOL:\n"
    f"📅 Daily: {sol_signal['daily']}\n"
    f"⏱ 4H: {sol_signal['4h']}\n"
    f"🕐 1H: {sol_signal['1h']}\n"
    f"🔀 BOS: {sol_signal['bos']}\n"
    f"↩️ Pullback: {sol_signal['pullback']}\n"
    f"🕯 Confirmation: {sol_signal['confirmation']}\n"
    f"🎯 Signal: {sol_signal['signal']}\n"
    f"⚠️ Reason: {sol_signal['reason']}"
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
                    text=f"🚨 {symbol}\nسیگنال: {result['signal']}"
                )

    except Exception as e:
        print("AUTO_SIGNAL_ERROR:", e)


app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("price", price))
app.add_handler(CommandHandler("signal", signal))
app.job_queue.run_repeating(auto_signal, interval=300, first=10)

app.run_polling()
