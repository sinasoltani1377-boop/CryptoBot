# ============================================================
# CryptoBot - Analysis Engine v6
#
# 1H  = Main Direction
# 15M  = Filter
# 5M  = Entry Trigger
#
# Strategies:
#   STOP_HUNT
#   THREE_TAP
#   LIQUIDITY_ZONE
#
# Only HIGH signals are returned as active trades.
# ============================================================

from statistics import mean


# ============================================================
# HELPERS
# ============================================================

def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def ema(values, period):
    if not values or len(values) < period:
        return None

    values = [
        safe_float(x)
        for x in values
        if safe_float(x) is not None
    ]

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period

    for price in values[period:]:
        result = ((price - result) * multiplier) + result

    return result


# ============================================================
# RSI
# ============================================================

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

    for i in range(period, len(gains)):
        avg_gain = (
            (avg_gain * (period - 1)) + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return round(
        100 - (100 / (1 + rs)),
        2
    )


# ============================================================
# VOLUME
# ============================================================

def volume_spike(candles, lookback=20, multiplier=1.4):
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

    return current > mean(previous) * multiplier


# ============================================================
# SWINGS
# ============================================================

def find_swing_highs(candles, strength=2):
    if len(candles) < (strength * 2 + 1):
        return []

    result = []

    for i in range(
        strength,
        len(candles) - strength
    ):
        high = safe_float(
            candles[i].get("high")
        )

        if high is None:
            continue

        valid = True

        for j in range(1, strength + 1):
            left = safe_float(
                candles[i - j].get("high")
            )
            right = safe_float(
                candles[i + j].get("high")
            )

            if left is None or right is None:
                valid = False
                break

            if high <= left or high <= right:
                valid = False
                break

        if valid:
            result.append({
                "index": i,
                "price": high
            })

    return result


def find_swing_lows(candles, strength=2):
    if len(candles) < (strength * 2 + 1):
        return []

    result = []

    for i in range(
        strength,
        len(candles) - strength
    ):
        low = safe_float(
            candles[i].get("low")
        )

        if low is None:
            continue

        valid = True

        for j in range(1, strength + 1):
            left = safe_float(
                candles[i - j].get("low")
            )
            right = safe_float(
                candles[i + j].get("low")
            )

            if left is None or right is None:
                valid = False
                break

            if low >= left or low >= right:
                valid = False
                break

        if valid:
            result.append({
                "index": i,
                "price": low
            })

    return result


# ============================================================
# MARKET STRUCTURE
# ============================================================

def market_structure(candles):
    if not candles or len(candles) < 30:
        return "RANGE"

    highs = find_swing_highs(candles, 2)
    lows = find_swing_lows(candles, 2)

    if len(highs) < 2 or len(lows) < 2:
        return "RANGE"

    previous_high = highs[-2]["price"]
    current_high = highs[-1]["price"]

    previous_low = lows[-2]["price"]
    current_low = lows[-1]["price"]

    if (
        current_high > previous_high
        and current_low > previous_low
    ):
        return "BULLISH"

    if (
        current_high < previous_high
        and current_low < previous_low
    ):
        return "BEARISH"

    return "RANGE"


# ============================================================
# EMA DIRECTION
# ============================================================

def ema_direction(candles):
    if not candles:
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
# STOP HUNT
# ============================================================

def detect_stop_hunt(candles, lookback=15):
    if not candles or len(candles) < lookback + 2:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INSUFFICIENT_DATA"
        }

    current = candles[-1]

    previous = candles[-lookback - 1:-1]

    highs = [
        safe_float(c.get("high"))
        for c in previous
        if safe_float(c.get("high")) is not None
    ]

    lows = [
        safe_float(c.get("low"))
        for c in previous
        if safe_float(c.get("low")) is not None
    ]

    if not highs or not lows:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "NO_LEVEL"
        }

    high_level = max(highs)
    low_level = min(lows)

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
        body = max(
            abs(h - l) * 0.15,
            0.00000001
        )

    # SHORT sweep
    if h > high_level and c < high_level:
        if upper_wick(current) >= body * 0.45:
            return {
                "matched": True,
                "direction": "SHORT",
                "level": high_level,
                "reason": "HIGH_SWEEP_RECLAIM"
            }

    # LONG sweep
    if l < low_level and c > low_level:
        if lower_wick(current) >= body * 0.45:
            return {
                "matched": True,
                "direction": "LONG",
                "level": low_level,
                "reason": "LOW_SWEEP_RECLAIM"
            }

    return {
        "matched": False,
        "direction": None,
        "level": None,
        "reason": "NO_STOP_HUNT"
    }


