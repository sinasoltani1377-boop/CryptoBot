# ============================================================
# CryptoBot - Analysis Engine v10
#
# 5 Strategies ONLY:
#   1. Trend Following
#   2. Pullback
#   3. Breakout
#   4. Reversal
#   5. Range Trading
#
# Timeframes:
#   1H  = Main structure / direction
#   15M = Setup confirmation
#   5M  = Entry trigger
#
# IMPORTANT:
#   - Only HIGH signals are active
#   - No score-only HIGH
#   - Closed candles only
#   - Strong confirmation required
#   - SL/TP calculation kept compatible with previous version
# ============================================================

from __future__ import annotations

from typing import Any, Dict, List, Optional
import math


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        x = float(value)
        if not math.isfinite(x):
            return default
        return x
    except Exception:
        return default


def candle_values(c):
    if isinstance(c, dict):
        o = safe_float(c.get("open", c.get("o")))
        h = safe_float(c.get("high", c.get("h")))
        l = safe_float(c.get("low", c.get("l")))
        cl = safe_float(c.get("close", c.get("c")))
        v = safe_float(c.get("volume", c.get("v")))
        return o, h, l, cl, v

    if isinstance(c, (list, tuple)) and len(c) >= 5:
        return (
            safe_float(c[0]),
            safe_float(c[1]),
            safe_float(c[2]),
            safe_float(c[3]),
            safe_float(c[4]),
        )

    return 0.0, 0.0, 0.0, 0.0, 0.0


def normalize_candles(candles):
    if not candles:
        return []

    result = []

    for c in candles:
        o, h, l, cl, v = candle_values(c)

        if h <= 0 or l <= 0 or cl <= 0:
            continue

        if h < l:
            continue

        result.append({
            "open": o,
            "high": h,
            "low": l,
            "close": cl,
            "volume": v,
        })

    return result


def closed_candles(candles):
    """
    Remove the currently forming candle.
    """
    candles = normalize_candles(candles)

    if len(candles) <= 2:
        return candles

    return candles[:-1]


def candle_body(c):
    o, h, l, cl, v = candle_values(c)
    return abs(cl - o)


def candle_range(c):
    o, h, l, cl, v = candle_values(c)
    return max(h - l, 0.0)


def upper_wick(c):
    o, h, l, cl, v = candle_values(c)
    return max(h - max(o, cl), 0.0)


def lower_wick(c):
    o, h, l, cl, v = candle_values(c)
    return max(min(o, cl) - l, 0.0)


# ============================================================
# EMA
# ============================================================

def ema(values, period):
    values = [safe_float(x) for x in values if safe_float(x) > 0]

    if len(values) < period:
        return None

    multiplier = 2.0 / (period + 1.0)

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (price - result) * multiplier + result

    return result


def ema_direction(candles):
    candles = closed_candles(candles)

    if len(candles) < 60:
        return "RANGE"

    closes = [c["close"] for c in candles]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    if e20 is None or e50 is None:
        return "RANGE"

    last = closes[-1]

    if last > e20 > e50:
        return "BULLISH"

    if last < e20 < e50:
        return "BEARISH"

    return "RANGE"


# ============================================================
# RSI
# ============================================================

def calculate_rsi(candles, period=14):
    candles = closed_candles(candles)

    if len(candles) < period + 2:
        return 50.0

    closes = [c["close"] for c in candles]

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):
    candles = closed_candles(candles)

    if len(candles) < period + 2:
        return 0.0

    trs = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        )

        trs.append(tr)

    if len(trs) < period:
        return 0.0

    atr = sum(trs[:period]) / period

    for tr in trs[period:]:
        atr = ((atr * (period - 1)) + tr) / period

    return atr


# ============================================================
# STANDARD WILDER ADX
# ============================================================

