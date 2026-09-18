import asyncio
import os
import requests
from analysis import generate_signal
from tracker import register_signal, check_open_trades, format_stats
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = 6912201079
AUTO_INTERVAL = 300

# Prevent a second full-market scan from starting while the previous one is running.
_scan_lock = asyncio.Lock()


def get_price(symbol):
    r = requests.get(
        "https://api.toobit.com/quote/v1/contract/ticker/price",
        params={"symbol": symbol},
        timeout=10,
    )
    r.raise_for_status()
    return float(r.json()[0]["p"])


def signal_text(symbol, result):
    strategies = ", ".join(result.get("strategy_matches", [])) or "N/A"
    return (
        f"🚨 {symbol}\n\n"
        f"🎯 سیگنال: {result.get('signal')}\n"
        f"⭐ کیفیت: {result.get('quality', 'UNKNOWN')}\n"
        f"📊 امتیاز: {result.get('score', 0)}\n\n"
        f"💰 Entry: {result.get('entry', 'N/A')}\n"
        f"🛑 SL: {result.get('sl', 'N/A')}\n\n"
        f"🎯 TP1: {result.get('tp1', 'N/A')}\n"
        f"🎯 TP2: {result.get('tp2', 'N/A')}\n"
        f"🎯 TP3: {result.get('tp3', 'N/A')}\n\n"
        f"📐 Risk: {result.get('risk', 'N/A')}\n"
        f"⚖️ RR: 1:{result.get('rr', 'N/A')}\n\n"
        f"🧠 Strategies: {strategies}\n\n"
        f"📌 Tracker: معامله ثبت شد"
    )


def tracker_event_text(event):
    t = event["trade"]
    e = event["event"]
    p = event["price"]

    if e == "TP1":
        return (
            f"🎯 TP1 HIT\n\n🔹 {t['symbol']}\n📈 {t['direction']}\n"
            f"💰 Price: {p}\n\nTP1: {t['tp1']}\nTP2: {t['tp2']}\nTP3: {t['tp3']}"
        )
    if e == "TP2":
        return (
            f"🎯 TP2 HIT\n\n🔹 {t['symbol']}\n📈 {t['direction']}\n"
            f"💰 Price: {p}\n\nTP3: {t['tp3']}"
        )
    if e == "TP3":
        return (
            f"🏆 TP3 HIT\n\n🔹 {t['symbol']}\n📈 {t['direction']}\n"
            f"💰 Price: {p}\n\nنتیجه: TP3"
        )
    if e == "SL":
        return (
            f"🛑 SL HIT\n\n🔹 {t['symbol']}\n📉 {t['direction']}\n"
            f"💰 Price: {p}\n\nنتیجه: STOP LOSS"
        )
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 ربات ترید فعال است!\n\n"
        "📊 /price\n📈 /signal\n📊 /stats"
    )


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from market import get_futures_symbols

        message = "📊 Toobit USDT-M Futures\n\n"
        for symbol in get_futures_symbols()[:20]:
            try:
                message += f"🔹 {symbol}: ${get_price(symbol):,.6f}\n"
            except Exception:
                pass
        await update.message.reply_text(message)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در دریافت قیمت:\n{e}")


async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Manual scan also respects the same lock, so it cannot collide with auto scan.
    if _scan_lock.locked():
        await update.message.reply_text("⏳ یک اسکن بازار در حال اجراست. کمی صبر کن و دوباره /signal را بزن.")
        return

    async with _scan_lock:
        try:
            from market import get_futures_symbols, get_market_data

            symbols = get_futures_symbols()
            parts = ["🤖 CryptoBot Market Scan\n"]
            scanned = 0
            found = 0

            for symbol in symbols:
                try:
                    result = generate_signal(get_market_data(symbol))
                    scanned += 1
                    if result.get("signal") in ["LONG", "SHORT"]:
                        found += 1
                        strategies = ", ".join(result.get("strategy_matches", [])) or "N/A"
                        parts.append(
                            f"🚨 {symbol}\n"
                            f"🎯 Signal: {result.get('signal')}\n"
                            f"⭐ Quality: {result.get('quality', 'LOW')}\n"
                            f"📊 Score: {result.get('score', 0)}\n\n"
                            f"💰 Entry: {result.get('entry', 'N/A')}\n"
                            f"🛑 SL: {result.get('sl', 'N/A')}\n\n"
                            f"🎯 TP1: {result.get('tp1', 'N/A')}\n"
                            f"🎯 TP2: {result.get('tp2', 'N/A')}\n"
                            f"🎯 TP3: {result.get('tp3', 'N/A')}\n\n"
                            f"📐 Risk: {result.get('risk', 'N/A')}\n"
                            f"⚖️ RR: 1:{result.get('rr', 'N/A')}\n"
                            f"🧠 Strategies: {strategies}\n"
                        )
                except Exception as e:
                    print(f"SIGNAL_ERROR {symbol}: {e}")

            if not found:
                parts.append(
                    f"⚪ در حال حاضر سیگنال معتبری پیدا نشد.\n\n🔎 Symbols scanned: {scanned}"
                )

            msg = "\n".join(parts)
            await update.message.reply_text(
                msg[:3900] + ("\n\n⚠️ پیام کوتاه شد." if len(msg) > 3900 else "")
            )
        except Exception as e:
            await update.message.reply_text(f"❌ خطا در اسکن بازار:\n{e}")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text(format_stats())
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در آمار:\n{e}")


async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    # This extra guard protects us even if the scheduler is configured to allow overlap.
    if _scan_lock.locked():
        print("AUTO_SIGNAL_SKIPPED: previous market scan is still running")
        return

    async with _scan_lock:
        try:
            from market import get_futures_symbols, get_market_data

            # 1) Check existing trades first. This part is kept separate from market scanning.
            try:
                events = check_open_trades()
                for event in events:
                    msg = tracker_event_text(event)
                    if msg:
                        await context.bot.send_message(chat_id=CHAT_ID, text=msg)
            except Exception as e:
                print(f"TRACKER_CHECK_ERROR: {e}")

            # 2) Scan the market and register only new LONG/SHORT signals.
            symbols = get_futures_symbols()
            scanned = 0
            new_signals = 0

            for symbol in symbols:
                try:
                    result = generate_signal(get_market_data(symbol))
                    scanned += 1

                    if result.get("signal") not in ["LONG", "SHORT"]:
                        continue

                    trade, created = register_signal(symbol, result)
                    if not created:
                        continue

                    new_signals += 1
                    await context.bot.send_message(
                        chat_id=CHAT_ID,
                        text=signal_text(symbol, result),
                    )
                except Exception as e:
                    print(f"AUTO_SYMBOL_ERROR {symbol}: {e}")

            print(
                f"AUTO_SCAN_DONE: scanned={scanned}, new_signals={new_signals}"
            )

        except Exception as e:
            print("AUTO_SIGNAL_ERROR:", e)


app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("price", price))
app.add_handler(CommandHandler("signal", signal))
app.add_handler(CommandHandler("stats", stats))

# Only one automatic scan instance is allowed at a time.
app.job_queue.run_repeating(
    auto_signal,
    interval=AUTO_INTERVAL,
    first=10,
    job_kwargs={"max_instances": 1, "coalesce": True},
)

app.run_polling()
