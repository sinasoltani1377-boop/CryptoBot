import math


# =========================================================
# CryptoBot - Professional Analysis Engine v7
# Strategies:
# 1. STOP_HUNT
# 2. THREE_TAP
# 3. LIQUIDITY_ZONE
#
# EMA / RSI / Volume = FILTERS
# =========================================================


# =========================================================
# BASIC HELPERS
# =========================================================

def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_candle(candle):
    if not isinstance(candle, dict):
        return None

    o = safe_float(candle.get("open"))
    h = safe_float(candle.get("high"))
    l = safe_float(candle.get("low"))
    c = safe_float(candle.get("close"))
    v = safe_float(candle.get("volume"), 0.0)

    if None in (o, h, l, c):
        return None

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
        "time": candle.get(
            "time",
            candle.get("timestamp")
        ),
    }


def clean_candles(candles):
    result = []

    if not isinstance(candles, list):
        return result

    for candle in candles:
        normalized = normalize_candle(candle)

        if normalized is not None:
            result.append(normalized)

    return result


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):
    if not values or len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(values[:period]) / period

    for price in values[period:]:
        ema = (
            (price - ema) * multiplier
        ) + ema

    return ema


def ema_trend(candles):
    candles = clean_candles(candles)

    if len(candles) < 200:
        return "RANGE"

    closes = [
        c["close"]
        for c in candles
    ]

    ema50 = calculate_ema(
        closes,
        50
    )

    ema200 = calculate_ema(
        closes,
        200
    )

    last = closes[-1]

    if ema50 is None or ema200 is None:
        return "RANGE"

    if (
        last > ema50
        and ema50 > ema200
    ):
        return "BULLISH"

    if (
        last < ema50
        and ema50 < ema200
    ):
        return "BEARISH"

    return "RANGE"


# =========================================================
# RSI
# =========================================================

def calculate_rsi(candles, period=14):
    candles = clean_candles(candles)

    if len(candles) < period + 1:
        return None

    closes = [
        c["close"]
        for c in candles
    ]

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

    avg_gain = sum(
        gains[:period]
    ) / period

    avg_loss = sum(
        losses[:period]
    ) / period

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

    return 100 - (
        100 / (1 + rs)
    )


# =========================================================
# SWINGS
# =========================================================

def find_swing_highs(candles, strength=2):
    candles = clean_candles(candles)

    highs = []

    for i in range(
        strength,
        len(candles) - strength
    ):

        current = candles[i]["high"]

        left = [
            candles[j]["high"]
            for j in range(
                i - strength,
                i
            )
        ]

        right = [
            candles[j]["high"]
            for j in range(
                i + 1,
                i + strength + 1
            )
        ]

        if (
            current > max(left)
            and current > max(right)
        ):
            highs.append({
                "index": i,
                "price": current,
            })

    return highs


def find_swing_lows(candles, strength=2):
    candles = clean_candles(candles)

    lows = []

    for i in range(
        strength,
        len(candles) - strength
    ):

        current = candles[i]["low"]

        left = [
            candles[j]["low"]
            for j in range(
                i - strength,
                i
            )
        ]

        right = [
            candles[j]["low"]
            for j in range(
                i + 1,
                i + strength + 1
            )
        ]

        if (
            current < min(left)
            and current < min(right)
        ):
            lows.append({
                "index": i,
                "price": current,
            })

    return lows


# =========================================================
# MARKET STRUCTURE
# =========================================================

def get_structure(candles):
    candles = clean_candles(candles)

    highs = find_swing_highs(candles)
    lows = find_swing_lows(candles)

    if len(highs) < 2 or len(lows) < 2:
        return "RANGE"

    previous_high = highs[-2]["price"]
    latest_high = highs[-1]["price"]

    previous_low = lows[-2]["price"]
    latest_low = lows[-1]["price"]

    if (
        latest_high > previous_high
        and latest_low > previous_low
    ):
        return "BULLISH"

    if (
        latest_high < previous_high
        and latest_low < previous_low
    ):
        return "BEARISH"

    return "RANGE"


