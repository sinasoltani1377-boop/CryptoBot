# ============================================================
# backtest_runner.py — Run this on Belmo to test strategies
# ============================================================

import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime

TOOBIT_URL = "https://api.toobit.com/quote/v1/klines"

def fetch_data(symbol, interval, days=365):
    end_ts = int(time.time() * 1000)
    start_ts = end_ts - (days * 24 * 60 * 60 * 1000)
    
    all_candles = []
    current_ts = start_ts
    print(f"Downloading {symbol} data for past {days} days...")
    
    while current_ts < end_ts:
        try:
            params = {
                "symbol": symbol, "interval": interval,
                "startTime": current_ts, "limit": 1000
            }
            response = requests.get(TOOBIT_URL, params=params, timeout=10)
            data = response.json()
            if not data:
                break
            for row in data:
                all_candles.append({
                    "time": row[0], "open": float(row[1]), "high": float(row[2]),
                    "low": float(row[3]), "close": float(row[4]), "volume": float(row[5])
                })
            current_ts = data[-1][0] + 1
            time.sleep(0.1)
        except Exception as e:
            print(f"Error fetching data: {e}")
            break

    df = pd.DataFrame(all_candles)
    df.drop_duplicates(subset=['time'], inplace=True)
    df.set_index('time', inplace=True)
    return df

def calculate_indicators(df):
    # Bollinger Bands
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std'] = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['sma20'] + (df['std'] * 2)
    df['bb_lower'] = df['sma20'] - (df['std'] * 2)
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = -delta.clip(upper=0).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def run_backtest(df, initial_capital=1000, risk_per_trade=0.01):
    capital = initial_capital
    position = None
    entry_price = 0
    tp_price = 0
    sl_price = 0
    
    wins = 0
    losses = 0
    total_trades = 0
    
    for i in range(20, len(df)):
        current_close = df['close'].iloc[i]
        current_high = df['high'].iloc[i]
        current_low = df['low'].iloc[i]
        
        # --- بررسی خروج از معامله (اگر پوزیشن باز داریم) ---
        if position == "LONG":
            if current_low <= sl_price:
                capital -= (capital * risk_per_trade)
                losses += 1
                position = None
            elif current_high >= tp_price:
                capital += (capital * risk_per_trade * 1.5) # فرض ریوارد 1.5
                wins += 1
                position = None
                
        elif position == "SHORT":
            if current_high >= sl_price:
                capital -= (capital * risk_per_trade)
                losses += 1
                position = None
            elif current_low <= tp_price:
                capital += (capital * risk_per_trade * 1.5)
                wins += 1
                position = None

        # --- بررسی ورود به معامله جدید (اگر پوزیشن باز نداریم) ---
        if position is None:
            # شرایط ورود LONG (خرید)
            if current_close <= df['bb_lower'].iloc[i] and df['rsi'].iloc[i] <= 32:
                position = "LONG"
                entry_price = current_close
                sl_price = entry_price * 0.98  # استاپ ۲٪
                tp_price = entry_price * 1.03  # تارگت ۳٪
                total_trades += 1
                
            # شرایط ورود SHORT (فروش)
            elif current_close >= df['bb_upper'].iloc[i] and df['rsi'].iloc[i] >= 68:
                position = "SHORT"
                entry_price = current_close
                sl_price = entry_price * 1.02
                tp_price = entry_price * 0.97
                total_trades += 1
                
    return capital, wins, losses, total_trades

if __name__ == "__main__":
    print("="*50)
    print("🤖 CRYPTO BOT BACKTEST STARTING...")
    print("="*50)
    
    df = fetch_data("BTC-SWAP-USDT", "1h", days=365)
    if len(df) == 0:
        print("❌ Failed to download data.")
    else:
        print(f"✅ Downloaded {len(df)} candles.")
        df = calculate_indicators(df)
        final_capital, wins, losses, total = run_backtest(df)
        
        win_rate = (wins / total * 100) if total > 0 else 0
        total_return = ((final_capital - 1000) / 1000) * 100
        
        print("\n" + "="*50)
        print("📊 BACKTEST RESULTS")
        print("="*50)
        print(f"💰 Initial Capital: 1000.00 USDT")
        print(f"💰 Final Capital:   {final_capital:.2f} USDT")
        print(f"📈 Total Return:    {total_return:.2f}%")
        print(f"🎯 Total Trades:    {total}")
        print(f"✅ Wins:            {wins}")
        print(f"❌ Losses:          {losses}")
        print(f"⚖️ Win Rate:        {win_rate:.2f}%")
        print("="*50)
