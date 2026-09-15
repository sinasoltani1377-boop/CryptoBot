# ============================================================
# CryptoBot - Professional Analysis Engine
# ============================================================

from math import isfinite


# ============================================================
# BASIC HELPERS
# ============================================================

def get_closes(candles):
    return [float(c["close"]) for c in candles]


def get_highs(candles):
    return [float(c["high"]) for c in candles]


def get_lows(candles):
    return [float(c["low"]) for c in candles]


def get_opens(candles):
    return [float(c["open"]) for c in candles]


def safe_float(value, default=0.0):
    try:
        value = float(value)
        if isfinite(value):
            return value
    except (TypeError, ValueError):
        pass

    return default


# ============================================================
# EMA
# ============================================================

def calculate_ema(candles, period):
    if len(candles) < period:
        return None

    closes = get_closes(candles)

    multiplier = 2 / (period + 1)

    ema = sum(closes[:period]) / period

    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def ema_trend(candles):
    if len(candles) < 200:
        return "UNKNOWN"

    ema20 = calculate_ema(candles, 20)
    ema50 = calculate_ema(candles, 50)
    ema200 = calculate_ema(candles, 200)

    price = safe_float(candles[-1]["close"])

    if ema20 is None or ema50 is None or ema200 is None:
        return "UNKNOWN"

    if price > ema200 and ema20 > ema50 and ema50 > ema200:
        return "BULLISH"

    if price < ema200 and ema20 < ema50 and ema50 < ema200:
        return "BEARISH"

    return "MIXED"


def ema_details(candles):
    return {
        "ema20": calculate_ema(candles, 20),
        "ema50": calculate_ema(candles, 50),
        "ema200": calculate_ema(candles, 200),
        "trend": ema_trend(candles)
    }


# ============================================================
# SWING DETECTION
# ============================================================

