# ============================================================
# CryptoBot - Professional Analysis Engine v3
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


def get_closes(candles):
    return [safe_float(c.get("close")) for c in candles]


def get_highs(candles):
    return [safe_float(c.get("high")) for c in candles]


def get_lows(candles):
    return [safe_float(c.get("low")) for c in candles]


def get_opens(candles):
    return [safe_float(c.get("open")) for c in candles]


# ============================================================
# EMA
# ============================================================

def calculate_ema(candles, period):
    if len(candles) < period:
        return None

    closes = get_closes(candles)

    if not closes:
        return None

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

    price = safe_float(candles[-1].get("close"))

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
        "trend": ema_trend(candles),
    }


# ============================================================
# SWING DETECTION
# ============================================================

def find_swings(candles, strength=2):
    swing_highs = []
    swing_lows = []

    required = strength * 2 + 1

    if len(candles) < required:
        return swing_highs, swing_lows

    for i in range(strength, len(candles) - strength):

        current_high = safe_float(candles[i].get("high"))
        current_low = safe_float(candles[i].get("low"))

        left_highs = [
            safe_float(candles[j].get("high"))
            for j in range(i - strength, i)
        ]

        right_highs = [
            safe_float(candles[j].get("high"))
            for j in range(i + 1, i + strength + 1)
        ]

        left_lows = [
            safe_float(candles[j].get("low"))
            for j in range(i - strength, i)
        ]

        right_lows = [
            safe_float(candles[j].get("low"))
            for j in range(i + 1, i + strength + 1)
        ]

        # Swing High
        if current_high > max(left_highs + right_highs):
            swing_highs.append({
                "index": i,
                "price": current_high,
            })

        # Swing Low
        if current_low < min(left_lows + right_lows):
            swing_lows.append({
                "index": i,
                "price": current_low,
            })

    return swing_highs, swing_lows


# ============================================================
# MARKET STRUCTURE
# ============================================================

def get_structure_direction(candles):
    swing_highs, swing_lows = find_swings(candles)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "RANGE"

    last_high = swing_highs[-1]["price"]
    previous_high = swing_highs[-2]["price"]

    last_low = swing_lows[-1]["price"]
    previous_low = swing_lows[-2]["price"]

    if last_high > previous_high and last_low > previous_low:
        return "BULLISH"

    if last_high < previous_high and last_low < previous_low:
        return "BEARISH"

    return "RANGE"


def structure_details(candles):
    swing_highs, swing_lows = find_swings(candles)

    return {
        "direction": get_structure_direction(candles),
        "swing_highs": swing_highs[-5:],
        "swing_lows": swing_lows[-5:],
    }


# ============================================================
# MULTI TIMEFRAME
# ============================================================

def analyze_all_timeframes(daily, h4, h1):
    return {
        "daily": get_structure_direction(daily),
        "4h": get_structure_direction(h4),
        "1h": get_structure_direction(h1),
    }


def check_trend_alignment(daily, h4, h1):
    d = get_structure_direction(daily)
    h4_trend = get_structure_direction(h4)
    h1_trend = get_structure_direction(h1)

    if d == "BULLISH" and h4_trend == "BULLISH":
        return "BULLISH"

    if d == "BEARISH" and h4_trend == "BEARISH":
        return "BEARISH"

    if d == "BULLISH" and h4_trend == "RANGE":
        return "BULLISH_WEAK"

    if d == "BEARISH" and h4_trend == "RANGE":
        return "BEARISH_WEAK"

    return "NO_ALIGNMENT"


# ============================================================
# BREAK OF STRUCTURE
# ============================================================

def detect_bos(candles):
    if len(candles) < 10:
        return None

    swing_highs, swing_lows = find_swings(candles[:-1])

    current_close = safe_float(candles[-1].get("close"))

    if swing_highs:
        last_high = swing_highs[-1]["price"]

        if current_close > last_high:
            return "LONG"

    if swing_lows:
        last_low = swing_lows[-1]["price"]

        if current_close < last_low:
            return "SHORT"

    return None


# ============================================================
# PULLBACK
# ============================================================

def detect_pullback(candles, direction):
    if len(candles) < 8:
        return False

    recent = candles[-6:]

    highs = get_highs(recent)
    lows = get_lows(recent)

    current_close = safe_float(candles[-1].get("close"))

    recent_high = max(highs)
    recent_low = min(lows)

    total_range = recent_high - recent_low

    if total_range <= 0:
        return False

    position = (current_close - recent_low) / total_range

    if direction == "LONG":
        return position < 0.70

    if direction == "SHORT":
        return position > 0.30

    return False


