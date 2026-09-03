def find_swings(candles, strength=2):
    swing_highs = []
    swing_lows = []

    for i in range(strength, len(candles) - strength):
        current_high = candles[i]["high"]
        current_low = candles[i]["low"]

        left_highs = [
            candles[j]["high"]
            for j in range(i - strength, i)
        ]

        right_highs = [
            candles[j]["high"]
            for j in range(i + 1, i + strength + 1)
        ]

        left_lows = [
            candles[j]["low"]
            for j in range(i - strength, i)
        ]

        right_lows = [
            candles[j]["low"]
            for j in range(i + 1, i + strength + 1)
        ]

        if current_high > max(left_highs + right_highs):
            swing_highs.append({
                "index": i,
                "price": current_high
            })

        if current_low < min(left_lows + right_lows):
            swing_lows.append({
                "index": i,
                "price": current_low
            })

    return swing_highs, swing_lows


def get_structure_direction(candles):
    swing_highs, swing_lows = find_swings(candles)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "UNKNOWN"

    previous_high = swing_highs[-2]["price"]
    last_high = swing_highs[-1]["price"]

    previous_low = swing_lows[-2]["price"]
    last_low = swing_lows[-1]["price"]

    if last_high > previous_high and last_low > previous_low:
        return "BULLISH"

    if last_high < previous_high and last_low < previous_low:
        return "BEARISH"

    return "RANGE"


def analyze_all_timeframes(market_data):
    result = {}

    for timeframe in ["daily", "4h", "1h"]:
        result[timeframe] = get_structure_direction(
            market_data[timeframe]
        )

    return result


def check_trend_alignment(market_data):
    analysis = analyze_all_timeframes(market_data)

    daily = analysis["daily"]
    four_hour = analysis["4h"]
    one_hour = analysis["1h"]

    if daily == "BULLISH" and four_hour == "BULLISH":
        setup = "LONG_BIAS"

    elif daily == "BEARISH" and four_hour == "BEARISH":
        setup = "SHORT_BIAS"

    else:
        setup = "NO_SETUP"

    return {
        "daily": daily,
        "4h": four_hour,
        "1h": one_hour,
        "setup": setup
    }

def detect_pullback(candles, lookback=10):
    if len(candles) < lookback:
        return "UNKNOWN"

    recent = candles[-lookback:]

    highest = max(c["high"] for c in recent)
    lowest = min(c["low"] for c in recent)
    last_close = recent[-1]["close"]

    price_range = highest - lowest

    if price_range == 0:
        return "NO_PULLBACK"

    position = (last_close - lowest) / price_range

    if position < 0.35:
        return "PULLBACK_DOWN"

    if position > 0.65:
        return "PULLBACK_UP"

    return "NO_PULLBACK"


def detect_bos(candles):
    swing_highs, swing_lows = find_swings(candles)

    if len(swing_highs) < 1 or len(swing_lows) < 1:
        return "NO_BOS"

    last_candle = candles[-1]

    last_swing_high = swing_highs[-1]["price"]
    last_swing_low = swing_lows[-1]["price"]

    if last_candle["close"] > last_swing_high:
        return "BULLISH_BOS"

    if last_candle["close"] < last_swing_low:
        return "BEARISH_BOS"

    return "NO_BOS"