# =========================================================
# 1H DIRECTION
# =========================================================

def get_1h_direction(candles):
    structure = get_structure(candles)
    ema = ema_trend(candles)

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


# =========================================================
# CONFIRMATION CANDLE
# =========================================================

def confirmation_candle(candles, direction):
    candles = clean_candles(candles)

    if len(candles) < 3:
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

    if previous_body == 0:
        return False

    if current_body < previous_body:
        return False

    if direction == "LONG":

        return (
            current["close"]
            > current["open"]
            and current["close"]
            > previous["high"]
        )

    if direction == "SHORT":

        return (
            current["close"]
            < current["open"]
            and current["close"]
            < previous["low"]
        )

    return False


# =========================================================
# VOLUME FILTER
# =========================================================

def volume_spike(candles, lookback=20):
    candles = clean_candles(candles)

    if len(candles) < lookback + 1:
        return False

    current_volume = candles[-1]["volume"]

    previous_volumes = [
        c["volume"]
        for c in candles[
            -(lookback + 1):-1
        ]
    ]

    if not previous_volumes:
        return False

    average_volume = (
        sum(previous_volumes)
        / len(previous_volumes)
    )

    if average_volume <= 0:
        return False

    return (
        current_volume
        >= average_volume * 1.5
    )


# =========================================================
# STRATEGY 1
# STOP HUNT
# =========================================================

def detect_stop_hunt(
    candles,
    lookback=20,
    wick_ratio=2.0
):
    candles = clean_candles(candles)

    if len(candles) < lookback + 2:
        return None

    current = candles[-1]

    body = abs(
        current["close"]
        - current["open"]
    )

    if body <= 0:
        body = (
            current["high"]
            - current["low"]
        ) * 0.1

    recent = candles[
        -(lookback + 1):-1
    ]

    previous_high = max(
        c["high"]
        for c in recent
    )

    previous_low = min(
        c["low"]
        for c in recent
    )

    upper_wick = (
        current["high"]
        - max(
            current["open"],
            current["close"]
        )
    )

    lower_wick = (
        min(
            current["open"],
            current["close"]
        )
        - current["low"]
    )

    # Bearish stop hunt:
    # price sweeps previous high
    # then closes back below it
    if (
        current["high"] > previous_high
        and current["close"] < previous_high
        and upper_wick >= body * wick_ratio
    ):
        return {
            "direction": "SHORT",
            "level": previous_high,
            "sweep": current["high"],
            "reason": (
                "High swept and price "
                "closed back below liquidity."
            ),
        }

    # Bullish stop hunt:
    # price sweeps previous low
    # then closes back above it
    if (
        current["low"] < previous_low
        and current["close"] > previous_low
        and lower_wick >= body * wick_ratio
    ):
        return {
            "direction": "LONG",
            "level": previous_low,
            "sweep": current["low"],
            "reason": (
                "Low swept and price "
                "closed back above liquidity."
            ),
        }

    return None


# =========================================================
# STRATEGY 2
# THREE TAP
# =========================================================

def detect_three_tap(
    candles,
    tolerance=0.003
):
    candles = clean_candles(candles)

    if len(candles) < 30:
        return None

    highs = find_swing_highs(candles)
    lows = find_swing_lows(candles)

    # Three similar highs
    if len(highs) >= 3:

        taps = highs[-3:]

        average = sum(
            x["price"]
            for x in taps
        ) / 3

        valid = all(
            abs(x["price"] - average)
            / average
            <= tolerance
            for x in taps
        )

        if valid:

            last = candles[-1]

            if last["close"] < average:

                return {
                    "direction": "SHORT",
                    "level": average,
                    "reason": (
                        "Three-tap resistance "
                        "with rejection."
                    ),
                }

    # Three similar lows
    if len(lows) >= 3:

        taps = lows[-3:]

        average = sum(
            x["price"]
            for x in taps
        ) / 3

        valid = all(
            abs(x["price"] - average)
            / average
            <= tolerance
            for x in taps
        )

        if valid:

            last = candles[-1]

            if last["close"] > average:

                return {
                    "direction": "LONG",
                    "level": average,
                    "reason": (
                        "Three-tap support "
                        "with rejection."
                    ),
                }

    return None


