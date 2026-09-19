# ============================================================
# CryptoBot - Analysis Engine v5
#
# Strategies:
#   1. STOP_HUNT
#   2. THREE_TAP
#   3. LIQUIDITY_ZONE
#
# Timeframes:
#   Daily = context
#   4H    = context
#   1H    = main direction
#   15M   = filter
#   5M    = setup + entry trigger
# ============================================================

from statistics import mean


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ema(values, period):
    if not values or len(values) < period:
        return None

    values = [safe_float(x) for x in values]
    values = [x for x in values if x is not None]

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (price - result) * multiplier + result

    return result


def calculate_rsi(candles, period=14):
    if not candles or len(candles) < period + 1:
        return None

    closes = [
        safe_float(c.get("close"))
        for c in candles
        if safe_float(c.get("close")) is not None
    ]

    if len(closes) < period + 1:
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

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

    return round(rsi, 2)


def volume_spike(candles, lookback=20, multiplier=1.5):
    if not candles or len(candles) < lookback + 1:
        return False

    volumes = [
        safe_float(c.get("volume"))
        for c in candles
        if safe_float(c.get("volume")) is not None
    ]

    if len(volumes) < lookback + 1:
        return False

    current = volumes[-1]
    previous = volumes[-lookback - 1:-1]

    if not previous:
        return False

    average_volume = mean(previous)

    return current > average_volume * multiplier


# ============================================================
# CANDLE HELPERS
# ============================================================

def candle_values(candle):
    return (
        safe_float(candle.get("open")),
        safe_float(candle.get("high")),
        safe_float(candle.get("low")),
        safe_float(candle.get("close")),
    )


def candle_body(candle):
    o, h, l, c = candle_values(candle)

    if None in (o, h, l, c):
        return 0.0

    return abs(c - o)


def is_bullish_candle(candle):
    o, h, l, c = candle_values(candle)

    if None in (o, h, l, c):
        return False

    return c > o


def is_bearish_candle(candle):
    o, h, l, c = candle_values(candle)

    if None in (o, h, l, c):
        return False

    return c < o


def upper_wick(candle):
    o, h, l, c = candle_values(candle)

    if None in (o, h, l, c):
        return 0.0

    return h - max(o, c)


def lower_wick(candle):
    o, h, l, c = candle_values(candle)

    if None in (o, h, l, c):
        return 0.0

    return min(o, c) - l


# ============================================================
# SWINGS
# ============================================================

def find_swing_highs(candles, strength=2):
    if len(candles) < strength * 2 + 1:
        return []

    swings = []

    for i in range(strength, len(candles) - strength):

        current_high = safe_float(candles[i].get("high"))

        if current_high is None:
            continue

        valid = True

        for j in range(1, strength + 1):

            left = safe_float(candles[i - j].get("high"))
            right = safe_float(candles[i + j].get("high"))

            if left is None or right is None:
                valid = False
                break

            if current_high <= left or current_high <= right:
                valid = False
                break

        if valid:
            swings.append({
                "index": i,
                "price": current_high
            })

    return swings


def find_swing_lows(candles, strength=2):
    if len(candles) < strength * 2 + 1:
        return []

    swings = []

    for i in range(strength, len(candles) - strength):

        current_low = safe_float(candles[i].get("low"))

        if current_low is None:
            continue

        valid = True

        for j in range(1, strength + 1):

            left = safe_float(candles[i - j].get("low"))
            right = safe_float(candles[i + j].get("low"))

            if left is None or right is None:
                valid = False
                break

            if current_low >= left or current_low >= right:
                valid = False
                break

        if valid:
            swings.append({
                "index": i,
                "price": current_low
            })

    return swings


# ============================================================
# MARKET STRUCTURE
# ============================================================

def market_structure(candles):

    if not candles or len(candles) < 20:
        return "RANGE"

    highs = find_swing_highs(candles, 2)
    lows = find_swing_lows(candles, 2)

    if len(highs) < 2 or len(lows) < 2:
        return "RANGE"

    h1 = highs[-2]["price"]
    h2 = highs[-1]["price"]

    l1 = lows[-2]["price"]
    l2 = lows[-1]["price"]

    if h2 > h1 and l2 > l1:
        return "BULLISH"

    if h2 < h1 and l2 < l1:
        return "BEARISH"

    return "RANGE"


