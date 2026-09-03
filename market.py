import requests


BASE_URL = "https://api.toobit.com"


def get_candles(symbol, interval, limit=100):
    url = f"{BASE_URL}/quote/v1/klines"

    response = requests.get(
        url,
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        },
        timeout=10
    )

    response.raise_for_status()

    raw_data = response.json()

    candles = []

    for candle in raw_data:
        candles.append({
            "time": candle[0],
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5])
        })

    return candles


def get_market_data(symbol):
    return {
        "daily": get_candles(symbol, "1d"),
        "4h": get_candles(symbol, "4h"),
        "1h": get_candles(symbol, "1h")
    }


if __name__ == "__main__":
    for symbol in ["BTC-SWAP-USDT", "SOL-SWAP-USDT"]:
        data = get_market_data(symbol)

        print("\n====================")
        print(symbol)
        print("====================")

        for timeframe, candles in data.items():
            last = candles[-1]

            print(
                f"{timeframe}: "
                f"O={last['open']} "
                f"H={last['high']} "
                f"L={last['low']} "
                f"C={last['close']}"
            )