# =========================================================
# STRATEGY 3
# LIQUIDITY ZONE
# =========================================================

def detect_liquidity_zone(
    candles,
    tolerance=0.003
):
    candles = clean_candles(candles)

    if len(candles) < 30:
        return None

    highs = find_swing_highs(candles)
    lows = find_swing_lows(candles)

    current = candles[-1]

    # Resistance liquidity zone
    if len(highs) >= 2:

        h1 = highs[-2]["price"]
        h2 = highs[-1]["price"]

        average_high = (
            h1 + h2
        ) / 2

        close_to_zone = (
            abs(h1 - h2)
            / average_high
            <= tolerance
        )

        if close_to_zone:

            if (
                current["high"]
                > average_high
                and current["close"]
                < average_high
            ):

                return {
                    "direction": "SHORT",
                    "level": average_high,
                    "sweep": current["high"],
                    "reason": (
                        "Resistance liquidity zone "
                        "was swept and rejected."
                    ),
                }

    # Support liquidity zone
    if len(lows) >= 2:

        l1 = lows[-2]["price"]
        l2 = lows[-1]["price"]

        average_low = (
            l1 + l2
        ) / 2

        close_to_zone = (
            abs(l1 - l2)
            / average_low
            <= tolerance
        )

        if close_to_zone:

            if (
                current["low"]
                < average_low
                and current["close"]
                > average_low
            ):

                return {
                    "direction": "LONG",
                    "level": average_low,
                    "sweep": current["low"],
                    "reason": (
                        "Support liquidity zone "
                        "was swept and reclaimed."
                    ),
                }

    return None


# =========================================================
# TRADE LEVELS
# =========================================================

def calculate_trade_levels(
    candles,
    direction,
    strategy_results
):
    candles = clean_candles(candles)

    if not candles:
        return None

    entry = candles[-1]["close"]

    levels = []

    for result in strategy_results:

        if not isinstance(result, dict):
            continue

        if result.get("direction") != direction:
            continue

        level = safe_float(
            result.get("level")
        )

        sweep = safe_float(
            result.get("sweep")
        )

        if level is not None:
            levels.append(level)

        if sweep is not None:
            levels.append(sweep)

    if direction == "LONG":

        relevant = [
            x for x in levels
            if x < entry
        ]

        if relevant:
            base = min(relevant)
        else:
            base = min(
                c["low"]
                for c in candles[-10:]
            )

        risk = entry - base

        if risk <= 0:
            return None

        sl = base - (
            risk * 0.10
        )

        risk = entry - sl

        tp1 = entry + risk
        tp2 = entry + risk * 2
        tp3 = entry + risk * 3

    elif direction == "SHORT":

        relevant = [
            x for x in levels
            if x > entry
        ]

        if relevant:
            base = max(relevant)
        else:
            base = max(
                c["high"]
                for c in candles[-10:]
            )

        risk = base - entry

        if risk <= 0:
            return None

        sl = base + (
            risk * 0.10
        )

        risk = sl - entry

        tp1 = entry - risk
        tp2 = entry - risk * 2
        tp3 = entry - risk * 3

    else:
        return None

    if risk <= 0:
        return None

    return {
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk": risk,
        "rr": "1:1 / 1:2 / 1:3",
    }


# =========================================================
# NO TRADE
# =========================================================

def no_trade_result(
    daily="UNKNOWN",
    h4="UNKNOWN",
    h1="UNKNOWN",
    reason="NO_SETUP"
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

        "rsi_15m": None,
        "volume_spike": False,
        "confirmation": False,
    }