def ema_direction(candles):

    if not candles or len(candles) < 200:
        return "RANGE"

    closes = [
        safe_float(c.get("close"))
        for c in candles
        if safe_float(c.get("close")) is not None
    ]

    if len(closes) < 200:
        return "RANGE"

    e50 = ema(closes, 50)
    e200 = ema(closes, 200)

    if e50 is None or e200 is None:
        return "RANGE"

    price = closes[-1]

    if price > e50 > e200:
        return "BULLISH"

    if price < e50 < e200:
        return "BEARISH"

    return "RANGE"


# ============================================================
# 5M CONFIRMATION
# ============================================================

def confirmation_candle(candles, direction):

    if not candles or len(candles) < 3:
        return False

    previous = candles[-2]
    current = candles[-1]

    previous_body = candle_body(previous)
    current_body = candle_body(current)

    if previous_body <= 0 or current_body <= 0:
        return False

    po, ph, pl, pc = candle_values(previous)
    co, ch, cl, cc = candle_values(current)

    if None in (po, ph, pl, pc, co, ch, cl, cc):
        return False

    # Long confirmation:
    # current candle bullish + stronger body + closes above previous high
    if direction == "LONG":
        return (
            cc > co
            and current_body >= previous_body * 0.8
            and cc > ph
        )

    # Short confirmation
    if direction == "SHORT":
        return (
            cc < co
            and current_body >= previous_body * 0.8
            and cc < pl
        )

    return False


# ============================================================
# STRATEGY 1 — STOP HUNT
# ============================================================

def detect_stop_hunt(candles, lookback=20):

    if not candles or len(candles) < lookback + 2:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INSUFFICIENT_DATA"
        }

    current = candles[-1]

    previous_candles = candles[-lookback - 1:-1]

    highs = [
        safe_float(c.get("high"))
        for c in previous_candles
        if safe_float(c.get("high")) is not None
    ]

    lows = [
        safe_float(c.get("low"))
        for c in previous_candles
        if safe_float(c.get("low")) is not None
    ]

    if not highs or not lows:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "NO_LEVEL"
        }

    previous_high = max(highs)
    previous_low = min(lows)

    o, h, l, c = candle_values(current)

    if None in (o, h, l, c):
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INVALID_CANDLE"
        }

    body = candle_body(current)

    if body <= 0:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "ZERO_BODY"
        }

    upper = upper_wick(current)
    lower = lower_wick(current)

    # SHORT:
    # price takes previous high and closes back below it
    if h > previous_high and c < previous_high:

        if upper >= body * 0.7:

            return {
                "matched": True,
                "direction": "SHORT",
                "level": previous_high,
                "reason": "HIGH_SWEEP_RECLAIM"
            }

    # LONG:
    # price takes previous low and closes back above it
    if l < previous_low and c > previous_low:

        if lower >= body * 0.7:

            return {
                "matched": True,
                "direction": "LONG",
                "level": previous_low,
                "reason": "LOW_SWEEP_RECLAIM"
            }

    return {
        "matched": False,
        "direction": None,
        "level": None,
        "reason": "NO_STOP_HUNT"
    }


# ============================================================
# STRATEGY 2 — THREE TAP
# ============================================================

def detect_three_tap(candles, tolerance=0.005):

    if not candles or len(candles) < 30:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INSUFFICIENT_DATA"
        }

    recent = candles[-80:]

    highs = find_swing_highs(recent, 2)
    lows = find_swing_lows(recent, 2)

    current = candles[-1]

    o, h, l, c = candle_values(current)

    if None in (o, h, l, c):
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INVALID_CANDLE"
        }

    # -------------------------
    # Three highs = SHORT
    # -------------------------

    if len(highs) >= 3:

        taps = highs[-3:]

        levels = [x["price"] for x in taps]

        average_level = mean(levels)

        if average_level > 0:

            deviation = max(
                abs(x - average_level) / average_level
                for x in levels
            )

            if deviation <= tolerance:

                # Current price must interact with the level
                # and reject it.
                if h >= average_level * 0.999 and c < average_level:

                    return {
                        "matched": True,
                        "direction": "SHORT",
                        "level": average_level,
                        "reason": "THREE_HIGH_TAPS"
                    }

    # -------------------------
    # Three lows = LONG
    # -------------------------

    if len(lows) >= 3:

        taps = lows[-3:]

        levels = [x["price"] for x in taps]

        average_level = mean(levels)

        if average_level > 0:

            deviation = max(
                abs(x - average_level) / average_level
                for x in levels
            )

            if deviation <= tolerance:

                if l <= average_level * 1.001 and c > average_level:

                    return {
                        "matched": True,
                        "direction": "LONG",
                        "level": average_level,
                        "reason": "THREE_LOW_TAPS"
                    }

    return {
        "matched": False,
        "direction": None,
        "level": None,
        "reason": "NO_THREE_TAP"
    }