def calculate_adx(candles, period=14):
    candles = closed_candles(candles)

    if len(candles) < (period * 2) + 2:
        return 0.0

    tr_list = []
    plus_dm = []
    minus_dm = []

    for i in range(1, len(candles)):
        cur = candles[i]
        prev = candles[i - 1]

        high_diff = cur["high"] - prev["high"]
        low_diff = prev["low"] - cur["low"]

        if high_diff > low_diff and high_diff > 0:
            pdm = high_diff
        else:
            pdm = 0.0

        if low_diff > high_diff and low_diff > 0:
            mdm = low_diff
        else:
            mdm = 0.0

        tr = max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]),
        )

        tr_list.append(tr)
        plus_dm.append(pdm)
        minus_dm.append(mdm)

    if len(tr_list) < period:
        return 0.0

    atr = sum(tr_list[:period])
    p_dm = sum(plus_dm[:period])
    m_dm = sum(minus_dm[:period])

    dx_values = []

    for i in range(period, len(tr_list)):
        atr = atr - (atr / period) + tr_list[i]
        p_dm = p_dm - (p_dm / period) + plus_dm[i]
        m_dm = m_dm - (m_dm / period) + minus_dm[i]

        if atr <= 0:
            continue

        plus_di = 100.0 * (p_dm / atr)
        minus_di = 100.0 * (m_dm / atr)

        denominator = plus_di + minus_di

        if denominator <= 0:
            continue

        dx = 100.0 * abs(plus_di - minus_di) / denominator

        dx_values.append(dx)

    if len(dx_values) < period:
        return 0.0

    adx = sum(dx_values[:period]) / period

    for dx in dx_values[period:]:
        adx = ((adx * (period - 1)) + dx) / period

    return round(adx, 2)


# ============================================================
# VOLUME
# ============================================================

def volume_spike(candles, multiplier=1.30):
    candles = closed_candles(candles)

    if len(candles) < 25:
        return False

    current_volume = candles[-1]["volume"]

    previous_volumes = [
        c["volume"]
        for c in candles[-21:-1]
        if c["volume"] > 0
    ]

    if not previous_volumes:
        return False

    avg_volume = sum(previous_volumes) / len(previous_volumes)

    return current_volume >= avg_volume * multiplier


# ============================================================
# MARKET STRUCTURE
# ============================================================

def swing_highs(candles, strength=2):
    candles = closed_candles(candles)

    result = []

    if len(candles) < strength * 2 + 1:
        return result

    for i in range(strength, len(candles) - strength):
        high = candles[i]["high"]

        left = [
            candles[j]["high"]
            for j in range(i - strength, i)
        ]

        right = [
            candles[j]["high"]
            for j in range(i + 1, i + strength + 1)
        ]

        if high > max(left) and high >= max(right):
            result.append((i, high))

    return result


def swing_lows(candles, strength=2):
    candles = closed_candles(candles)

    result = []

    if len(candles) < strength * 2 + 1:
        return result

    for i in range(strength, len(candles) - strength):
        low = candles[i]["low"]

        left = [
            candles[j]["low"]
            for j in range(i - strength, i)
        ]

        right = [
            candles[j]["low"]
            for j in range(i + 1, i + strength + 1)
        ]

        if low < min(left) and low <= min(right):
            result.append((i, low))

    return result


def market_structure(candles):
    candles = closed_candles(candles)

    highs = swing_highs(candles)
    lows = swing_lows(candles)

    if len(highs) < 2 or len(lows) < 2:
        return "RANGE"

    h1 = highs[-2][1]
    h2 = highs[-1][1]

    l1 = lows[-2][1]
    l2 = lows[-1][1]

    if h2 > h1 and l2 > l1:
        return "BULLISH"

    if h2 < h1 and l2 < l1:
        return "BEARISH"

    return "RANGE"


# ============================================================
# TREND STRENGTH
# ============================================================

def trend_strength(candles):
    candles = closed_candles(candles)

    if len(candles) < 60:
        return "WEAK"

    adx = calculate_adx(candles)

    if adx >= 25:
        return "STRONG"

    if adx >= 18:
        return "MODERATE"

    return "WEAK"


# ============================================================
# MTF CONFIRMATION
# ============================================================

def mtf_confirmation(m15, direction):
    m15 = closed_candles(m15)

    if len(m15) < 25:
        return False

    structure = market_structure(m15)
    ema_dir = ema_direction(m15)

    if direction == "LONG":
        return (
            structure == "BULLISH"
            and ema_dir == "BULLISH"
        )

    if direction == "SHORT":
        return (
            structure == "BEARISH"
            and ema_dir == "BEARISH"
        )

    return False