def confirmation_candle(candles, direction):
    if len(candles) < 1:
        return False

    candle = candles[-1]

    open_price = candle["open"]
    close_price = candle["close"]

    if direction == "LONG":
        return close_price > open_price

    if direction == "SHORT":
        return close_price < open_price

    return False


    def generate_signal(market_data):
        alignment = check_trend_alignment(market_data)

    daily = alignment["daily"]
    four_hour = alignment["4h"]

    if daily == "BULLISH" and four_hour == "BULLISH":
        direction = "LONG"

    elif daily == "BEARISH" and four_hour == "BEARISH":
        direction = "SHORT"

    else:
        return {
            "signal": "NO_TRADE",
            "reason": "TIMEFRAME_NOT_ALIGNED"
        }

    candles_1h = market_data["1h"]

    bos = detect_bos(candles_1h)
    pullback = detect_pullback(candles_1h)
    confirmation = confirmation_candle(candles_1h, direction)

    if direction == "LONG":
        if bos != "BULLISH_BOS":
            return {
                "signal": "NO_TRADE",
                "reason": "NO_BULLISH_BOS"
            }

        if pullback != "PULLBACK_DOWN":
            return {
                "signal": "NO_TRADE",
                "reason": "NO_PULLBACK"
            }

        if not confirmation:
            return {
                "signal": "NO_TRADE",
                "reason": "NO_CONFIRMATION"
            }

        return {
            "signal": "LONG",
            "reason": "ALL_CONFIRMATIONS"
        }

    if direction == "SHORT":
        if bos != "BEARISH_BOS":
            return {
                "signal": "NO_TRADE",
                "reason": "NO_BEARISH_BOS"
            }

        if pullback != "PULLBACK_UP":
            return {
                "signal": "NO_TRADE",
                "reason": "NO_PULLBACK"
            }

        if not confirmation:
            return {
                "signal": "NO_TRADE",
                "reason": "NO_CONFIRMATION"
            }

        return {
            "signal": "SHORT",
            "reason": "ALL_CONFIRMATIONS"
        }


        def generate_signal(market_data):
            alignment = check_trend_alignment(market_data)

    daily = alignment["daily"]
    four_hour = alignment["4h"]

    if daily == "BULLISH" and four_hour == "BULLISH":
        direction = "LONG"
    elif daily == "BEARISH" and four_hour == "BEARISH":
        direction = "SHORT"
    else:
        return {
            "signal": "NO_TRADE",
            "reason": "TIMEFRAME_NOT_ALIGNED"
        }

    candles_1h = market_data["1h"]

    bos = detect_bos(candles_1h)
    pullback = detect_pullback(candles_1h)
    confirmation = confirmation_candle(candles_1h, direction)

    if direction == "LONG":
        if bos != "BULLISH_BOS":
            return {
                "signal": "NO_TRADE",
                "reason": "NO_BULLISH_BOS"
            }

        if pullback != "PULLBACK_DOWN":
            return {
                "signal": "NO_TRADE",
                "reason": "NO_PULLBACK"
            }

        if not confirmation:
            return {
                "signal": "NO_TRADE",
                "reason": "NO_CONFIRMATION"
            }

        return {
            "signal": "LONG",
            "reason": "ALL_CONFIRMATIONS"
        }

    if direction == "SHORT":
        if bos != "BEARISH_BOS":
            return {
                "signal": "NO_TRADE",
                "reason": "NO_BEARISH_BOS"
            }

        if pullback != "PULLBACK_UP":
            return {
                "signal": "NO_TRADE",
                "reason": "NO_PULLBACK"
            }

        if not confirmation:
            return {
                "signal": "NO_TRADE",
                "reason": "NO_CONFIRMATION"
            }

        return {
            "signal": "SHORT",
            "reason": "ALL_CONFIRMATIONS"
        }


def generate_signal(market_data):
    alignment = check_trend_alignment(market_data)

    daily = alignment["daily"]
    four_hour = alignment["4h"]
    one_hour = alignment["1h"]

    candles_1h = market_data["1h"]

    bos = detect_bos(candles_1h)
    pullback = detect_pullback(candles_1h)

    if daily == "BULLISH" and four_hour == "BULLISH":
        direction = "LONG"
    elif daily == "BEARISH" and four_hour == "BEARISH":
        direction = "SHORT"
    else:
        return {
            "daily": daily,
            "4h": four_hour,
            "1h": one_hour,
            "bos": bos,
            "pullback": pullback,
            "confirmation": False,
            "signal": "NO_TRADE",
            "reason": "TIMEFRAME_NOT_ALIGNED"
        }

    confirmation = confirmation_candle(
        candles_1h,
        direction
    )

    if direction == "LONG":

        if bos != "BULLISH_BOS":
            return {
                "daily": daily,
                "4h": four_hour,
                "1h": one_hour,
                "bos": bos,
                "pullback": pullback,
                "confirmation": confirmation,
                "signal": "NO_TRADE",
                "reason": "NO_BULLISH_BOS"
            }

        if pullback != "PULLBACK_DOWN":
            return {
                "daily": daily,
                "4h": four_hour,
                "1h": one_hour,
                "bos": bos,
                "pullback": pullback,
                "confirmation": confirmation,
                "signal": "NO_TRADE",
                "reason": "NO_PULLBACK"
            }

        if not confirmation:
            return {
                "daily": daily,
                "4h": four_hour,
                "1h": one_hour,
                "bos": bos,
                "pullback": pullback,
                "confirmation": confirmation,
                "signal": "NO_TRADE",
                "reason": "NO_CONFIRMATION"
            }

        return {
            "daily": daily,
            "4h": four_hour,
            "1h": one_hour,
            "bos": bos,
            "pullback": pullback,
            "confirmation": confirmation,
            "signal": "LONG",
            "reason": "ALL_CONFIRMATIONS"
        }

    if direction == "SHORT":

        if bos != "BEARISH_BOS":
            return {
                "daily": daily,
                "4h": four_hour,
                "1h": one_hour,
                "bos": bos,
                "pullback": pullback,
                "confirmation": confirmation,
                "signal": "NO_TRADE",
                "reason": "NO_BEARISH_BOS"
            }

        if pullback != "PULLBACK_UP":
            return {
                "daily": daily,
                "4h": four_hour,
                "1h": one_hour,
                "bos": bos,
                "pullback": pullback,
                "confirmation": confirmation,
                "signal": "NO_TRADE",
                "reason": "NO_PULLBACK"
            }

        if not confirmation:
            return {
                "daily": daily,
                "4h": four_hour,
                "1h": one_hour,
                "bos": bos,
                "pullback": pullback,
                "confirmation": confirmation,
                "signal": "NO_TRADE",
                "reason": "NO_CONFIRMATION"
            }

        return {
            "daily": daily,
            "4h": four_hour,
            "1h": one_hour,
            "bos": bos,
            "pullback": pullback,
            "confirmation": confirmation,
            "signal": "SHORT",
            "reason": "ALL_CONFIRMATIONS"
        }
























