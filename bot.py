import requests
import os
from analysis import generate_signal
from tracker import register_signal, check_open_trades, format_stats
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = 6912201079

def get_price(symbol):
    r=requests.get("https://api.toobit.com/quote/v1/contract/ticker/price",params={"symbol":symbol},timeout=10)
    r.raise_for_status(); return float(r.json()[0]["p"])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 ربات ترید فعال است!\n\n📊 /price\n📈 /signal\n📊 /stats")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from market import get_futures_symbols
        message="📊 Toobit USDT-M Futures\n\n"
        for symbol in get_futures_symbols()[:20]:
            try: message += f"🔹 {symbol}: ${get_price(symbol):,.6f}\n"
            except Exception: pass
        await update.message.reply_text(message)
    except Exception as e: await update.message.reply_text(f"❌ خطا در دریافت قیمت:\n{e}")

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from market import get_futures_symbols, get_market_data
        parts=["🤖 CryptoBot Market Scan\n"]; scanned=0; found=0
        for symbol in get_futures_symbols():
            try:
                result=generate_signal(get_market_data(symbol)); scanned+=1
                if result.get("signal") in ["LONG","SHORT"]:
                    found+=1; st=", ".join(result.get("strategy_matches",[]))
                    parts.append(f"🚨 {symbol}\n🎯 Signal: {result.get('signal')}\n⭐ Quality: {result.get('quality','LOW')}\n📊 Score: {result.get('score',0)}\n\n💰 Entry: {result.get('entry','N/A')}\n🛑 SL: {result.get('sl','N/A')}\n\n🎯 TP1: {result.get('tp1','N/A')}\n🎯 TP2: {result.get('tp2','N/A')}\n🎯 TP3: {result.get('tp3','N/A')}\n\n📐 Risk: {result.get('risk','N/A')}\n⚖️ RR: 1:{result.get('rr','N/A')}\n🧠 Strategies: {st}\n")
            except Exception as e: print(f"SIGNAL_ERROR {symbol}: {e}")
        if not found: parts.append(f"⚪ در حال حاضر سیگنال معتبری پیدا نشد.\n\n🔎 Symbols scanned: {scanned}")
        msg="\n".join(parts); await update.message.reply_text(msg[:3900]+("\n\n⚠️ پیام کوتاه شد." if len(msg)>3900 else ""))
    except Exception as e: await update.message.reply_text(f"❌ خطا در اسکن بازار:\n{e}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: await update.message.reply_text(format_stats())
    except Exception as e: await update.message.reply_text(f"❌ خطا در آمار:\n{e}")

async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    try:
        from market import get_futures_symbols, get_market_data
        for event in check_open_trades():
            t=event["trade"]; e=event["event"]; p=event["price"]
            if e=="TP1": msg=f"🎯 TP1 HIT\n\n🔹 {t['symbol']}\n📈 {t['direction']}\n💰 Price: {p}\n\nTP1: {t['tp1']}\nTP2: {t['tp2']}\nTP3: {t['tp3']}"
            elif e=="TP2": msg=f"🎯 TP2 HIT\n\n🔹 {t['symbol']}\n📈 {t['direction']}\n💰 Price: {p}\n\nTP3: {t['tp3']}"
            elif e=="TP3": msg=f"🏆 TP3 HIT\n\n🔹 {t['symbol']}\n📈 {t['direction']}\n💰 Price: {p}\n\nنتیجه: TP3"
            elif e=="SL": msg=f"🛑 SL HIT\n\n🔹 {t['symbol']}\n📉 {t['direction']}\n💰 Price: {p}\n\nنتیجه: STOP LOSS"
            else: continue
            await context.bot.send_message(chat_id=CHAT_ID,text=msg)
        for symbol in get_futures_symbols():
            try:
                result=generate_signal(get_market_data(symbol))
                if result.get("signal") not in ["LONG","SHORT"]: continue
                trade,created=register_signal(symbol,result)
                if not created: continue
                st=", ".join(result.get("strategy_matches",[]))
                await context.bot.send_message(chat_id=CHAT_ID,text=f"🚨 {symbol}\n\n🎯 سیگنال: {result['signal']}\n⭐ کیفیت: {result.get('quality','UNKNOWN')}\n📊 امتیاز: {result.get('score',0)}\n\n💰 Entry: {result.get('entry','N/A')}\n🛑 SL: {result.get('sl','N/A')}\n\n🎯 TP1: {result.get('tp1','N/A')}\n🎯 TP2: {result.get('tp2','N/A')}\n🎯 TP3: {result.get('tp3','N/A')}\n\n📐 Risk: {result.get('risk','N/A')}\n⚖️ RR: 1:{result.get('rr','N/A')}\n\n🧠 Strategies: {st}\n\n📌 Tracker: معامله ثبت شد")
            except Exception as e: print(f"AUTO_SYMBOL_ERROR {symbol}: {e}")
    except Exception as e: print("AUTO_SIGNAL_ERROR:",e)

app=Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("price",price)); app.add_handler(CommandHandler("signal",signal)); app.add_handler(CommandHandler("stats",stats))
app.job_queue.run_repeating(auto_signal,interval=300,first=10)
app.run_polling()