# ============================================================
# SUPPORT / RESISTANCE
# ============================================================

def find_support_resistance(candles):
    swing_highs, swing_lows = find_swings(candles)

    resistance = None
    support = None

    if swing_highs:
        resistance = swing_highs[-1]["price"]

    if swing_lows:
        support = swing_lows[-1]["price"]

    return {
        "support": support,
        "resistance": resistance,
    }


# ============================================================
# BREAKOUT + RETEST
# ============================================================

def detect_breakout_retest(candles, direction):
    if len(candles) < 12:
        return False

    sr = find_support_resistance(candles[:-3])

    support = sr.get("support")
    resistance = sr.get("resistance")

    recent = candles[-3:]

    if direction == "LONG" and resistance is not None:
        breakout = safe_float(recent[1].get("close")) > resistance
        retest = safe_float(recent[2].get("low")) <= resistance
        close_above = safe_float(recent[2].get("close")) > resistance

        return breakout and retest and close_above

    if direction == "SHORT" and support is not None:
        breakout = safe_float(recent[1].get("close")) < support
        retest = safe_float(recent[2].get("high")) >= support
        close_below = safe_float(recent[2].get("close")) < support

        return breakout and retest and close_below

    return False


# ============================================================
# CONFIRMATION CANDLE
# ============================================================

def confirmation_candle(candles, direction):
    if len(candles) < 3:
        return False

    previous = candles[-2]
    current = candles[-1]

    prev_open = safe_float(previous.get("open"))
    prev_close = safe_float(previous.get("close"))

    current_open = safe_float(current.get("open"))
    current_close = safe_float(current.get("close"))

    prev_body = abs(prev_close - prev_open)
    current_body = abs(current_close - current_open)

    if prev_body <= 0:
        prev_body = 0.00000001

    if direction == "LONG":
        bullish = current_close > current_open
        stronger = current_body >= prev_body * 1.05

        return bullish and stronger

    if direction == "SHORT":
        bearish = current_close < current_open
        stronger = current_body >= prev_body * 1.05

        return bearish and stronger

    return False


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def detect_liquidity_sweep(candles, direction):
    if len(candles) < 8:
        return False

    previous_candles = candles[:-1]

    swing_highs, swing_lows = find_swings(previous_candles)

    current = candles[-1]

    current_high = safe_float(current.get("high"))
    current_low = safe_float(current.get("low"))
    current_close = safe_float(current.get("close"))

    if direction == "LONG" and swing_lows:
        liquidity_level = swing_lows[-1]["price"]

        swept = current_low < liquidity_level
        reclaimed = current_close > liquidity_level

        return swept and reclaimed

    if direction == "SHORT" and swing_highs:
        liquidity_level = swing_highs[-1]["price"]

        swept = current_high > liquidity_level
        rejected = current_close < liquidity_level

        return swept and rejected

    return False


# ============================================================
# ORDER BLOCK
# ============================================================

def detect_order_block(candles, direction):
    if len(candles) < 6:
        return False

    recent = candles[-6:]

    for i in range(len(recent) - 2):
        candle = recent[i]
        next_candle = recent[i + 1]

        open_price = safe_float(candle.get("open"))
        close_price = safe_float(candle.get("close"))

        next_open = safe_float(next_candle.get("open"))
        next_close = safe_float(next_candle.get("close"))

        body = abs(close_price - open_price)
        next_body = abs(next_close - next_open)

        if body <= 0:
            continue

        if direction == "LONG":
            bearish_candle = close_price < open_price
            strong_move = (
                next_close > next_open
                and next_body >= body * 1.3
            )

            if bearish_candle and strong_move:
                return True

        if direction == "SHORT":
            bullish_candle = close_price > open_price
            strong_move = (
                next_close < next_open
                and next_body >= body * 1.3
            )

            if bullish_candle and strong_move:
                return True

    return False


# ============================================================
# RANGE
# ============================================================

def detect_range(candles):
    if len(candles) < 20:
        return False

    recent = candles[-20:]

    highest = max(get_highs(recent))
    lowest = min(get_lows(recent))

    current = safe_float(candles[-1].get("close"))

    if current <= 0:
        return False

    range_percent = ((highest - lowest) / current) * 100

    return range_percent <= 5.0


def range_signal(candles):
    if not detect_range(candles):
        return None

    recent = candles[-20:]

    highest = max(get_highs(recent))
    lowest = min(get_lows(recent))

    current = safe_float(candles[-1].get("close"))

    distance_high = abs(highest - current)
    distance_low = abs(current - lowest)

    if distance_low < distance_high:
        return "LONG"

    return "SHORT"