# ============================================================
# 5M CONFIRMATION
# ============================================================

def confirmation_trigger(m5, direction):
    candles = closed_candles(m5)

    if len(candles) < 8:
        return False

    a = candles[-1]
    b = candles[-2]

    body_a = candle_body(a)
    range_a = candle_range(a)

    body_b = candle_body(b)
    range_b = candle_range(b)

    if range_a <= 0 or range_b <= 0:
        return False

    strong_a = body_a / range_a >= 0.55
    strong_b = body_b / range_b >= 0.40

    if direction == "LONG":
        bullish_a = a["close"] > a["open"]
        bullish_b = b["close"] > b["open"]

        structure_break = a["close"] > b["high"]

        return (
            bullish_a
            and strong_a
            and bullish_b
            and strong_b
            and structure_break
        )

    if direction == "SHORT":
        bearish_a = a["close"] < a["open"]
        bearish_b = b["close"] < b["open"]

        structure_break = a["close"] < b["low"]

        return (
            bearish_a
            and strong_a
            and bearish_b
            and strong_b
            and structure_break
        )

    return False


# ============================================================
# REJECTION CANDLE
# ============================================================

def bullish_rejection(c):
    body = candle_body(c)
    lower = lower_wick(c)
    rng = candle_range(c)

    if rng <= 0:
        return False

    return (
        c["close"] > c["open"]
        and lower >= body * 1.2
        and lower / rng >= 0.30
    )


def bearish_rejection(c):
    body = candle_body(c)
    upper = upper_wick(c)
    rng = candle_range(c)

    if rng <= 0:
        return False

    return (
        c["close"] < c["open"]
        and upper >= body * 1.2
        and upper / rng >= 0.30
    )


# ============================================================
# TREND FOLLOWING
# ============================================================

def detect_trend_following(h1, m15, m5, direction):
    if direction not in ("LONG", "SHORT"):
        return False

    h1 = closed_candles(h1)

    if len(h1) < 60:
        return False

    structure = market_structure(h1)
    ema_dir = ema_direction(h1)

    if direction == "LONG":
        if structure != "BULLISH" or ema_dir != "BULLISH":
            return False

    if direction == "SHORT":
        if structure != "BEARISH" or ema_dir != "BEARISH":
            return False

    if not mtf_confirmation(m15, direction):
        return False

    if not confirmation_trigger(m5, direction):
        return False

    return True


# ============================================================
# PULLBACK
# ============================================================

def detect_pullback(h1, m15, m5, direction):
    if direction not in ("LONG", "SHORT"):
        return False

    h1 = closed_candles(h1)

    if len(h1) < 60:
        return False

    structure = market_structure(h1)
    ema_dir = ema_direction(h1)

    if direction == "LONG":
        if structure != "BULLISH" or ema_dir != "BULLISH":
            return False
    else:
        if structure != "BEARISH" or ema_dir != "BEARISH":
            return False

    closes = [c["close"] for c in h1]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    if e20 is None or e50 is None:
        return False

    recent = h1[-6:]

    zone_touch = False

    for c in recent:
        low = c["low"]
        high = c["high"]

        if direction == "LONG":
            if low <= e20 * 1.004 or low <= e50 * 1.004:
                zone_touch = True

        else:
            if high >= e20 * 0.996 or high >= e50 * 0.996:
                zone_touch = True

    if not zone_touch:
        return False

    last = h1[-1]

    if direction == "LONG":
        rejection = bullish_rejection(last)
    else:
        rejection = bearish_rejection(last)

    if not rejection:
        return False

    if not mtf_confirmation(m15, direction):
        return False

    if not confirmation_trigger(m5, direction):
        return False

    return True


# ============================================================
# BREAKOUT
# ============================================================