# =========================================================
# MAIN SIGNAL ENGINE
# =========================================================

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
    m15 = clean_candles(m15)
    m5 = clean_candles(m5)

    if (
        not daily
        or not h4
        or not h1
        or not m15
        or not m5
    ):
        return no_trade_result(
            reason="MISSING_TIMEFRAME_DATA"
        )

    # -----------------------------------------------------
    # DAILY
    # -----------------------------------------------------

    daily_trend = get_structure(daily)

    # -----------------------------------------------------
    # 4H
    # -----------------------------------------------------

    h4_trend = get_structure(h4)

    # Daily must have a direction
    if daily_trend not in (
        "BULLISH",
        "BEARISH"
    ):

        return no_trade_result(
            daily_trend,
            h4_trend,
            get_structure(h1),
            "DAILY_RANGE"
        )

    # 4H cannot oppose Daily
    if (
        h4_trend != daily_trend
        and h4_trend != "RANGE"
    ):

        return no_trade_result(
            daily_trend,
            h4_trend,
            get_structure(h1),
            "4H_OPPOSITE_TREND"
        )

    # -----------------------------------------------------
    # 1H
    # -----------------------------------------------------

    h1_structure = get_structure(h1)
    h1_ema = ema_trend(h1)

    if (
        daily_trend == "BULLISH"
        and h1_structure == "BULLISH"
        and h1_ema == "BULLISH"
    ):
        direction = "LONG"

    elif (
        daily_trend == "BEARISH"
        and h1_structure == "BEARISH"
        and h1_ema == "BEARISH"
    ):
        direction = "SHORT"

    else:

        return no_trade_result(
            daily_trend,
            h4_trend,
            h1_structure,
            "1H_NOT_ALIGNED"
        )

    # -----------------------------------------------------
    # 15M RSI FILTER
    # -----------------------------------------------------

    rsi_15m = calculate_rsi(
        m15
    )

    if rsi_15m is None:

        return no_trade_result(
            daily_trend,
            h4_trend,
            h1_structure,
            "RSI_UNAVAILABLE"
        )

    if (
        direction == "LONG"
        and rsi_15m >= 70
    ):

        result = no_trade_result(
            daily_trend,
            h4_trend,
            h1_structure,
            "15M_RSI_OVERBOUGHT"
        )

        result["rsi_15m"] = round(
            rsi_15m,
            2
        )

        return result

    if (
        direction == "SHORT"
        and rsi_15m <= 30
    ):

        result = no_trade_result(
            daily_trend,
            h4_trend,
            h1_structure,
            "15M_RSI_OVERSOLD"
        )

        result["rsi_15m"] = round(
            rsi_15m,
            2
        )

        return result

    # -----------------------------------------------------
    # 5M STRATEGIES
    # -----------------------------------------------------

    stop_hunt = detect_stop_hunt(
        m5
    )

    three_tap = detect_three_tap(
        m5
    )

    liquidity_zone = detect_liquidity_zone(
        m5
    )

    strategy_results = []

    strategy_matches = []

    strategy_details = {
        "STOP_HUNT": False,
        "THREE_TAP": False,
        "LIQUIDITY_ZONE": False,
    }

    if (
        stop_hunt
        and stop_hunt.get("direction")
        == direction
    ):
        strategy_results.append(
            stop_hunt
        )

        strategy_matches.append(
            "STOP_HUNT"
        )

        strategy_details[
            "STOP_HUNT"
        ] = True

    if (
        three_tap
        and three_tap.get("direction")
        == direction
    ):
        strategy_results.append(
            three_tap
        )

        strategy_matches.append(
            "THREE_TAP"
        )

        strategy_details[
            "THREE_TAP"
        ] = True

    if (
        liquidity_zone
        and liquidity_zone.get("direction")
        == direction
    ):
        strategy_results.append(
            liquidity_zone
        )

        strategy_matches.append(
            "LIQUIDITY_ZONE"
        )

        strategy_details[
            "LIQUIDITY_ZONE"
        ] = True

    if not strategy_results:

        result = no_trade_result(
            daily_trend,
            h4_trend,
            h1_structure,
            "NO_STRATEGY_SETUP"
        )

        result["rsi_15m"] = round(
            rsi_15m,
            2
        )

        result[
            "stop_hunt"
        ] = stop_hunt

        result[
            "three_tap"
        ] = three_tap

        result[
            "liquidity_zone"
        ] = liquidity_zone

        result[
            "strategy_details"
        ] = strategy_details

        return result

    # -----------------------------------------------------
    # 5M CONFIRMATION
    # -----------------------------------------------------

    confirmed = confirmation_candle(
        m5,
        direction
    )

    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

    volume_ok = volume_spike(
        m5
    )

    # -----------------------------------------------------
    # SCORE
    # -----------------------------------------------------

    score = 4

    if len(strategy_results) >= 2:
        score += 2

    if volume_ok:
        score += 1

    if confirmed:
        score += 2

    score += 1

    # -----------------------------------------------------
    # QUALITY
    # -----------------------------------------------------

    if score >= 8:
        quality = "HIGH"

    elif score >= 6:
        quality = "MEDIUM"

    else:
        quality = "LOW"

    # HIGH quality requires confirmation
    if not confirmed:

        result = no_trade_result(
            daily_trend,
            h4_trend,
            h1_structure,
            "5M_CONFIRMATION_MISSING"
        )

        result["score"] = score
        result["quality"] = quality
        result["direction"] = direction

        result["rsi_15m"] = round(
            rsi_15m,
            2
        )

        result["volume_spike"] = volume_ok
        result["confirmation"] = False

        result[
            "strategies"
        ] = strategy_matches

        result[
            "strategy_matches"
        ] = strategy_matches

        result[
            "strategy_details"
        ] = strategy_details

        result[
            "stop_hunt"
        ] = stop_hunt

        result[
            "three_tap"
        ] = three_tap

        result[
            "liquidity_zone"
        ] = liquidity_zone

        return result

    # -----------------------------------------------------
    # TRADE LEVELS
    # -----------------------------------------------------

    levels = calculate_trade_levels(
        m5,
        direction,
        strategy_results
    )

    if levels is None:

        result = no_trade_result(
            daily_trend,
            h4_trend,
            h1_structure,
            "INVALID_TRADE_LEVELS"
        )

        result["score"] = score
        result["quality"] = quality
        result["direction"] = direction

        result["rsi_15m"] = round(
            rsi_15m,
            2
        )

        result["volume_spike"] = volume_ok
        result["confirmation"] = confirmed

        result[
            "strategies"
        ] = strategy_matches

        result[
            "strategy_matches"
        ] = strategy_matches

        result[
            "strategy_details"
        ] = strategy_details

        return result

    # -----------------------------------------------------
    # FINAL SIGNAL
    # -----------------------------------------------------

    return {
        "signal": direction,
        "direction": direction,

        "quality": quality,
        "score": score,

        "reason": "VALID_SETUP",

        "daily": daily_trend,
        "4h": h4_trend,
        "1h": h1_structure,

        "entry": levels["entry"],
        "sl": levels["sl"],
        "tp1": levels["tp1"],
        "tp2": levels["tp2"],
        "tp3": levels["tp3"],
        "risk": levels["risk"],
        "rr": levels["rr"],

        "strategies": strategy_matches,
        "strategy_matches": strategy_matches,

        "strategy_details": strategy_details,

        "stop_hunt": stop_hunt,
        "three_tap": three_tap,
        "liquidity_zone": liquidity_zone,

        "rsi_15m": round(
            rsi_15m,
            2
        ),

        "volume_spike": volume_ok,
        "confirmation": confirmed,
    }


# =========================================================
# DIRECTION HELPER
# =========================================================

def direction_to_trend(direction):

    if direction == "LONG":
        return "BULLISH"

    if direction == "SHORT":
        return "BEARISH"

    return "RANGE"