# ============================================================
# THREE TAP
# ============================================================

def detect_three_tap(candles, tolerance=0.008):
    if not candles or len(candles) < 35:
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

    # Three highs
    if len(highs) >= 3:
        taps = highs[-3:]
        levels = [x["price"] for x in taps]
        level = mean(levels)

        if level > 0:
            deviation = max(
                abs(x - level) / level
                for x in levels
            )

            if deviation <= tolerance:

                # Price is near the third-tap zone
                distance = abs(c - level) / level

                if (
                    distance <= tolerance * 1.5
                    or h >= level
                ):
                    return {
                        "matched": True,
                        "direction": "SHORT",
                        "level": level,
                        "reason": "THREE_HIGH_TAPS"
                    }

    # Three lows
    if len(lows) >= 3:
        taps = lows[-3:]
        levels = [x["price"] for x in taps]
        level = mean(levels)

        if level > 0:
            deviation = max(
                abs(x - level) / level
                for x in levels
            )

            if deviation <= tolerance:

                distance = abs(c - level) / level

                if (
                    distance <= tolerance * 1.5
                    or l <= level
                ):
                    return {
                        "matched": True,
                        "direction": "LONG",
                        "level": level,
                        "reason": "THREE_LOW_TAPS"
                    }

    return {
        "matched": False,
        "direction": None,
        "level": None,
        "reason": "NO_THREE_TAP"
    }


# ============================================================
# LIQUIDITY ZONE
# ============================================================

def detect_liquidity_zone(candles, tolerance=0.008):
    if not candles or len(candles) < 35:
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

    # High liquidity zone
    if len(highs) >= 3:

        candidates = [
            x["price"]
            for x in highs[-6:]
        ]

        # Find clusters rather than average everything blindly
        for base in candidates:

            cluster = [
                x for x in candidates
                if abs(x - base) / base <= tolerance
            ]

            if len(cluster) >= 3:

                zone = mean(cluster)

                if h >= zone and c <= zone:

                    return {
                        "matched": True,
                        "direction": "SHORT",
                        "level": zone,
                        "reason": "HIGH_LIQUIDITY_ZONE"
                    }

    # Low liquidity zone
    if len(lows) >= 3:

        candidates = [
            x["price"]
            for x in lows[-6:]
        ]

        for base in candidates:

            cluster = [
                x for x in candidates
                if abs(x - base) / base <= tolerance
            ]

            if len(cluster) >= 3:

                zone = mean(cluster)

                if l <= zone and c >= zone:

                    return {
                        "matched": True,
                        "direction": "LONG",
                        "level": zone,
                        "reason": "LOW_LIQUIDITY_ZONE"
                    }

    return {
        "matched": False,
        "direction": None,
        "level": None,
        "reason": "NO_LIQUIDITY_ZONE"
    }


# ============================================================
# 5M ENTRY TRIGGER
# ============================================================