def detect_breakout(m15, m5, direction):
    m15 = closed_candles(m15)

    if len(m15) < 30:
        return False

    previous = m15[-21:-1]

    highest = max(c["high"] for c in previous)
    lowest = min(c["low"] for c in previous)

    last = m15[-1]
    previous_candle = m15[-2]

    body = candle_body(last)
    rng = candle_range(last)

    if rng <= 0:
        return False

    strong_close = body / rng >= 0.60

    vol_ok = volume_spike(m15, 1.30)

    if direction == "LONG":
        broke = last["close"] > highest

        if not broke:
            return False

        if not strong_close or not vol_ok:
            return False

        # Hold above breakout level.
        if last["close"] < highest:
            return False

        # 5M must confirm continuation.
        if not confirmation_trigger(m5, "LONG"):
            return False

        return True

    if direction == "SHORT":
        broke = last["close"] < lowest

        if not broke:
            return False

        if not strong_close or not vol_ok:
            return False

        if last["close"] > lowest:
            return False

        if not confirmation_trigger(m5, "SHORT"):
            return False

        return True

    return False


# ============================================================
# REVERSAL
# ============================================================

def detect_reversal(m15, m5):
    m15 = closed_candles(m15)

    if len(m15) < 30:
        return None

    highs = swing_highs(m15)
    lows = swing_lows(m15)

    last = m15[-1]

    # --------------------------------------------------------
    # Bullish reversal:
    # sweep previous swing low -> close back above -> 5M shift
    # --------------------------------------------------------

    if lows:
        previous_low = lows[-1][1]

        swept = last["low"] < previous_low
        recovered = last["close"] > previous_low

        if swept and recovered and bullish_rejection(last):
            if confirmation_trigger(m5, "LONG"):
                return "LONG"

    # --------------------------------------------------------
    # Bearish reversal:
    # sweep previous swing high -> close back below -> 5M shift
    # --------------------------------------------------------

    if highs:
        previous_high = highs[-1][1]

        swept = last["high"] > previous_high
        recovered = last["close"] < previous_high

        if swept and recovered and bearish_rejection(last):
            if confirmation_trigger(m5, "SHORT"):
                return "SHORT"

    return None


# ============================================================
# RANGE TRADING
# ============================================================

def detect_range(h1, m5):
    h1 = closed_candles(h1)

    if len(h1) < 40:
        return None

    structure = market_structure(h1)
    adx = calculate_adx(h1)

    if structure != "RANGE":
        return None

    if adx > 22:
        return None

    recent = h1[-20:]

    range_high = max(c["high"] for c in recent)
    range_low = min(c["low"] for c in recent)

    width = range_high - range_low

    if width <= 0:
        return None

    last = h1[-1]
    position = (last["close"] - range_low) / width

    # Near lower boundary -> LONG
    if position <= 0.20:
        if bullish_rejection(last):
            if confirmation_trigger(m5, "LONG"):
                return "LONG"

    # Near upper boundary -> SHORT
    if position >= 0.80:
        if bearish_rejection(last):
            if confirmation_trigger(m5, "SHORT"):
                return "SHORT"

    return None


# ============================================================
# CONTEXT FILTER
# ============================================================