def find_swings(candles, strength=2):
    swing_highs = []
    swing_lows = []

    if len(candles) < (strength * 2 + 1):
        return swing_highs, swing_lows

    for i in range(strength, len(candles) - strength):

        current_high = safe_float(candles[i]["high"])
        current_low = safe_float(candles[i]["low"])

        left_highs = [
            safe_float(candles[j]["high"])
            for j in range(i - strength, i)
        ]

        right_highs = [
            safe_float(candles[j]["high"])
            for j in range(i + 1, i + strength + 1)
        ]

        left_lows = [
            safe_float(candles[j]["low"])
            for j in range(i - strength, i)
        ]

        right_lows = [
            safe_float(candles[j]["low"])
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


# ============================================================
# MARKET STRUCTURE
# ============================================================

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


def structure_details(candles):
    swing_highs, swing_lows = find_swings(candles)

    result = {
        "direction": get_structure_direction(candles),
        "last_high": None,
        "previous_high": None,
        "last_low": None,
        "previous_low": None
    }

    if len(swing_highs) >= 2:
        result["previous_high"] = swing_highs[-2]["price"]
        result["last_high"] = swing_highs[-1]["price"]

    if len(swing_lows) >= 2:
        result["previous_low"] = swing_lows[-2]["price"]
        result["last_low"] = swing_lows[-1]["price"]

    return result


# ============================================================
# MULTI TIMEFRAME ANALYSIS
# ============================================================

def analyze_all_timeframes(market_data):
    result = {}

    for timeframe in ["daily", "4h", "1h"]:
        candles = market_data.get(timeframe, [])

        if not candles:
            result[timeframe] = "UNKNOWN"
        else:
            result[timeframe] = get_structure_direction(candles)

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


# ============================================================
# BOS
# ============================================================

def detect_bos(candles):
    if len(candles) < 10:
        return "NO_BOS"

    swing_highs, swing_lows = find_swings(candles)

    if not swing_highs or not swing_lows:
        return "NO_BOS"

    last_candle = candles[-1]

    close = safe_float(last_candle["close"])

    last_swing_high = swing_highs[-1]["price"]
    last_swing_low = swing_lows[-1]["price"]

    if close > last_swing_high:
        return "BULLISH_BOS"

    if close < last_swing_low:
        return "BEARISH_BOS"

    return "NO_BOS"


# ============================================================
# PULLBACK
# ============================================================

def detect_pullback(candles, lookback=10):
    if len(candles) < lookback:
        return "UNKNOWN"

    recent = candles[-lookback:]

    highest = max(get_highs(recent))
    lowest = min(get_lows(recent))
    last_close = safe_float(recent[-1]["close"])

    price_range = highest - lowest

    if price_range <= 0:
        return "NO_PULLBACK"

    position = (last_close - lowest) / price_range

    if position < 0.35:
        return "PULLBACK_DOWN"

    if position > 0.65:
        return "PULLBACK_UP"

    return "NO_PULLBACK"


# ============================================================
# SUPPORT / RESISTANCE
# ============================================================

def find_support_resistance(candles, lookback=80):
    if len(candles) < 10:
        return {
            "support": None,
            "resistance": None
        }

    recent = candles[-lookback:]

    swing_highs, swing_lows = find_swings(recent)

    resistance = None
    support = None

    if swing_highs:
        resistance = swing_highs[-1]["price"]

    if swing_lows:
        support = swing_lows[-1]["price"]

    return {
        "support": support,
        "resistance": resistance
    }


# ============================================================
# BREAKOUT + RETEST
# ============================================================

def detect_breakout_retest(candles, direction):
    if len(candles) < 20:
        return False

    levels = find_support_resistance(candles[:-3])

    support = levels["support"]
    resistance = levels["resistance"]

    if support is None or resistance is None:
        return False

    recent = candles[-3:]

    if direction == "LONG":

        breakout = safe_float(recent[0]["close"]) > resistance

        retest = (
            safe_float(recent[1]["low"]) <= resistance
            and safe_float(recent[1]["close"]) > resistance
        )

        confirmation = safe_float(recent[2]["close"]) > safe_float(
            recent[2]["open"]
        )

        return breakout and retest and confirmation

    if direction == "SHORT":

        breakout = safe_float(recent[0]["close"]) < support

        retest = (
            safe_float(recent[1]["high"]) >= support
            and safe_float(recent[1]["close"]) < support
        )

        confirmation = safe_float(recent[2]["close"]) < safe_float(
            recent[2]["open"]
        )

        return breakout and retest and confirmation

    return False


# ============================================================
# CONFIRMATION CANDLE
# ============================================================

def confirmation_candle(candles, direction):
    if len(candles) < 2:
        return False

    candle = candles[-1]

    open_price = safe_float(candle["open"])
    close_price = safe_float(candle["close"])
    high = safe_float(candle["high"])
    low = safe_float(candle["low"])

    body = abs(close_price - open_price)
    candle_range = high - low

    if candle_range <= 0:
        return False

    body_ratio = body / candle_range

    if body_ratio < 0.55:
        return False

    previous = candles[-2]

    previous_open = safe_float(previous["open"])
    previous_close = safe_float(previous["close"])

    previous_body = abs(previous_close - previous_open)

    if direction == "LONG":

        if close_price <= open_price:
            return False

        if body < previous_body:
            return False

        return True

    if direction == "SHORT":

        if close_price >= open_price:
            return False

        if body < previous_body:
            return False

        return True

    return False


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def detect_liquidity_sweep(candles, direction):
    if len(candles) < 15:
        return False

    swing_highs, swing_lows = find_swings(candles[:-1])

    current = candles[-1]

    current_high = safe_float(current["high"])
    current_low = safe_float(current["low"])
    current_close = safe_float(current["close"])

    if direction == "LONG":

        if not swing_lows:
            return False

        level = swing_lows[-1]["price"]

        swept = current_low < level
        reclaimed = current_close > level

        return swept and reclaimed

    if direction == "SHORT":

        if not swing_highs:
            return False

        level = swing_highs[-1]["price"]

        swept = current_high > level
        rejected = current_close < level

        return swept and rejected

    return False


# ============================================================
# ORDER BLOCK
# ============================================================

def detect_order_block(candles, direction):
    if len(candles) < 10:
        return False

    recent = candles[-8:]

    for i in range(len(recent) - 3):

        candle = recent[i]

        open_price = safe_float(candle["open"])
        close_price = safe_float(candle["close"])

        next_candles = recent[i + 1:i + 4]

        if direction == "LONG":

            bearish = close_price < open_price

            if not bearish:
                continue

            highest_after = max(
                safe_float(c["high"])
                for c in next_candles
            )

            body = abs(close_price - open_price)

            if body == 0:
                continue

            if highest_after > safe_float(candle["high"]) + body:
                return True

        if direction == "SHORT":

            bullish = close_price > open_price

            if not bullish:
                continue

            lowest_after = min(
                safe_float(c["low"])
                for c in next_candles
            )

            body = abs(close_price - open_price)

            if body == 0:
                continue

            if lowest_after < safe_float(candle["low"]) - body:
                return True

    return False


# ============================================================
# RANGE DETECTION
# ============================================================

def detect_range(candles, lookback=30):
    if len(candles) < lookback:
        return False

    recent = candles[-lookback:]

    highest = max(get_highs(recent))
    lowest = min(get_lows(recent))

    if lowest <= 0:
        return False

    current = safe_float(recent[-1]["close"])

    range_size = highest - lowest
    range_percent = (range_size / lowest) * 100

    if range_percent > 8:
        return False

    position = (current - lowest) / range_size

    return 0.15 <= position <= 0.85


def range_signal(candles):
    if not detect_range(candles):
        return "NONE"

    recent = candles[-30:]

    highest = max(get_highs(recent))
    lowest = min(get_lows(recent))

    current = safe_float(candles[-1]["close"])

    distance_from_low = abs(current - lowest)
    distance_from_high = abs(highest - current)

    range_size = highest - lowest

    if range_size <= 0:
        return "NONE"

    if distance_from_low / range_size < 0.20:
        return "LONG_ZONE"

    if distance_from_high / range_size < 0.20:
        return "SHORT_ZONE"

    return "MID_ZONE"


# ============================================================
# TREND PULLBACK STRATEGY
# ============================================================

def trend_pullback_signal(candles, direction):
    if len(candles) < 50:
        return False

    trend = ema_trend(candles)

    if direction == "LONG" and trend != "BULLISH":
        return False

    if direction == "SHORT" and trend != "BEARISH":
        return False

    pullback = detect_pullback(candles)

    if direction == "LONG":
        return pullback == "PULLBACK_DOWN"

    if direction == "SHORT":
        return pullback == "PULLBACK_UP"

    return False


# ============================================================
# SUPPORT / RESISTANCE REVERSAL
# ============================================================

def sr_reversal_signal(candles, direction):
    if len(candles) < 20:
        return False

    levels = find_support_resistance(candles[:-2])

    support = levels["support"]
    resistance = levels["resistance"]

    current = candles[-1]

    close = safe_float(current["close"])
    high = safe_float(current["high"])
    low = safe_float(current["low"])

    if direction == "LONG" and support is not None:

        touched = low <= support * 1.003
        rejected = close > support

        return touched and rejected

    if direction == "SHORT" and resistance is not None:

        touched = high >= resistance * 0.997
        rejected = close < resistance

        return touched and rejected

    return False


# ============================================================
# TREND STRENGTH
# ============================================================

def trend_strength(candles):
    if len(candles) < 50:
        return "UNKNOWN"

    structure = get_structure_direction(candles)
    ema = ema_trend(candles)

    if structure == "BULLISH" and ema == "BULLISH":
        return "STRONG_BULLISH"

    if structure == "BEARISH" and ema == "BEARISH":
        return "STRONG_BEARISH"

    if structure == ema and structure in ["BULLISH", "BEARISH"]:
        return "MODERATE"

    return "WEAK"


# ============================================================
# STRATEGY SCORE
# ============================================================

def calculate_signal_score(market_data, direction):
    candles_1h = market_data.get("1h", [])

    if len(candles_1h) < 20:
        return {
            "score": 0,
            "max_score": 10,
            "details": []
        }

    score = 0
    details = []

    # --------------------------------------------------------
    # 1. Multi-timeframe trend
    # --------------------------------------------------------

    alignment = check_trend_alignment(market_data)

    if direction == "LONG":

        if alignment["daily"] == "BULLISH":
            score += 1
            details.append("DAILY_BULLISH")

        if alignment["4h"] == "BULLISH":
            score += 1
            details.append("4H_BULLISH")

    if direction == "SHORT":

        if alignment["daily"] == "BEARISH":
            score += 1
            details.append("DAILY_BEARISH")

        if alignment["4h"] == "BEARISH":
            score += 1
            details.append("4H_BEARISH")

    # --------------------------------------------------------
    # 2. EMA
    # --------------------------------------------------------

    ema = ema_trend(candles_1h)

    if direction == "LONG" and ema == "BULLISH":
        score += 1
        details.append("EMA_BULLISH")

    if direction == "SHORT" and ema == "BEARISH":
        score += 1
        details.append("EMA_BEARISH")

    # --------------------------------------------------------
    # 3. BOS
    # --------------------------------------------------------

    bos = detect_bos(candles_1h)

    if direction == "LONG" and bos == "BULLISH_BOS":
        score += 1
        details.append("BULLISH_BOS")

    if direction == "SHORT" and bos == "BEARISH_BOS":
        score += 1
        details.append("BEARISH_BOS")

    # --------------------------------------------------------
    # 4. Breakout + Retest
    # --------------------------------------------------------

    if detect_breakout_retest(candles_1h, direction):
        score += 2
        details.append("BREAKOUT_RETEST")

    # --------------------------------------------------------
    # 5. Trend Pullback
    # --------------------------------------------------------

    if trend_pullback_signal(candles_1h, direction):
        score += 1
        details.append("TREND_PULLBACK")

    # --------------------------------------------------------
    # 6. Liquidity Sweep
    # --------------------------------------------------------

    if detect_liquidity_sweep(candles_1h, direction):
        score += 1
        details.append("LIQUIDITY_SWEEP")

    # --------------------------------------------------------
    # 7. Order Block
    # --------------------------------------------------------

    if detect_order_block(candles_1h, direction):
        score += 1
        details.append("ORDER_BLOCK")

    # --------------------------------------------------------
    # 8. S/R Reversal
    # --------------------------------------------------------

    if sr_reversal_signal(candles_1h, direction):
        score += 1
        details.append("SR_REVERSAL")

    # --------------------------------------------------------
    # 9. Confirmation candle
    # --------------------------------------------------------

    if confirmation_candle(candles_1h, direction):
        score += 1
        details.append("CONFIRMATION")

    return {
        "score": score,
        "max_score": 11,
        "details": details
    }


# ============================================================
# QUALITY FILTER
# ============================================================

def quality_filter(score_data):
    score = score_data["score"]

    # High-quality setup
    if score >= 8:
        return "HIGH"

    # Medium setup - rejected for final signal
    if score >= 6:
        return "MEDIUM"

    return "LOW"


# ============================================================
# FINAL SIGNAL ENGINE
# ============================================================
def calculate_trade_levels(candles, direction):
    """
    Calculate Entry, Stop Loss and Take Profit levels
    based on recent swing structure.
    """

    if not candles or len(candles) < 10:
        return None

    try:
        recent = candles[-20:]

        highs = [float(c["high"]) for c in recent]
        lows = [float(c["low"]) for c in recent]
        closes = [float(c["close"]) for c in recent]

        entry = closes[-1]

        if direction == "LONG":

            swing_low = min(lows[-8:])

            risk = entry - swing_low

            if risk <= 0:
                return None

            sl = swing_low

            tp1 = entry + (risk * 1.5)
            tp2 = entry + (risk * 2)
            tp3 = entry + (risk * 3)

        elif direction == "SHORT":

            swing_high = max(highs[-8:])

            risk = swing_high - entry

            if risk <= 0:
                return None

            sl = swing_high

            tp1 = entry - (risk * 1.5)
            tp2 = entry - (risk * 2)
            tp3 = entry - (risk * 3)

        else:
            return None

        return {
            "entry": round(entry, 4),
            "sl": round(sl, 4),
            "tp1": round(tp1, 4),
            "tp2": round(tp2, 4),
            "tp3": round(tp3, 4),
            "risk": round(risk, 4),
            "rr": 3
        }

    except Exception:
        return None
def generate_signal(market_data):

    alignment = check_trend_alignment(market_data)

    daily = alignment["daily"]
    four_hour = alignment["4h"]
    one_hour = alignment["1h"]

    candles = market_data.get("1h", [])

    if len(candles) < 50:
        return {
            "daily": daily,
            "4h": four_hour,
            "1h": one_hour,
            "signal": "NO_TRADE",
            "reason": "NOT_ENOUGH_CANDLES",
            "score": 0,
            "quality": "LOW",
            "strategy_matches": []
        }

    # ========================================================
    # DIRECTION
    # ========================================================

    if daily == "BULLISH":
        direction = "LONG"

    elif daily == "BEARISH":
        direction = "SHORT"

    else:
        return {
            "daily": daily,
            "4h": four_hour,
            "1h": one_hour,
            "signal": "NO_TRADE",
            "reason": "DAILY_RANGE",
            "score": 0,
            "quality": "LOW",
            "strategy_matches": []
        }

    # ========================================================
    # 4H FILTER
    # ========================================================

    if direction == "LONG" and four_hour == "BEARISH":
        return {
            "daily": daily,
            "4h": four_hour,
            "1h": one_hour,
            "direction": direction,
            "signal": "NO_TRADE",
            "reason": "4H_AGAINST_DAILY",
            "score": 0,
            "quality": "LOW",
            "strategy_matches": []
        }

    if direction == "SHORT" and four_hour == "BULLISH":
        return {
            "daily": daily,
            "4h": four_hour,
            "1h": one_hour,
            "direction": direction,
            "signal": "NO_TRADE",
            "reason": "4H_AGAINST_DAILY",
            "score": 0,
            "quality": "LOW",
            "strategy_matches": []
        }

    # ========================================================
    # INDICATORS
    # ========================================================

    ema = ema_trend(candles)

    bos = detect_bos(candles)

    confirmation = confirmation_candle(
        candles,
        direction
    )

    pullback = trend_pullback_signal(
        candles,
        direction
    )

    sweep = detect_liquidity_sweep(
        candles,
        direction
    )

    order_block = detect_order_block(
        candles,
        direction
    )

    breakout_retest = detect_breakout_retest(
        candles,
        direction
    )

    sr_reversal = sr_reversal_signal(
        candles,
        direction
    )

    # ========================================================
    # SCORE
    # ========================================================

    score = 0
    strategies = []

    # Daily
    score += 2
    strategies.append(
        "DAILY_BULLISH"
        if direction == "LONG"
        else "DAILY_BEARISH"
    )

    # 4H
    if (
        (direction == "LONG" and four_hour == "BULLISH")
        or
        (direction == "SHORT" and four_hour == "BEARISH")
    ):
        score += 2
        strategies.append(
            "4H_BULLISH"
            if direction == "LONG"
            else "4H_BEARISH"
        )

    # 1H
    if (
        (direction == "LONG" and one_hour == "BULLISH")
        or
        (direction == "SHORT" and one_hour == "BEARISH")
    ):
        score += 1
        strategies.append(
            "1H_BULLISH"
            if direction == "LONG"
            else "1H_BEARISH"
        )

    # EMA
    if (
        (direction == "LONG" and ema == "BULLISH")
        or
        (direction == "SHORT" and ema == "BEARISH")
    ):
        score += 1
        strategies.append(
            "EMA_BULLISH"
            if direction == "LONG"
            else "EMA_BEARISH"
        )

    # ========================================================
    # MAIN SETUPS
    # ========================================================

    setup_count = 0

    if pullback:
        score += 2
        setup_count += 1
        strategies.append("TREND_PULLBACK")

    if breakout_retest:
        score += 2
        setup_count += 1
        strategies.append("BREAKOUT_RETEST")

    if sweep:
        score += 2
        setup_count += 1
        strategies.append("LIQUIDITY_SWEEP")

    if order_block:
        score += 2
        setup_count += 1
        strategies.append("ORDER_BLOCK")

    if sr_reversal:
        score += 1
        setup_count += 1
        strategies.append("SR_REVERSAL")

    # ========================================================
    # BOS IS CONFIRMATION ONLY
    # ========================================================

    if (
        direction == "LONG"
        and bos == "BULLISH_BOS"
    ):
        score += 1
        strategies.append("BULLISH_BOS")

    if (
        direction == "SHORT"
        and bos == "BEARISH_BOS"
    ):
        score += 1
        strategies.append("BEARISH_BOS")

    # ========================================================
    # NO MAIN SETUP
    # ========================================================

    if setup_count == 0:
        return {
            "daily": daily,
            "4h": four_hour,
            "1h": one_hour,
            "direction": direction,
            "score": score,
            "quality": "LOW",
            "signal": "NO_TRADE",
            "reason": "NO_MAIN_SETUP",
            "strategy_matches": strategies
        }

    # ========================================================
    # CONFIRMATION
    # ========================================================

    if not confirmation:
        return {
            "daily": daily,
            "4h": four_hour,
            "1h": one_hour,
            "direction": direction,
            "score": score,
            "quality": "LOW",
            "signal": "NO_TRADE",
            "reason": "WAITING_CONFIRMATION",
            "strategy_matches": strategies
        }

    score += 1
    strategies.append("CONFIRMATION")

    # ========================================================
    # QUALITY
    # ========================================================

    if score >= 8:
        quality = "HIGH"

    elif score >= 6:
        quality = "MEDIUM"

    else:
        quality = "LOW"

    # ========================================================
    # FINAL FILTER
    # ========================================================

    if score < 6:
        return {
            "daily": daily,
            "4h": four_hour,
            "1h": one_hour,
            "direction": direction,
            "score": score,
            "quality": quality,
            "signal": "NO_TRADE",
            "reason": "SCORE_TOO_LOW",
            "strategy_matches": strategies
        }

    # ========================================================
    # FINAL SIGNAL
    # ========================================================

    return {
        "daily": daily,
        "4h": four_hour,
        "1h": one_hour,
        "direction": direction,

        "ema": ema,
        "bos": bos,

        "pullback": pullback,
        "liquidity_sweep": sweep,
        "order_block": order_block,
        "breakout_retest": breakout_retest,
        "sr_reversal": sr_reversal,

        "confirmation": confirmation,

        "score": score,
        "quality": quality,

        "signal": direction,
        "reason": "ACTIVE_SETUP",

        "strategy_matches": strategies
    }