def entry_trigger(candles, direction):
    if not candles or len(candles) < 3:
        return False

    current = candles[-1]
    previous = candles[-2]

    o, h, l, c = candle_values(current)
    po, ph, pl, pc = candle_values(previous)

    if None in (
        o, h, l, c,
        po, ph, pl, pc
    ):
        return False

    body = candle_body(current)
    previous_body = candle_body(previous)

    candle_range = h - l

    if candle_range <= 0:
        return False

    # LONG:
    # bullish current candle and reasonable body
    if direction == "LONG":

        bullish = c > o

        body_ok = (
            body >= candle_range * 0.25
        )

        momentum = (
            c >= pc
            or c > ph
            or c > o
        )

        return (
            bullish
            and body_ok
            and momentum
        )

    # SHORT
    if direction == "SHORT":

        bearish = c < o

        body_ok = (
            body >= candle_range * 0.25
        )

        momentum = (
            c <= pc
            or c < pl
            or c < o
        )

        return (
            bearish
            and body_ok
            and momentum
        )

    return False


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_trade_levels(
    candles,
    direction,
    strategy_level=None
):
    if not candles or len(candles) < 10:
        return None

    entry = safe_float(
        candles[-1].get("close")
    )

    if entry is None or entry <= 0:
        return None

    recent = candles[-15:]

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

    if direction == "LONG":

        candidates = [
            x for x in lows
            if x < entry
        ]

        if (
            strategy_level is not None
            and strategy_level < entry
        ):
            candidates.append(strategy_level)

        if not candidates:
            return None

        support = max(candidates)

        raw_risk = entry - support

        if raw_risk <= 0:
            return None

        # Prevent absurdly tiny stop
        minimum_risk = entry * 0.0015

        risk_distance = max(
            raw_risk,
            minimum_risk
        )

        sl = entry - risk_distance

        tp1 = entry + risk_distance * 1.5
        tp2 = entry + risk_distance * 2.5
        tp3 = entry + risk_distance * 3.0

    elif direction == "SHORT":

        candidates = [
            x for x in highs
            if x > entry
        ]

        if (
            strategy_level is not None
            and strategy_level > entry
        ):
            candidates.append(strategy_level)

        if not candidates:
            return None

        resistance = min(candidates)

        raw_risk = resistance - entry

        if raw_risk <= 0:
            return None

        minimum_risk = entry * 0.0015

        risk_distance = max(
            raw_risk,
            minimum_risk
        )

        sl = entry + risk_distance

        tp1 = entry - risk_distance * 1.5
        tp2 = entry - risk_distance * 2.5
        tp3 = entry - risk_distance * 3.0

    else:
        return None

    return {
        "entry": round(entry, 8),
        "sl": round(sl, 8),
        "tp1": round(tp1, 8),
        "tp2": round(tp2, 8),
        "tp3": round(tp3, 8),
        "risk": round(risk_distance, 8),
        "rr": "1:1.5 / 1:2.5 / 1:3"
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
# MAIN ENGINE
# ============================================================

def generate_signal(daily, h4, h1, m15, m5):
    if not all([daily, h4, h1, m15, m5]):
        return no_trade("INSUFFICIENT_MARKET_DATA")

    # --------------------------------------------------------
    # MARKET CONTEXT
    # --------------------------------------------------------
    daily_direction = market_structure(daily)
    h4_direction = market_structure(h4)
    h1_direction = market_structure(h1)

    # 1H = MAIN DIRECTION
    if h1_direction not in ("BULLISH", "BEARISH"):
        return no_trade(
            "1H_RANGE",
            daily_direction,
            h4_direction,
            h1_direction
        )

    direction = "LONG" if h1_direction == "BULLISH" else "SHORT"

    # --------------------------------------------------------
    # FILTERS
    # --------------------------------------------------------
    daily_ema = ema_direction(daily)
    h4_ema = ema_direction(h4)
    h1_ema = ema_direction(h1)

    rsi_15m = calculate_rsi(m15)
    volume_is_spike = volume_spike(m5)

    # --------------------------------------------------------
    # STRATEGIES
    # --------------------------------------------------------
    stop_hunt = detect_stop_hunt(m5)
    three_tap = detect_three_tap(m5)
    liquidity_zone = detect_liquidity_zone(m5)

    strategy_details = {
        "STOP_HUNT": stop_hunt,
        "THREE_TAP": three_tap,
        "LIQUIDITY_ZONE": liquidity_zone
    }

    # --------------------------------------------------------
    # FIND STRATEGIES THAT MATCH 1H DIRECTION
    # --------------------------------------------------------
    matching_strategies = []

    if (
        stop_hunt.get("matched")
        and stop_hunt.get("direction") == direction
    ):
        matching_strategies.append("STOP_HUNT")

    if (
        three_tap.get("matched")
        and three_tap.get("direction") == direction
    ):
        matching_strategies.append("THREE_TAP")

    if (
        liquidity_zone.get("matched")
        and liquidity_zone.get("direction") == direction
    ):
        matching_strategies.append("LIQUIDITY_ZONE")

    # --------------------------------------------------------
    # IMPORTANT:
    # Strategy may exist but be opposite to 1H.
    # Do NOT call that simply "NO STRATEGY".
    # --------------------------------------------------------
    if not matching_strategies:

        opposite_strategies = []

        for name, data in strategy_details.items():
            if not isinstance(data, dict):
                continue

            if not data.get("matched"):
                continue

            strategy_direction = data.get("direction")

            if strategy_direction:
                opposite_strategies.append(
                    f"{name}_{strategy_direction}"
                )

        if opposite_strategies:
            reason = (
                "STRATEGY_OPPOSITE_1H:"
                + ",".join(opposite_strategies)
            )
        else:
            reason = "NO_MAIN_SETUP"

        return no_trade(
            reason,
            daily_direction,
            h4_direction,
            h1_direction,
            rsi_15m,
            strategy_details
        )

    # --------------------------------------------------------
    # 5M ENTRY TRIGGER
    # --------------------------------------------------------
    confirmation = entry_trigger(m5, direction)

    if not confirmation:
        return no_trade(
            "5M_ENTRY_TRIGGER_MISSING",
            daily_direction,
            h4_direction,
            h1_direction,
            rsi_15m,
            strategy_details
        )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------
    score = 0

    # Main 1H direction + valid strategy
    score += 5

    # Valid 5M entry trigger
    score += 2

    # Base setup quality
    score += 1

    # Multiple strategies
    if len(matching_strategies) >= 2:
        score += 1

    # Daily alignment = bonus only
    if (
        (direction == "LONG" and daily_direction == "BULLISH")
        or
        (direction == "SHORT" and daily_direction == "BEARISH")
    ):
        score += 1

    # 4H alignment = BONUS ONLY
    # IMPORTANT: 4H NEVER BLOCKS THE TRADE
    if (
        (direction == "LONG" and h4_direction == "BULLISH")
        or
        (direction == "SHORT" and h4_direction == "BEARISH")
    ):
        score += 1

    # 15M RSI filter/bonus
    if rsi_15m is not None:

        if direction == "LONG":
            if 35 <= rsi_15m < 70:
                score += 1

        elif direction == "SHORT":
            if 30 < rsi_15m <= 65:
                score += 1

    # Volume bonus
    if volume_is_spike:
        score += 1

    # --------------------------------------------------------
    # QUALITY
    # --------------------------------------------------------
    if score < 8:
        return no_trade(
            "SIGNAL_QUALITY_TOO_LOW",
            daily_direction,
            h4_direction,
            h1_direction,
            rsi_15m,
            strategy_details,
            score
        )

    # --------------------------------------------------------
    # STRATEGY PRIORITY
    # --------------------------------------------------------
    priority = [
        "STOP_HUNT",
        "LIQUIDITY_ZONE",
        "THREE_TAP"
    ]

    selected_strategy = None
    strategy_level = None

    for name in priority:

        if name in matching_strategies:

            selected_strategy = name
            strategy_level = strategy_details[name].get("level")

            break

    # --------------------------------------------------------
    # TRADE LEVELS
    # --------------------------------------------------------
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

    # --------------------------------------------------------
    # HIGH SIGNAL
    # --------------------------------------------------------
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
        "volume_spike": volume_is_spike,
        "confirmation": confirmation,

        "strategies": matching_strategies,
        "strategy_matches": matching_strategies,
        "strategy": selected_strategy,
        "strategy_details": strategy_details,

        "stop_hunt": "STOP_HUNT" in matching_strategies,
        "three_tap": "THREE_TAP" in matching_strategies,
        "liquidity_zone": "LIQUIDITY_ZONE" in matching_strategies,

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
            + " + 5M_ENTRY"
        )
}
