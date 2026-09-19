# ============================================================
# CryptoBot - Analysis Engine v7
# ONLY:
# 1. STOP HUNT
# 2. THREE TAP
# 3. LIQUIDITY ZONE
#
# EMA / RSI / VOLUME = FILTERS ONLY
# ============================================================

from math import isfinite


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value, default=0.0):
    try:
        value = float(value)
        if isfinite(value):
            return value
    except (TypeError, ValueError):
        pass

    return default


def normalize_candle(candle):

    if isinstance(candle, dict):

        o = safe_float(candle.get("open", candle.get("o")))
        h = safe_float(candle.get("high", candle.get("h")))
        l = safe_float(candle.get("low", candle.get("l")))
        c = safe_float(candle.get("close", candle.get("c")))
        v = safe_float(candle.get("volume", candle.get("v")))

        t = candle.get(
            "timestamp",
            candle.get("time", candle.get("t"))
        )

        if min(o, h, l, c) <= 0:
            return None

        if h < l:
            return None

        return {
            "timestamp": t,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
        }

    if isinstance(candle, (list, tuple)):

        if len(candle) < 5:
            return None

        o = safe_float(candle[1])
        h = safe_float(candle[2])
        l = safe_float(candle[3])
        c = safe_float(candle[4])

        if min(o, h, l, c) <= 0:
            return None

        if h < l:
            return None

        v = safe_float(candle[5]) if len(candle) > 5 else 0.0

        return {
            "timestamp": candle[0],
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
        }

    return None


def clean_candles(candles):

    if not isinstance(candles, (list, tuple)):
        return []

    result = []

    for candle in candles:

        normalized = normalize_candle(candle)

        if normalized:
            result.append(normalized)

    return result


def get_closes(candles):
    return [c["close"] for c in candles]


def get_highs(candles):
    return [c["high"] for c in candles]


def get_lows(candles):
    return [c["low"] for c in candles]


# ============================================================
# EMA
# ============================================================

def calculate_ema(candles, period):

    candles = clean_candles(candles)

    if len(candles) < period:
        return None

    closes = get_closes(candles)

    multiplier = 2 / (period + 1)

    ema = sum(closes[:period]) / period

    for price in closes[period:]:
        ema = (
            (price - ema) * multiplier
            + ema
        )

    return ema


def ema_trend(candles):

    candles = clean_candles(candles)

    if len(candles) < 200:
        return "UNKNOWN"

    ema50 = calculate_ema(candles, 50)
    ema200 = calculate_ema(candles, 200)

    if ema50 is None or ema200 is None:
        return "UNKNOWN"

    close = candles[-1]["close"]

    if close > ema200 and ema50 > ema200:
        return "BULLISH"

    if close < ema200 and ema50 < ema200:
        return "BEARISH"

    return "RANGE"


# ============================================================
# RSI
# ============================================================