def context_allowed(daily, h4, h1, direction, strategy_names):
    strong_reversal = "REVERSAL" in strategy_names
    range_trade = "RANGE_TRADING" in strategy_names

    # Daily strong opposite trend.
    if direction == "LONG":
        if daily == "BEARISH" and h4 == "BEARISH":
            if not strong_reversal:
                return False, "DAILY_4H_OPPOSITE"

    if direction == "SHORT":
        if daily == "BULLISH" and h4 == "BULLISH":
            if not strong_reversal:
                return False, "DAILY_4H_OPPOSITE"

    # 4H direct opposition.
    if direction == "LONG" and h4 == "BEARISH":
        if not strong_reversal and not range_trade:
            return False, "4H_OPPOSITE_TREND"

    if direction == "SHORT" and h4 == "BULLISH":
        if not strong_reversal and not range_trade:
            return False, "4H_OPPOSITE_TREND"

    return True, "OK"


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_trade_levels(h1, m5, direction):
    h1 = closed_candles(h1)
    m5 = closed_candles(m5)

    if not h1 or not m5:
        return None

    entry = m5[-1]["close"]

    atr = calculate_atr(h1, 14)

    if atr <= 0:
        return None

    highs = swing_highs(h1)
    lows = swing_lows(h1)

    if direction == "LONG":

        candidates = [
            low
            for _, low in lows[-5:]
            if low < entry
        ]

        if candidates:
            swing_sl = min(candidates)
        else:
            swing_sl = entry - atr

        sl = swing_sl - atr * 0.35

        risk = entry - sl

        min_risk = atr * 1.20
        max_risk = atr * 3.00

        if risk < min_risk:
            risk = min_risk
            sl = entry - risk

        if risk > max_risk:
            risk = max_risk
            sl = entry - risk

        tp1 = entry + risk * 1.50
        tp2 = entry + risk * 2.50
        tp3 = entry + risk * 3.00

    else:

        candidates = [
            high
            for _, high in highs[-5:]
            if high > entry
        ]

        if candidates:
            swing_sl = max(candidates)
        else:
            swing_sl = entry + atr

        sl = swing_sl + atr * 0.35

        risk = sl - entry

        min_risk = atr * 1.20
        max_risk = atr * 3.00

        if risk < min_risk:
            risk = min_risk
            sl = entry + risk

        if risk > max_risk:
            risk = max_risk
            sl = entry + risk

        tp1 = entry - risk * 1.50
        tp2 = entry - risk * 2.50
        tp3 = entry - risk * 3.00

    if entry <= 0 or risk <= 0:
        return None

    risk_percent = abs(risk / entry) * 100

    # Keep extreme trades out.
    if risk_percent > 3.5:
        return None

    return {
        "entry": round(entry, 8),
        "sl": round(sl, 8),
        "tp1": round(tp1, 8),
        "tp2": round(tp2, 8),
        "tp3": round(tp3, 8),
        "risk": round(risk, 8),
        "rr": "1:3",
    }


# ============================================================
# NO TRADE
# ============================================================

def no_trade(
    reason="NO_VALID_STRATEGY",
    daily="RANGE",
    h4="RANGE",
    h1="RANGE",
    rsi_15m=50.0,
    adx_1h=0.0,
    adx_15m=0.0,
    mtf_confirmed=False,
    volume_spike_flag=False,
    confirmation=False,
    strategies=None,
    strategy_matches=None,
):
    strategies = strategies or []
    strategy_matches = strategy_matches or {}

    return {
        "signal": "NO_TRADE",
        "direction": None,
        "quality": "LOW",
        "score": 0,

        "daily": daily,
        "4h": h4,
        "1h": h1,

        "daily_ema": daily,
        "4h_ema": h4,
        "1h_ema": h1,

        "rsi_15m": round(rsi_15m, 2),
        "adx_1h": round(adx_1h, 2),
        "adx_15m": round(adx_15m, 2),

        "mtf_confirmed": bool(mtf_confirmed),
        "volume_spike": bool(volume_spike_flag),
        "confirmation": bool(confirmation),

        "strategies": strategies,
        "strategy_matches": strategy_matches,
        "strategy": None,
        "strategy_details": strategy_matches,

        "entry": None,
        "sl": None,
        "tp1": None,
        "tp2": None,
        "tp3": None,
        "risk": None,
        "rr": None,

        "reason": reason,

        "trend_following": bool(strategy_matches.get("TREND_FOLLOWING")),
        "pullback": bool(strategy_matches.get("PULLBACK")),
        "breakout": bool(strategy_matches.get("BREAKOUT")),
        "reversal": bool(strategy_matches.get("REVERSAL")),
        "range_trading": bool(strategy_matches.get("RANGE_TRADING")),
    }


# ============================================================
# MAIN SIGNAL GENERATOR
# ============================================================