# ============================================================
# TREND PULLBACK
# ============================================================

def trend_pullback_signal(candles, direction):
    structure = get_structure_direction(candles)

    if direction == "LONG":
        return (
            structure == "BULLISH"
            and detect_pullback(candles, "LONG")
        )

    if direction == "SHORT":
        return (
            structure == "BEARISH"
            and detect_pullback(candles, "SHORT")
        )

    return False


# ============================================================
# SUPPORT / RESISTANCE REVERSAL
# ============================================================

def sr_reversal_signal(candles, direction):
    if len(candles) < 10:
        return False

    sr = find_support_resistance(candles)

    support = sr.get("support")
    resistance = sr.get("resistance")

    current = candles[-1]

    current_high = safe_float(current.get("high"))
    current_low = safe_float(current.get("low"))
    current_close = safe_float(current.get("close"))

    if direction == "LONG" and support is not None:
        touched = current_low <= support * 1.003
        recovered = current_close > support

        return touched and recovered

    if direction == "SHORT" and resistance is not None:
        touched = current_high >= resistance * 0.997
        rejected = current_close < resistance

        return touched and rejected

    return False


# ============================================================
# TREND STRENGTH
# ============================================================

def trend_strength(candles):
    if len(candles) < 50:
        return 0

    structure = get_structure_direction(candles)
    ema = ema_trend(candles)

    score = 0

    if structure in ("BULLISH", "BEARISH"):
        score += 1

    if ema in ("BULLISH", "BEARISH"):
        score += 1

    if structure == ema:
        score += 1

    return score


# ============================================================
# QUALITY
# ============================================================

def quality_filter(score):
    if score >= 8:
        return "HIGH"

    if score >= 6:
        return "MEDIUM"

    return "LOW"


# ============================================================
# DIRECTION
# ============================================================

def direction_to_trend(direction):
    if direction == "LONG":
        return "BULLISH"

    if direction == "SHORT":
        return "BEARISH"

    return "RANGE"


# ============================================================
# SCORE
# ============================================================

def calculate_signal_score(
    daily_trend,
    h4_trend,
    h1_trend,
    direction,
    ema,
    main_setup,
    bos,
    confirmation,
):
    score = 0
    strategies = []

    expected = direction_to_trend(direction)

    if daily_trend == expected:
        score += 2

    if h4_trend == expected:
        score += 2

    if h1_trend == expected:
        score += 1

    if ema == expected:
        score += 1

    if main_setup:
        score += 2
        strategies.extend(main_setup)

    if bos == direction:
        score += 1
        strategies.append("BOS")

    if confirmation:
        score += 1
        strategies.append("CONFIRMATION")

    strategies = list(dict.fromkeys(strategies))

    return {
        "score": score,
        "max_score": 10,
        "quality": quality_filter(score),
        "strategies": strategies,
    }


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_trade_levels(candles, direction):
    if len(candles) < 10:
        return None

    entry = safe_float(candles[-1].get("close"))

    if entry <= 0:
        return None

    recent = candles[-8:]

    recent_high = max(get_highs(recent))
    recent_low = min(get_lows(recent))

    if direction == "LONG":
        sl = recent_low

        if sl >= entry:
            return None

        risk = entry - sl

        if risk <= 0:
            return None

        return {
            "entry": entry,
            "sl": sl,
            "tp1": entry + risk,
            "tp2": entry + risk * 2,
            "tp3": entry + risk * 3,
            "risk": risk,
            "rr": 3.0,
        }

    if direction == "SHORT":
        sl = recent_high

        if sl <= entry:
            return None

        risk = sl - entry

        if risk <= 0:
            return None

        return {
            "entry": entry,
            "sl": sl,
            "tp1": entry - risk,
            "tp2": entry - risk * 2,
            "tp3": entry - risk * 3,
            "risk": risk,
            "rr": 3.0,
        }

    return None


# ============================================================
# NO TRADE
# ============================================================

def no_trade_result(
    daily,
    h4,
    h1,
    score=0,
    quality="LOW",
    reason="NO_SETUP",
):
    return {
        "daily": daily,
        "4h": h4,
        "1h": h1,
        "direction": None,
        "ema": None,
        "bos": None,
        "pullback": False,
        "liquidity_sweep": False,
        "order_block": False,
        "breakout_retest": False,
        "sr_reversal": False,
        "confirmation": False,
        "entry": None,
        "sl": None,
        "tp1": None,
        "tp2": None,
        "tp3": None,
        "risk": None,
        "rr": None,
        "score": score,
        "quality": quality,
        "signal": "NO_TRADE",
        "reason": reason,
        "strategy_matches": [],
    }