# ============================================================
# STRATEGY 3 — LIQUIDITY ZONE
# ============================================================

def detect_liquidity_zone(candles, tolerance=0.006):

    if not candles or len(candles) < 30:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INSUFFICIENT_DATA"
        }

    recent = candles[-80:]

    highs = find_swing_highs(recent, 2)
    lows = find_swing_lows(recent, 2)

    current = candles[-1]

    o, h, l, c = candle_values(current)

    if None in (o, h, l, c):
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INVALID_CANDLE"
        }

    # -------------------------
    # High liquidity zone
    # -------------------------

    if len(highs) >= 3:

        candidate_highs = [x["price"] for x in highs[-6:]]

        zone = mean(candidate_highs)

        if zone > 0:

            nearby = [
                x for x in candidate_highs
                if abs(x - zone) / zone <= tolerance
            ]

            if len(nearby) >= 3:

                # Sweep + rejection
                if h > zone and c < zone:

                    return {
                        "matched": True,
                        "direction": "SHORT",
                        "level": zone,
                        "reason": "HIGH_LIQUIDITY_SWEEP"
                    }

    # -------------------------
    # Low liquidity zone
    # -------------------------

    if len(lows) >= 3:

        candidate_lows = [x["price"] for x in lows[-6:]]

        zone = mean(candidate_lows)

        if zone > 0:

            nearby = [
                x for x in candidate_lows
                if abs(x - zone) / zone <= tolerance
            ]

            if len(nearby) >= 3:

                if l < zone and c > zone:

                    return {
                        "matched": True,
                        "direction": "LONG",
                        "level": zone,
                        "reason": "LOW_LIQUIDITY_SWEEP"
                    }

    return {
        "matched": False,
        "direction": None,
        "level": None,
        "reason": "NO_LIQUIDITY_ZONE"
    }


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_trade_levels(candles, direction, strategy_level=None):

    if not candles or len(candles) < 10:
        return None

    entry = safe_float(candles[-1].get("close"))

    if entry is None or entry <= 0:
        return None

    recent = candles[-20:]

    highs = [
        safe_float(c.get("high"))
        for c in recent
        if safe_float(c.get("high")) is not None
    ]

    lows = [
        safe_float(c.get("low"))
        for c in recent
        if safe_float(c.get("low")) is not None
    ]

    if not highs or not lows:
        return None

    # -------------------------
    # LONG
    # -------------------------

    if direction == "LONG":

        candidates = [
            low for low in lows
            if low < entry
        ]

        if strategy_level is not None and strategy_level < entry:
            candidates.append(strategy_level)

        if not candidates:
            return None

        support = max(candidates)

        risk = entry - support

        if risk <= 0:
            return None

        sl = support - (risk * 0.10)

        actual_risk = entry - sl

        tp1 = entry + actual_risk * 1.5
        tp2 = entry + actual_risk * 2.5
        tp3 = entry + actual_risk * 3.5

    # -------------------------
    # SHORT
    # -------------------------

    elif direction == "SHORT":

        candidates = [
            high for high in highs
            if high > entry
        ]

        if strategy_level is not None and strategy_level > entry:
            candidates.append(strategy_level)

        if not candidates:
            return None

        resistance = min(candidates)

        risk = resistance - entry

        if risk <= 0:
            return None

        sl = resistance + (risk * 0.10)

        actual_risk = sl - entry

        tp1 = entry - actual_risk * 1.5
        tp2 = entry - actual_risk * 2.5
        tp3 = entry - actual_risk * 3.5

    else:
        return None

    return {
        "entry": round(entry, 8),
        "sl": round(sl, 8),
        "tp1": round(tp1, 8),
        "tp2": round(tp2, 8),
        "tp3": round(tp3, 8),
        "risk": round(actual_risk, 8),
        "rr": "1:1.5 / 1:2.5 / 1:3.5"
    }