def generate_signal(daily, h4, h1, m15, m5):

    daily = closed_candles(daily)
    h4 = closed_candles(h4)
    h1 = closed_candles(h1)
    m15 = closed_candles(m15)
    m5 = closed_candles(m5)

    if (
        len(daily) < 60
        or len(h4) < 60
        or len(h1) < 60
        or len(m15) < 30
        or len(m5) < 20
    ):
        return no_trade("INSUFFICIENT_DATA")

    # --------------------------------------------------------
    # MARKET CONTEXT
    # --------------------------------------------------------

    daily_structure = market_structure(daily)
    h4_structure = market_structure(h4)
    h1_structure = market_structure(h1)

    daily_ema = ema_direction(daily)
    h4_ema = ema_direction(h4)
    h1_ema = ema_direction(h1)

    # Main 1H direction.
    direction = None

    if (
        h1_structure == "BULLISH"
        and h1_ema == "BULLISH"
    ):
        direction = "LONG"

    elif (
        h1_structure == "BEARISH"
        and h1_ema == "BEARISH"
    ):
        direction = "SHORT"

    # --------------------------------------------------------
    # INDICATORS
    # --------------------------------------------------------

    rsi_15m = calculate_rsi(m15)
    adx_1h = calculate_adx(h1)
    adx_15m = calculate_adx(m15)

    vol_spike = volume_spike(m15)

    # --------------------------------------------------------
    # STRATEGY DETECTION
    # --------------------------------------------------------

    matches = {}

    if direction:
        matches["TREND_FOLLOWING"] = detect_trend_following(
            h1, m15, m5, direction
        )

        matches["PULLBACK"] = detect_pullback(
            h1, m15, m5, direction
        )

        matches["BREAKOUT"] = detect_breakout(
            m15, m5, direction
        )

    else:
        matches["TREND_FOLLOWING"] = False
        matches["PULLBACK"] = False
        matches["BREAKOUT"] = False

    reversal_direction = detect_reversal(m15, m5)

    matches["REVERSAL"] = reversal_direction is not None

    range_direction = detect_range(h1, m5)

    matches["RANGE_TRADING"] = range_direction is not None

    # --------------------------------------------------------
    # STRATEGY DIRECTION
    # --------------------------------------------------------

    if direction is None:

        if reversal_direction:
            direction = reversal_direction

        elif range_direction:
            direction = range_direction

    # No direction = no trade.
    if direction is None:
        return no_trade(
            "NO_VALID_STRATEGY",
            daily_structure,
            h4_structure,
            h1_structure,
            rsi_15m,
            adx_1h,
            adx_15m,
            False,
            vol_spike,
            False,
            [],
            matches,
        )

    # --------------------------------------------------------
    # STRATEGIES THAT ACTUALLY MATCH
    # --------------------------------------------------------

    matched = [
        name
        for name, value in matches.items()
        if value
    ]

    if not matched:
        return no_trade(
            "NO_VALID_STRATEGY",
            daily_structure,
            h4_structure,
            h1_structure,
            rsi_15m,
            adx_1h,
            adx_15m,
            False,
            vol_spike,
            False,
            [],
            matches,
        )

    # --------------------------------------------------------
    # CHECK 5M CONFIRMATION
    # --------------------------------------------------------

    confirmation = confirmation_trigger(m5, direction)

    # Reversal/range functions already require confirmation,
    # but keep a final global safety check.
    if not confirmation:
        return no_trade(
            "NO_5M_CONFIRMATION",
            daily_structure,
            h4_structure,
            h1_structure,
            rsi_15m,
            adx_1h,
            adx_15m,
            False,
            vol_spike,
            False,
            matched,
            matches,
        )

    # --------------------------------------------------------
    # 15M MTF CONFIRMATION
    # --------------------------------------------------------

    mtf = mtf_confirmation(m15, direction)

    # Trend/pullback require MTF.
    if (
        matches.get("TREND_FOLLOWING")
        or matches.get("PULLBACK")
    ):
        if not mtf:
            return no_trade(
                "NO_15M_MTF_CONFIRMATION",
                daily_structure,
                h4_structure,
                h1_structure,
                rsi_15m,
                adx_1h,
                adx_15m,
                mtf,
                vol_spike,
                confirmation,
                matched,
                matches,
            )

    # --------------------------------------------------------
    # CONTEXT FILTER
    # --------------------------------------------------------

    allowed, context_reason = context_allowed(
        daily_structure,
        h4_structure,
        h1_structure,
        direction,
        matched,
    )

    if not allowed:
        return no_trade(
            context_reason,
            daily_structure,
            h4_structure,
            h1_structure,
            rsi_15m,
            adx_1h,
            adx_15m,
            mtf,
            vol_spike,
            confirmation,
            matched,
            matches,
        )

    # --------------------------------------------------------
    # QUALITY REQUIREMENTS
    # --------------------------------------------------------

    # HIGH cannot come from one weak condition.
    #
    # Required:
    #   - at least one real strategy
    #   - confirmation
    #   - context
    #
    # Trend Following alone is NOT automatically HIGH.
    #

    strategy_count = len(matched)

    strong_strategy = any(
        x in matched
        for x in (
            "PULLBACK",
            "BREAKOUT",
            "REVERSAL",
            "RANGE_TRADING",
        )
    )

    # Trend-only needs stronger market agreement.
    trend_only_valid = (
        matched == ["TREND_FOLLOWING"]
        and mtf
        and confirmation
        and adx_1h >= 20
        and adx_15m >= 18
    )

    high_valid = False

    if strong_strategy:
        high_valid = (
            confirmation
            and (
                mtf
                or "REVERSAL" in matched
                or "RANGE_TRADING" in matched
            )
        )

    elif trend_only_valid:
        high_valid = True

    if not high_valid:
        return no_trade(
            "SETUP_NOT_STRONG_ENOUGH",
            daily_structure,
            h4_structure,
            h1_structure,
            rsi_15m,
            adx_1h,
            adx_15m,
            mtf,
            vol_spike,
            confirmation,
            matched,
            matches,
        )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    score += strategy_count * 3

    if mtf:
        score += 2

    if confirmation:
        score += 2

    if vol_spike:
        score += 1

    if adx_1h >= 25:
        score += 1

    if adx_15m >= 20:
        score += 1

    # Context alignment.
    if direction == "LONG":
        if daily_structure == "BULLISH":
            score += 1

        if h4_structure == "BULLISH":
            score += 1

    if direction == "SHORT":
        if daily_structure == "BEARISH":
            score += 1

        if h4_structure == "BEARISH":
            score += 1

    # --------------------------------------------------------
    # TRADE LEVELS
    # --------------------------------------------------------

    levels = calculate_trade_levels(
        h1,
        m5,
        direction,
    )

    if levels is None:
        return no_trade(
            "INVALID_TRADE_LEVELS",
            daily_structure,
            h4_structure,
            h1_structure,
            rsi_15m,
            adx_1h,
            adx_15m,
            mtf,
            vol_spike,
            confirmation,
            matched,
            matches,
        )

    # --------------------------------------------------------
    # FINAL HIGH
    # --------------------------------------------------------

    return {
        "signal": direction,
        "direction": direction,

        "quality": "HIGH",
        "score": score,

        "daily": daily_structure,
        "4h": h4_structure,
        "1h": h1_structure,

        "daily_ema": daily_ema,
        "4h_ema": h4_ema,
        "1h_ema": h1_ema,

        "rsi_15m": round(rsi_15m, 2),
        "adx_1h": round(adx_1h, 2),
        "adx_15m": round(adx_15m, 2),

        "mtf_confirmed": mtf,
        "volume_spike": vol_spike,
        "confirmation": confirmation,

        "strategies": matched,
        "strategy_matches": matches,
        "strategy": matched[0] if matched else None,
        "strategy_details": matches,

        "trend_following": matches.get(
            "TREND_FOLLOWING", False
        ),

        "pullback": matches.get(
            "PULLBACK", False
        ),

        "breakout": matches.get(
            "BREAKOUT", False
        ),

        "reversal": matches.get(
            "REVERSAL", False
        ),

        "range_trading": matches.get(
            "RANGE_TRADING", False
        ),

        "entry": levels["entry"],
        "sl": levels["sl"],
        "tp1": levels["tp1"],
        "tp2": levels["tp2"],
        "tp3": levels["tp3"],
        "risk": levels["risk"],
        "rr": levels["rr"],

        "reason": "VALID_HIGH_SETUP",
    }
