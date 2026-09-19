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
        "daily": get_candles(symbol, "1d", 100),
        "4h": get_candles(symbol, "4h", 100),
        "1h": get_candles(symbol, "1h", 100),
        "15m": get_candles(symbol, "15m", 100),
        "5m": get_candles(symbol, "5m", 100)
    }


def get_futures_symbols():
    """
    دریافت قراردادهای USDT-M Futures فعال از Toobit.
    """

    url = f"{BASE_URL}/api/v1/exchangeInfo"

    response = requests.get(
        url,
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    contracts = data.get("contracts", [])

    symbols = []

    for contract in contracts:

        symbol = contract.get("symbol", "")

        status = str(
            contract.get("status", "")
        ).upper()

        if not symbol.endswith("-SWAP-USDT"):
            continue

        if status and status not in {
            "TRADING",
            "1",
            "ONLINE",
            "ACTIVE"
        }:
            continue

        symbols.append(symbol)

    return sorted(set(symbols))


if __name__ == "__main__":

    print("\n========== TOOBIT USDT-M FUTURES ==========\n")

    try:

        symbols = get_futures_symbols()

        print(f"Found {len(symbols)} Futures symbols:\n")

        for symbol in symbols:
            print(symbol)

    except Exception as e:

        print("Error getting Futures symbols:")
        print(e)

    print("\n========== MARKET DATA TEST ==========\n")

    for symbol in [
        "BTC-SWAP-USDT",
        "SOL-SWAP-USDT"
    ]:

        try:

            data = get_market_data(symbol)

            print("\n====================")
            print(symbol)
            print("====================")

            for timeframe, candles in data.items():

                if not candles:
                    print(f"{timeframe}: NO DATA")
                    continue

                last = candles[-1]

                print(
                    f"{timeframe}: "
                    f"O={last['open']} "
                    f"H={last['high']} "
                    f"L={last['low']} "
                    f"C={last['close']}"
                )

        except Exception as e:

            print(f"{symbol} ERROR:")
            print(e)