# ============================================================
# NO TRADE
# ============================================================

def no_trade(
    reason,
    daily="RANGE",
    h4="RANGE",
    h1="RANGE",
    rsi_15m=None,
    strategy_details=None,
    score=0
):

    if strategy_details is None:

        strategy_details = {
            "STOP_HUNT": {
                "matched": False,
                "direction": None,
                "reason": "NOT_CHECKED"
            },
            "THREE_TAP": {
                "matched": False,
                "direction": None,
                "reason": "NOT_CHECKED"
            },
            "LIQUIDITY_ZONE": {
                "matched": False,
                "direction": None,
                "reason": "NOT_CHECKED"
            }
        }

    return {
        "signal": "NO_TRADE",
        "direction": None,
        "quality": "LOW",
        "score": score,

        "daily": daily,
        "4h": h4,
        "1h": h1,

        "rsi_15m": rsi_15m,

        "volume_spike": False,
        "confirmation": False,

        "strategies": [],
        "strategy": None,
        "strategy_matches": [],

        "strategy_details": strategy_details,

        "stop_hunt": False,
        "three_tap": False,
        "liquidity_zone": False,

        "entry": None,
        "sl": None,
        "tp1": None,
        "tp2": None,
        "tp3": None,
        "risk": None,
        "rr": None,

        "reason": reason
    }


# ============================================================
# MAIN SIGNAL ENGINE
# ============================================================