def calculate_rsi(candles, period=14):

    candles = clean_candles(candles)

    closes = get_closes(candles)

    if len(closes) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):

        change = closes[i] - closes[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    if len(gains) < period:
        return None

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# STRUCTURE
# ============================================================

def find_swings(candles, strength=2):

    candles = clean_candles(candles)

    highs = []
    lows = []

    if len(candles) < strength * 2 + 1:
        return highs, lows

    for i in range(
        strength,
        len(candles) - strength
    ):

        current_high = candles[i]["high"]
        current_low = candles[i]["low"]

        left_highs = [
            candles[j]["high"]
            for j in range(i - strength, i)
        ]

        right_highs = [
            candles[j]["high"]
            for j in range(
                i + 1,
                i + strength + 1
            )
        ]

        left_lows = [
            candles[j]["low"]
            for j in range(i - strength, i)
        ]

        right_lows = [
            candles[j]["low"]
            for j in range(
                i + 1,
                i + strength + 1
            )
        ]

        if current_high > max(
            left_highs + right_highs
        ):
            highs.append({
                "index": i,
                "price": current_high
            })

        if current_low < min(
            left_lows + right_lows
        ):
            lows.append({
                "index": i,
                "price": current_low
            })

    return highs, lows


def get_structure_direction(candles):

    candles = clean_candles(candles)

    highs, lows = find_swings(candles)

    if len(highs) < 2 or len(lows) < 2:
        return "RANGE"

    last_high = highs[-1]["price"]
    previous_high = highs[-2]["price"]

    last_low = lows[-1]["price"]
    previous_low = lows[-2]["price"]

    if (
        last_high > previous_high
        and last_low > previous_low
    ):
        return "BULLISH"

    if (
        last_high < previous_high
        and last_low < previous_low
    ):
        return "BEARISH"

    return "RANGE"


# ============================================================
# 1H TREND FILTER
# ============================================================

def get_1h_direction(h1):

    structure = get_structure_direction(h1)
    ema = ema_trend(h1)

    if (
        structure == "BULLISH"
        and ema == "BULLISH"
    ):
        return "LONG"

    if (
        structure == "BEARISH"
        and ema == "BEARISH"
    ):
        return "SHORT"

    return None


# ============================================================
# VOLUME FILTER
# ============================================================

def volume_spike(candles, lookback=20, multiplier=1.5):

    candles = clean_candles(candles)

    if len(candles) < lookback + 1:
        return False

    current_volume = candles[-1]["volume"]

    previous = candles[-lookback - 1:-1]

    volumes = [
        c["volume"]
        for c in previous
        if c["volume"] > 0
    ]

    if not volumes:
        return False

    average_volume = sum(volumes) / len(volumes)

    if average_volume <= 0:
        return False

    return current_volume >= (
        average_volume * multiplier
    )


# ============================================================
# STOP HUNT
# ============================================================

def detect_stop_hunt(
    candles,
    lookback=20,
    wick_ratio=2.0
):

    candles = clean_candles(candles)

    if len(candles) < lookback + 2:
        return None

    current = candles[-1]

    previous = candles[-lookback - 1:-1]

    previous_low = min(
        c["low"] for c in previous
    )

    previous_high = max(
        c["high"] for c in previous
    )

    body = abs(
        current["close"]
        - current["open"]
    )

    if body <= 0:
        body = 0.00000001

    lower_wick = (
        min(
            current["open"],
            current["close"]
        )
        - current["low"]
    )

    upper_wick = (
        current["high"]
        - max(
            current["open"],
            current["close"]
        )
    )

    # --------------------------------------------------------
    # LONG STOP HUNT
    # --------------------------------------------------------

    long_signal = (
        lower_wick >= body * wick_ratio
        and current["low"] < previous_low
        and current["close"] > previous_low
    )

    if long_signal:

        return {
            "side": "LONG",
            "level": previous_low,
            "sweep": current["low"],
            "entry": current["close"],
            "wick": lower_wick,
            "body": body,
            "reason": "Liquidity swept below previous low and price reclaimed the level."
        }

    # --------------------------------------------------------
    # SHORT STOP HUNT
    # --------------------------------------------------------

    short_signal = (
        upper_wick >= body * wick_ratio
        and current["high"] > previous_high
        and current["close"] < previous_high
    )

    if short_signal:

        return {
            "side": "SHORT",
            "level": previous_high,
            "sweep": current["high"],
            "entry": current["close"],
            "wick": upper_wick,
            "body": body,
            "reason": "Liquidity swept above previous high and price rejected back below the level."
        }

    return None


# ============================================================
# THREE TAP
# ============================================================

def detect_three_tap(
    candles,
    tolerance=0.003
):

    candles = clean_candles(candles)

    if len(candles) < 30:
        return None

    highs, lows = find_swings(
        candles,
        strength=2
    )

    # --------------------------------------------------------
    # THREE LOW TAPS = LONG
    # --------------------------------------------------------

    if len(lows) >= 3:

        last_three = lows[-3:]

        prices = [
            x["price"]
            for x in last_three
        ]

        average = sum(prices) / 3

        similar = all(
            abs(price - average) / average
            <= tolerance
            for price in prices
        )

        if similar:

            current = candles[-1]

            if current["close"] > current["open"]:

                return {
                    "side": "LONG",
                    "level": average,
                    "reason": "Three similar swing-low taps with bullish reaction."
                }

    # --------------------------------------------------------
    # THREE HIGH TAPS = SHORT
    # --------------------------------------------------------

    if len(highs) >= 3:

        last_three = highs[-3:]

        prices = [
            x["price"]
            for x in last_three
        ]

        average = sum(prices) / 3

        similar = all(
            abs(price - average) / average
            <= tolerance
            for price in prices
        )

        if similar:

            current = candles[-1]

            if current["close"] < current["open"]:

                return {
                    "side": "SHORT",
                    "level": average,
                    "reason": "Three similar swing-high taps with bearish reaction."
                }

    return None


# ============================================================
# LIQUIDITY ZONE
# ============================================================

def detect_liquidity_zone(
    candles,
    tolerance=0.003
):

    candles = clean_candles(candles)

    if len(candles) < 30:
        return None

    highs, lows = find_swings(
        candles,
        strength=2
    )

    current = candles[-1]

    # --------------------------------------------------------
    # LOW LIQUIDITY ZONE
    # --------------------------------------------------------

    if len(lows) >= 2:

        last_lows = lows[-5:]

        for i in range(len(last_lows)):

            for j in range(i + 1, len(last_lows)):

                a = last_lows[i]["price"]
                b = last_lows[j]["price"]

                difference = abs(a - b) / ((a + b) / 2)

                if difference <= tolerance:

                    zone = (a + b) / 2

                    if (
                        current["low"] < zone
                        and current["close"] > zone
                    ):

                        return {
                            "side": "LONG",
                            "zone": zone,
                            "reason": "Price swept a clustered liquidity zone and reclaimed it."
                        }

    # --------------------------------------------------------
    # HIGH LIQUIDITY ZONE
    # --------------------------------------------------------

    if len(highs) >= 2:

        last_highs = highs[-5:]

        for i in range(len(last_highs)):

            for j in range(i + 1, len(last_highs)):

                a = last_highs[i]["price"]
                b = last_highs[j]["price"]

                difference = abs(a - b) / ((a + b) / 2)

                if difference <= tolerance:

                    zone = (a + b) / 2

                    if (
                        current["high"] > zone
                        and current["close"] < zone
                    ):

                        return {
                            "side": "SHORT",
                            "zone": zone,
                            "reason": "Price swept a clustered liquidity zone and rejected below it."
                        }

    return None


# ============================================================
# CONFIRMATION CANDLE
# ============================================================

def confirmation_candle(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 2:
        return False

    previous = candles[-2]
    current = candles[-1]

    previous_body = abs(
        previous["close"]
        - previous["open"]
    )

    current_body = abs(
        current["close"]
        - current["open"]
    )

    if previous_body <= 0:
        return False

    if current_body < previous_body * 1.05:
        return False

    if direction == "LONG":

        return (
            current["close"] > current["open"]
            and current["close"] > previous["close"]
        )

    if direction == "SHORT":

        return (
            current["close"] < current["open"]
            and current["close"] < previous["close"]
        )

    return False


# ============================================================
# 15M FILTER
# ============================================================

def check_15m_filter(
    candles,
    direction
):

    rsi = calculate_rsi(
        candles,
        14
    )

    if rsi is None:
        return False, None, "RSI_UNAVAILABLE"

    # We don't enter when market is extremely overextended.
    if direction == "LONG":

        if rsi >= 70:
            return False, rsi, "RSI_OVERBOUGHT"

    if direction == "SHORT":

        if rsi <= 30:
            return False, rsi, "RSI_OVERSOLD"

    return True, rsi, "RSI_OK"


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_trade_levels(
    candles,
    direction,
    signal_data
):

    candles = clean_candles(candles)

    if len(candles) < 5:
        return None

    entry = signal_data.get(
        "entry",
        candles[-1]["close"]
    )

    sweep = signal_data.get("sweep")

    zone = signal_data.get("zone")

    level = signal_data.get("level")

    if direction == "LONG":

        candidates = [
            x for x in (
                sweep,
                zone,
                level
            )
            if x is not None and x > 0
        ]

        if candidates:
            base = min(candidates)
        else:
            base = min(
                c["low"]
                for c in candles[-6:]
            )

        sl = base * 0.999

        risk = entry - sl

        if risk <= 0:
            return None

        tp1 = entry + risk
        tp2 = entry + risk * 2
        tp3 = entry + risk * 3

    elif direction == "SHORT":

        candidates = [
            x for x in (
                sweep,
                zone,
                level
            )
            if x is not None and x > 0
        ]

        if candidates:
            base = max(candidates)
        else:
            base = max(
                c["high"]
                for c in candles[-6:]
            )

        sl = base * 1.001

        risk = sl - entry

        if risk <= 0:
            return None

        tp1 = entry - risk
        tp2 = entry - risk * 2
        tp3 = entry - risk * 3

    else:
        return None

    return {
        "entry": round(entry, 8),
        "sl": round(sl, 8),
        "tp1": round(tp1, 8),
        "tp2": round(tp2, 8),
        "tp3": round(tp3, 8),
        "risk": round(risk, 8),
        "rr_tp1": 1.0,
        "rr_tp2": 2.0,
        "rr_tp3": 3.0,
    }


# ============================================================
# SCORE
# ============================================================

def calculate_score(
    strategy_count,
    volume_ok,
    confirmation_ok,
    rsi_ok
):

    score = 0

    # Main strategy
    if strategy_count >= 1:
        score += 4

    # Multiple strategies agree
    if strategy_count >= 2:
        score += 2

    # Volume
    if volume_ok:
        score += 1

    # Confirmation
    if confirmation_ok:
        score += 2

    # RSI
    if rsi_ok:
        score += 1

    return min(score, 10)


def quality_from_score(score):

    if score >= 8:
        return "HIGH"

    if score >= 6:
        return "MEDIUM"

    return "LOW"


# ============================================================
# NO TRADE
# ============================================================

def no_trade_result(
    daily="UNKNOWN",
    h4="UNKNOWN",
    h1="UNKNOWN",
    reason="NO_TRADE"
):

    return {
        "signal": "NO_TRADE",
        "direction": None,

        "quality": "LOW",
        "score": 0,

        "reason": reason,

        "daily": daily,
        "4h": h4,
        "1h": h1,

        "entry": None,
        "sl": None,

        "tp1": None,
        "tp2": None,
        "tp3": None,

        "risk": None,

        "rr": None,
        "rr_tp1": None,
        "rr_tp2": None,
        "rr_tp3": None,

        "strategies": [],
        "strategy_matches": [],

        "strategy_details": {},

        "stop_hunt": None,
        "three_tap": None,
        "liquidity_zone": None,

        "volume_spike": False,

        "ema": None,
        "rsi": None,

        "confirmation": False,
    }


# ============================================================
# MAIN ENGINE
# ============================================================

def generate_signal(
    daily,
    h4,
    h1,
    m15=None,
    m5=None
):

    daily = clean_candles(daily)
    h4 = clean_candles(h4)
    h1 = clean_candles(h1)

    # --------------------------------------------------------
    # NEW ENGINE REQUIRES 15M + 5M
    # --------------------------------------------------------

    if m15 is None or m5 is None:

        return no_trade_result(
            reason="MISSING_15M_OR_5M_DATA"
        )

    m15 = clean_candles(m15)
    m5 = clean_candles(m5)

    if not daily or not h4 or not h1:
        return no_trade_result(
            reason="MISSING_MARKET_DATA"
        )

    if len(h1) < 200:
        return no_trade_result(
            reason="INSUFFICIENT_1H_DATA"
        )

    if len(m15) < 30:
        return no_trade_result(
            reason="INSUFFICIENT_15M_DATA"
        )

    if len(m5) < 25:
        return no_trade_result(
            reason="INSUFFICIENT_5M_DATA"
        )

    # --------------------------------------------------------
    # HIGHER TIMEFRAME
    # --------------------------------------------------------

    daily_trend = get_structure_direction(daily)
    h4_trend = get_structure_direction(h4)
    h1_trend = get_structure_direction(h1)

    if daily_trend not in (
        "BULLISH",
        "BEARISH"
    ):

        return no_trade_result(
            daily_trend,
            h4_trend,
            h1_trend,
            "DAILY_NO_CLEAR_TREND"
        )

    if daily_trend == "BULLISH":
        direction = "LONG"
    else:
        direction = "SHORT"

    # --------------------------------------------------------
    # 4H MUST NOT OPPOSE DAILY
    # --------------------------------------------------------

    if direction == "LONG" and h4_trend == "BEARISH":

        return no_trade_result(
            daily_trend,
            h4_trend,
            h1_trend,
            "4H_OPPOSITE_TREND"
        )

    if direction == "SHORT" and h4_trend == "BULLISH":

        return no_trade_result(
            daily_trend,
            h4_trend,
            h1_trend,
            "4H_OPPOSITE_TREND"
        )

    # --------------------------------------------------------
    # 1H DIRECTION
    # --------------------------------------------------------

    h1_direction = get_1h_direction(h1)

    if h1_direction != direction:

        return no_trade_result(
            daily_trend,
            h4_trend,
            h1_trend,
            "1H_NOT_ALIGNED"
        )

    # --------------------------------------------------------
    # 15M RSI FILTER
    # --------------------------------------------------------

    rsi_ok, rsi, rsi_reason = check_15m_filter(
        m15,
        direction
    )

    if not rsi_ok:

        return no_trade_result(
            daily_trend,
            h4_trend,
            h1_trend,
            rsi_reason
        )

    # --------------------------------------------------------
    # STRATEGY 1
    # STOP HUNT ON 5M
    # --------------------------------------------------------

    stop_hunt = detect_stop_hunt(
        m5
    )

    if (
        stop_hunt
        and stop_hunt["side"] != direction
    ):
        stop_hunt = None

    # --------------------------------------------------------
    # STRATEGY 2
    # THREE TAP ON 5M
    # --------------------------------------------------------

    three_tap = detect_three_tap(
        m5
    )

    if (
        three_tap
        and three_tap["side"] != direction
    ):
        three_tap = None

    # --------------------------------------------------------
    # STRATEGY 3
    # LIQUIDITY ZONE ON 5M
    # --------------------------------------------------------

    liquidity_zone = detect_liquidity_zone(
        m5
    )

    if (
        liquidity_zone
        and liquidity_zone["side"] != direction
    ):
        liquidity_zone = None

    # --------------------------------------------------------
    # STRATEGY LIST
    # --------------------------------------------------------

    strategies = []

    if stop_hunt:
        strategies.append("STOP_HUNT")

    if three_tap:
        strategies.append("THREE_TAP")

    if liquidity_zone:
        strategies.append("LIQUIDITY_ZONE")

    # --------------------------------------------------------
    # NO STRATEGY
    # --------------------------------------------------------

    if not strategies:

        return {
            **no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "NO_STRATEGY_MATCH"
            ),

            "rsi": rsi,

            "strategies": [],
            "strategy_matches": [],

            "strategy_details": {
                "STOP_HUNT": False,
                "THREE_TAP": False,
                "LIQUIDITY_ZONE": False,
            },

            "stop_hunt": None,
            "three_tap": None,
            "liquidity_zone": None,
        }

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    volume_ok = volume_spike(
        m5,
        lookback=20,
        multiplier=1.5
    )

    # --------------------------------------------------------
    # CONFIRMATION
    # --------------------------------------------------------

    confirmation_ok = confirmation_candle(
        m5,
        direction
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = calculate_score(
        len(strategies),
        volume_ok,
        confirmation_ok,
        rsi_ok
    )

    quality = quality_from_score(
        score
    )

    # --------------------------------------------------------
    # REQUIRE CONFIRMATION
    # --------------------------------------------------------

    if not confirmation_ok:

        return {
            **no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "NO_5M_CONFIRMATION"
            ),

            "score": score,
            "quality": quality,

            "rsi": rsi,

            "strategies": strategies,
            "strategy_matches": strategies,

            "strategy_details": {
                "STOP_HUNT": bool(stop_hunt),
                "THREE_TAP": bool(three_tap),
                "LIQUIDITY_ZONE": bool(liquidity_zone),
            },

            "stop_hunt": stop_hunt,
            "three_tap": three_tap,
            "liquidity_zone": liquidity_zone,

            "volume_spike": volume_ok,
            "confirmation": False,
        }

    # --------------------------------------------------------
    # REQUIRE HIGH QUALITY
    # --------------------------------------------------------

    if quality != "HIGH":

        return {
            **no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "SIGNAL_QUALITY_TOO_LOW"
            ),

            "score": score,
            "quality": quality,

            "rsi": rsi,

            "strategies": strategies,
            "strategy_matches": strategies,

            "strategy_details": {
                "STOP_HUNT": bool(stop_hunt),
                "THREE_TAP": bool(three_tap),
                "LIQUIDITY_ZONE": bool(liquidity_zone),
            },

            "stop_hunt": stop_hunt,
            "three_tap": three_tap,
            "liquidity_zone": liquidity_zone,

            "volume_spike": volume_ok,
            "confirmation": True,
        }

    # --------------------------------------------------------
    # SELECT STRATEGY DATA
    # --------------------------------------------------------

    signal_data = None

    if stop_hunt:
        signal_data = stop_hunt

    elif liquidity_zone:
        signal_data = liquidity_zone

    elif three_tap:
        signal_data = three_tap

    if signal_data is None:

        return no_trade_result(
            daily_trend,
            h4_trend,
            h1_trend,
            "INVALID_SIGNAL_DATA"
        )

    # --------------------------------------------------------
    # TRADE LEVELS
    # --------------------------------------------------------

    levels = calculate_trade_levels(
        m5,
        direction,
        signal_data
    )

    if levels is None:

        return no_trade_result(
            daily_trend,
            h4_trend,
            h1_trend,
            "INVALID_TRADE_LEVELS"
        )

    # --------------------------------------------------------
    # FINAL SIGNAL
    # --------------------------------------------------------

    return {

        "signal": direction,

        "direction": direction,

        "quality": quality,

        "score": score,

        "reason": "MULTI_TIMEFRAME_LIQUIDITY_SETUP",

        "daily": daily_trend,

        "4h": h4_trend,

        "1h": h1_trend,

        "entry": levels["entry"],

        "sl": levels["sl"],

        "tp1": levels["tp1"],

        "tp2": levels["tp2"],

        "tp3": levels["tp3"],

        "risk": levels["risk"],

        "rr": 3.0,

        "rr_tp1": levels["rr_tp1"],
        "rr_tp2": levels["rr_tp2"],
        "rr_tp3": levels["rr_tp3"],

        "strategies": strategies,

        "strategy_matches": strategies,

        "strategy_details": {
            "STOP_HUNT": bool(stop_hunt),
            "THREE_TAP": bool(three_tap),
            "LIQUIDITY_ZONE": bool(liquidity_zone),
        },

        "stop_hunt": stop_hunt,

        "three_tap": three_tap,

        "liquidity_zone": liquidity_zone,

        "volume_spike": volume_ok,

        "confirmation": confirmation_ok,

        "ema": {
            "trend": ema_trend(h1),
            "ema50": calculate_ema(h1, 50),
            "ema200": calculate_ema(h1, 200),
        },

        "rsi": rsi,
    }