# ============================================================
# MAIN SIGNAL ENGINE
# ============================================================

def generate_signal(daily_candles, h4_candles, h1_candles):

    if not daily_candles or not h4_candles or not h1_candles:
        return no_trade_result(
            "UNKNOWN",
            "UNKNOWN",
            "UNKNOWN",
            reason="INSUFFICIENT_DATA",
        )

    if len(h1_candles) < 50:
        return no_trade_result(
            get_structure_direction(daily_candles),
            get_structure_direction(h4_candles),
            get_structure_direction(h1_candles),
            reason="INSUFFICIENT_1H_DATA",
        )

    daily = get_structure_direction(daily_candles)
    h4 = get_structure_direction(h4_candles)
    h1 = get_structure_direction(h1_candles)

    if daily not in ("BULLISH", "BEARISH"):
        return no_trade_result(
            daily,
            h4,
            h1,
            reason="DAILY_NOT_CLEAR",
        )

    direction = "LONG" if daily == "BULLISH" else "SHORT"

    opposite = (
        "BEARISH"
        if direction == "LONG"
        else "BULLISH"
    )

    if h4 == opposite:
        return no_trade_result(
            daily,
            h4,
            h1,
            reason="4H_AGAINST_DAILY",
        )

    if h1 == opposite:
        return no_trade_result(
            daily,
            h4,
            h1,
            reason="1H_AGAINST_DIRECTION",
        )

    ema = ema_trend(h1)

    bos = detect_bos(h1)

    pullback = trend_pullback_signal(
        h1,
        direction,
    )

    liquidity_sweep = detect_liquidity_sweep(
        h1,
        direction,
    )

    order_block = detect_order_block(
        h1,
        direction,
    )

    breakout_retest = detect_breakout_retest(
        h1,
        direction,
    )

    sr_reversal = sr_reversal_signal(
        h1,
        direction,
    )

    confirmation = confirmation_candle(
        h1,
        direction,
    )

    main_setup = []

    if pullback:
        main_setup.append("TREND_PULLBACK")

    if breakout_retest:
        main_setup.append("BREAKOUT_RETEST")

    if liquidity_sweep:
        main_setup.append("LIQUIDITY_SWEEP")

    if order_block:
        main_setup.append("ORDER_BLOCK")

    if sr_reversal:
        main_setup.append("SR_REVERSAL")

    if not main_setup:
        return no_trade_result(
            daily,
            h4,
            h1,
            reason="NO_MAIN_SETUP",
        )

    score_data = calculate_signal_score(
        daily_trend=daily,
        h4_trend=h4,
        h1_trend=h1,
        direction=direction,
        ema=ema,
        main_setup=main_setup,
        bos=bos,
        confirmation=confirmation,
    )

    score = score_data["score"]
    quality = score_data["quality"]
    strategies = score_data["strategies"]

    if quality != "HIGH":
        return no_trade_result(
            daily,
            h4,
            h1,
            score=score,
            quality=quality,
            reason="QUALITY_NOT_HIGH",
        )

    if not confirmation:
        return no_trade_result(
            daily,
            h4,
            h1,
            score=score,
            quality=quality,
            reason="NO_CONFIRMATION",
        )

    levels = calculate_trade_levels(
        h1_candles,
        direction,
    )

    if not levels:
        return no_trade_result(
            daily,
            h4,
            h1,
            score=score,
            quality=quality,
            reason="INVALID_TRADE_LEVELS",
        )

    return {
        "daily": daily,
        "4h": h4,
        "1h": h1,
        "direction": direction,
        "ema": ema,
        "bos": bos,
        "pullback": pullback,
        "liquidity_sweep": liquidity_sweep,
        "order_block": order_block,
        "breakout_retest": breakout_retest,
        "sr_reversal": sr_reversal,
        "confirmation": confirmation,
        "entry": levels["entry"],
        "sl": levels["sl"],
        "tp1": levels["tp1"],
        "tp2": levels["tp2"],
        "tp3": levels["tp3"],
        "risk": levels["risk"],
        "rr": levels["rr"],
        "score": score,
        "quality": quality,
        "signal": direction,
        "reason": "HIGH_QUALITY_SETUP",
        "strategy_matches": strategies,
    }