def generate_signal(daily, h4, h1, m15, m5):

    if not all([daily, h4, h1, m15, m5]):

        return no_trade(
            "INSUFFICIENT_MARKET_DATA"
        )

    # ========================================================
    # MARKET DIRECTION
    # ========================================================

    daily_direction = market_structure(daily)
    h4_direction = market_structure(h4)
    h1_direction = market_structure(h1)

    # 1H remains the main direction.
    if h1_direction not in ("BULLISH", "BEARISH"):

        return no_trade(
            "1H_RANGE",
            daily_direction,
            h4_direction,
            h1_direction
        )

    direction = (
        "LONG"
        if h1_direction == "BULLISH"
        else "SHORT"
    )

    # ========================================================
    # CONTEXT
    # ========================================================

    daily_ema = ema_direction(daily)
    h4_ema = ema_direction(h4)
    h1_ema = ema_direction(h1)

    rsi_15m = calculate_rsi(m15)

    # RSI is a filter.
    # Missing RSI must NOT receive a bonus.
    rsi_passed = False

    if rsi_15m is not None:

        if direction == "LONG":
            rsi_passed = rsi_15m < 75

        elif direction == "SHORT":
            rsi_passed = rsi_15m > 25

    # ========================================================
    # STRATEGIES
    # ========================================================

    stop_hunt = detect_stop_hunt(m5)

    three_tap = detect_three_tap(m5)

    liquidity_zone = detect_liquidity_zone(m5)

    strategy_details = {
        "STOP_HUNT": stop_hunt,
        "THREE_TAP": three_tap,
        "LIQUIDITY_ZONE": liquidity_zone
    }

    matching_strategies = []

    if (
        stop_hunt["matched"]
        and stop_hunt["direction"] == direction
    ):
        matching_strategies.append("STOP_HUNT")

    if (
        three_tap["matched"]
        and three_tap["direction"] == direction
    ):
        matching_strategies.append("THREE_TAP")

    if (
        liquidity_zone["matched"]
        and liquidity_zone["direction"] == direction
    ):
        matching_strategies.append("LIQUIDITY_ZONE")

    # No strategy = no trade
    if not matching_strategies:

        return no_trade(
            "NO_MAIN_SETUP",
            daily_direction,
            h4_direction,
            h1_direction,
            rsi_15m,
            strategy_details
        )

    # ========================================================
    # 5M FILTERS
    # ========================================================

    volume_is_spike = volume_spike(m5)

    confirmation = confirmation_candle(
        m5,
        direction
    )

    # ========================================================
    # SCORE
    # ========================================================

    score = 0

    # Main strategy
    score += 5

    # Multiple strategies agree
    if len(matching_strategies) >= 2:
        score += 1

    # 1H direction
    score += 2

    # Daily context
    if (
        direction == "LONG"
        and daily_direction == "BULLISH"
    ) or (
        direction == "SHORT"
        and daily_direction == "BEARISH"
    ):
        score += 1

    # 4H context
    if (
        direction == "LONG"
        and h4_direction == "BULLISH"
    ) or (
        direction == "SHORT"
        and h4_direction == "BEARISH"
    ):
        score += 1

    # RSI
    if rsi_passed:
        score += 1

    # Volume
    if volume_is_spike:
        score += 1

    # Confirmation
    if confirmation:
        score += 2

    # ========================================================
    # QUALITY
    # ========================================================

    if score >= 10:
        quality = "HIGH"

    elif score >= 8:
        quality = "MEDIUM"

    else:
        quality = "LOW"

    # ========================================================
    # SELECT STRATEGY
    # ========================================================

    priority = [
        "STOP_HUNT",
        "LIQUIDITY_ZONE",
        "THREE_TAP"
    ]

    selected_strategy = matching_strategies[0]

    strategy_level = None

    for strategy_name in priority:

        if strategy_name in matching_strategies:

            selected_strategy = strategy_name

            strategy_level = strategy_details[
                strategy_name
            ].get("level")

            break

    # ========================================================
    # TRADE LEVELS
    # ========================================================

    levels = calculate_trade_levels(
        m5,
        direction,
        strategy_level
    )

    if levels is None:

        return no_trade(
            "LEVEL_CALCULATION_FAILED",
            daily_direction,
            h4_direction,
            h1_direction,
            rsi_15m,
            strategy_details,
            score
        )

    # ========================================================
    # CONFIRMATION REQUIRED
    # ========================================================

    if not confirmation:

        return no_trade(
            "5M_CONFIRMATION_MISSING",
            daily_direction,
            h4_direction,
            h1_direction,
            rsi_15m,
            strategy_details,
            score
        )

    # ========================================================
    # HIGH QUALITY REQUIRED
    # ========================================================

    if score < 10:

        return no_trade(
            "SIGNAL_QUALITY_TOO_LOW",
            daily_direction,
            h4_direction,
            h1_direction,
            rsi_15m,
            strategy_details,
            score
        )

    # ========================================================
    # FINAL HIGH SIGNAL
    # ========================================================

    return {
        "signal": direction,
        "direction": direction,

        "quality": "HIGH",
        "score": score,

        "daily": daily_direction,
        "4h": h4_direction,
        "1h": h1_direction,

        "daily_ema": daily_ema,
        "4h_ema": h4_ema,
        "1h_ema": h1_ema,

        "rsi_15m": rsi_15m,
        "rsi_passed": rsi_passed,

        "volume_spike": volume_is_spike,
        "confirmation": confirmation,

        "strategies": matching_strategies,
        "strategy_matches": matching_strategies,

        "strategy": selected_strategy,

        "strategy_details": strategy_details,

        "stop_hunt": (
            "STOP_HUNT"
            in matching_strategies
        ),

        "three_tap": (
            "THREE_TAP"
            in matching_strategies
        ),

        "liquidity_zone": (
            "LIQUIDITY_ZONE"
            in matching_strategies
        ),

        "entry": levels["entry"],
        "sl": levels["sl"],
        "tp1": levels["tp1"],
        "tp2": levels["tp2"],
        "tp3": levels["tp3"],

        "risk": levels["risk"],
        "rr": levels["rr"],

        "reason": (
            "1H_DIRECTION + "
            + selected_strategy
            + " + "
            + "5M_CONFIRMATION"
        )
    }


# ============================================================
# COMPATIBILITY HELPER
# ============================================================

def direction_to_trend(direction):

    if direction in ("LONG", "BULLISH"):
        return "BULLISH"

    if direction in ("SHORT", "BEARISH"):
        return "BEARISH"

    return "RANGE"
