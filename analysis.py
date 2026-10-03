# ============================================================
# CryptoBot - Analysis Engine v10
#
# Main timeframe structure:
#   1H  = Main Direction
#   15M = Setup / Filter
#   5M  = Entry Confirmation
#
# Strategies:
#   1. TREND_FOLLOWING
#   2. PULLBACK
#   3. BREAKOUT
#   4. REVERSAL
#   5. RANGE_TRADING
#
# IMPORTANT:
#   - Only HIGH signals are active.
#   - Closed candles are used.
#   - HIGH cannot be created by score alone.
#   - SL / TP model intentionally kept compatible with v9.
# ============================================================

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


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


def candle_values(candle):
    """
    Supports common Toobit candle formats:
    [time, open, high, low, close, volume, ...]
    or dictionaries.
    """

    if isinstance(candle, dict):
        o = safe_float(
            candle.get("open", candle.get("o", candle.get("Open", 0)))
        )
        h = safe_float(
            candle.get("high", candle.get("h", candle.get("High", 0)))
        )
        l = safe_float(
            candle.get("low", candle.get("l", candle.get("Low", 0)))
        )
        c = safe_float(
            candle.get("close", candle.get("c", candle.get("Close", 0)))
        )
        v = safe_float(
            candle.get("volume", candle.get("v", candle.get("Volume", 0)))
        )
        return o, h, l, c, v

    if isinstance(candle, (list, tuple)) and len(candle) >= 5:
        o = safe_float(candle[1])
        h = safe_float(candle[2])
        l = safe_float(candle[3])
        c = safe_float(candle[4])
        v = safe_float(candle[5]) if len(candle) > 5 else 0.0
        return o, h, l, c, v

    return 0.0, 0.0, 0.0, 0.0, 0.0


def normalize_candles(candles):
    result = []

    if not isinstance(candles, list):
        return result

    for c in candles:
        o, h, l, close, v = candle_values(c)

        if h <= 0 or l <= 0 or close <= 0:
            continue

        if h < l:
            continue

        result.append({
            "open": o,
            "high": h,
            "low": l,
            "close": close,
            "volume": v,
        })

    return result


def closed(candles, count=1):
    """
    Remove the currently forming candle.

    The last candle from exchange data can still be open.
    Therefore all strategy calculations use candles[:-1].
    """

    c = normalize_candles(candles)

    if len(c) <= count:
        return c

    return c[:-count]


def candle_body(c):
    return abs(c["close"] - c["open"])


def candle_range(c):
    return max(c["high"] - c["low"], 1e-12)


def upper_wick(c):
    return c["high"] - max(c["open"], c["close"])


def lower_wick(c):
    return min(c["open"], c["close"]) - c["low"]


def bullish(c):
    return c["close"] > c["open"]


def bearish(c):
    return c["close"] < c["open"]


def body_ratio(c):
    return candle_body(c) / candle_range(c)


# ============================================================
# EMA
# ============================================================

def ema(values, period):
    values = [safe_float(x) for x in values if safe_float(x) > 0]

    if len(values) < period:
        return None

    multiplier = 2.0 / (period + 1.0)

    current = sum(values[:period]) / period

    for price in values[period:]:
        current = (price - current) * multiplier + current

    return current


def ema_direction(candles):
    c = closed(candles)

    if len(c) < 210:
        return "RANGE"

    closes = [x["close"] for x in c]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)

    if e20 is None or e50 is None or e200 is None:
        return "RANGE"

    last = closes[-1]

    if last > e20 > e50 > e200:
        return "BULLISH"

    if last < e20 < e50 < e200:
        return "BEARISH"

    return "RANGE"


# ============================================================
# RSI
# ============================================================

def calculate_rsi(candles, period=14):
    c = closed(candles)

    if len(c) < period + 2:
        return 50.0

    closes = [x["close"] for x in c]

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]

        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

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
    c = closed(candles)

    if len(c) < period + 2:
        return 0.0

    trs = []

    for i in range(1, len(c)):
        high = c[i]["high"]
        low = c[i]["low"]
        prev_close = c[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
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
    """
    Standard Wilder-style ADX.

    This replaces the old simplified DX calculation.
    """

    c = closed(candles)

    if len(c) < (period * 2) + 5:
        return 0.0

    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, len(c)):
        high = c[i]["high"]
        low = c[i]["low"]

        prev_high = c[i - 1]["high"]
        prev_low = c[i - 1]["low"]
        prev_close = c[i - 1]["close"]

        up_move = high - prev_high
        down_move = prev_low - low

        plus_dm = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0.0

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )

        tr_list.append(tr)
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    if len(tr_list) < period:
        return 0.0

    atr = sum(tr_list[:period])
    plus_dm = sum(plus_dm_list[:period])
    minus_dm = sum(minus_dm_list[:period])

    dx_values = []

    for i in range(period, len(tr_list)):
        atr = atr - (atr / period) + tr_list[i]
        plus_dm = plus_dm - (plus_dm / period) + plus_dm_list[i]
        minus_dm = minus_dm - (minus_dm / period) + minus_dm_list[i]

        if atr <= 0:
            continue

        plus_di = 100.0 * (plus_dm / atr)
        minus_di = 100.0 * (minus_dm / atr)

        denominator = plus_di + minus_di

        if denominator <= 0:
            dx = 0.0
        else:
            dx = 100.0 * abs(plus_di - minus_di) / denominator

        dx_values.append(dx)

    if len(dx_values) < period:
        return 0.0

    adx = sum(dx_values[:period]) / period

    for dx in dx_values[period:]:
        adx = ((adx * (period - 1)) + dx) / period

    return max(0.0, min(100.0, adx))


# ============================================================
# VOLUME
# ============================================================

def volume_spike(candles, multiplier=1.30, lookback=20):
    c = closed(candles)

    if len(c) < lookback + 2:
        return False

    current = c[-1]["volume"]

    previous = [
        x["volume"]
        for x in c[-lookback - 1:-1]
        if x["volume"] > 0
    ]

    if len(previous) < 10:
        return False

    average = sum(previous) / len(previous)

    if average <= 0:
        return False

    return current >= average * multiplier


# ============================================================
# MARKET STRUCTURE
# ============================================================

def swing_highs(candles, strength=2):
    c = closed(candles)

    highs = []

    for i in range(strength, len(c) - strength):
        current = c[i]["high"]

        left = [c[j]["high"] for j in range(i - strength, i)]
        right = [c[j]["high"] for j in range(i + 1, i + strength + 1)]

        if current > max(left) and current > max(right):
            highs.append((i, current))

    return highs


def swing_lows(candles, strength=2):
    c = closed(candles)

    lows = []

    for i in range(strength, len(c) - strength):
        current = c[i]["low"]

        left = [c[j]["low"] for j in range(i - strength, i)]
        right = [c[j]["low"] for j in range(i + 1, i + strength + 1)]

        if current < min(left) and current < min(right):
            lows.append((i, current))

    return lows


def market_structure(candles):
    c = closed(candles)

    highs = swing_highs(c, 2)
    lows = swing_lows(c, 2)

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
    adx = calculate_adx(candles)

    if adx >= 30:
        return "STRONG"

    if adx >= 22:
        return "MODERATE"

    return "WEAK"


# ============================================================
# MTF CONFIRMATION
# ============================================================

def mtf_confirmation(m15, direction):
    if direction not in ("LONG", "SHORT"):
        return False

    c = closed(m15)

    if len(c) < 10:
        return False

    structure = market_structure(c)

    ema_dir = ema_direction(c)

    if direction == "LONG":
        return structure == "BULLISH" and ema_dir == "BULLISH"

    return structure == "BEARISH" and ema_dir == "BEARISH"


# ============================================================
# 5M ENTRY CONFIRMATION
# ============================================================

def entry_trigger(m5, direction):
    """
    Stronger confirmation.

    We require:
      1. last closed candle agrees with direction
      2. candle has meaningful body
      3. previous candle is not strongly against the setup
      4. recent micro-structure agrees
    """

    c = closed(m5)

    if len(c) < 8:
        return False

    last = c[-1]
    prev = c[-2]

    if body_ratio(last) < 0.50:
        return False

    if direction == "LONG":
        if not bullish(last):
            return False

        if bearish(prev) and body_ratio(prev) > 0.70:
            return False

        recent_high = max(x["high"] for x in c[-6:-1])

        if last["close"] < recent_high:
            return False

        return True

    if direction == "SHORT":
        if not bearish(last):
            return False

        if bullish(prev) and body_ratio(prev) > 0.70:
            return False

        recent_low = min(x["low"] for x in c[-6:-1])

        if last["close"] > recent_low:
            return False

        return True

    return False


# ============================================================
# REJECTION CANDLE
# ============================================================

def rejection_candle(c, direction):
    if not c:
        return False

    last = c[-1]

    rng = candle_range(last)
    body = candle_body(last)

    if rng <= 0:
        return False

    if direction == "LONG":
        return (
            lower_wick(last) >= body * 1.2
            and last["close"] >= last["low"] + rng * 0.55
        )

    if direction == "SHORT":
        return (
            upper_wick(last) >= body * 1.2
            and last["close"] <= last["high"] - rng * 0.55
        )

    return False


# ============================================================
# TREND FOLLOWING
# ============================================================

def detect_trend_following(h1, m15, m5):
    h1_structure = market_structure(h1)
    h1_ema = ema_direction(h1)

    if h1_structure not in ("BULLISH", "BEARISH"):
        return None

    if h1_structure != h1_ema:
        return None

    direction = "LONG" if h1_structure == "BULLISH" else "SHORT"

    adx = calculate_adx(h1)

    if adx < 22:
        return None

    if not mtf_confirmation(m15, direction):
        return None

    if not entry_trigger(m5, direction):
        return None

    return {
        "direction": direction,
        "name": "TREND_FOLLOWING",
        "strength": "STRONG" if adx >= 30 else "MODERATE",
        "reason": "1H structure + EMA + ADX + 15M confirmation + 5M trigger",
    }


# ============================================================
# PULLBACK
# ============================================================

def detect_pullback(h1, m15, m5):
    h1_structure = market_structure(h1)
    h1_ema = ema_direction(h1)

    if h1_structure not in ("BULLISH", "BEARISH"):
        return None

    if h1_structure != h1_ema:
        return None

    direction = "LONG" if h1_structure == "BULLISH" else "SHORT"

    c = closed(h1)

    if len(c) < 60:
        return None

    closes = [x["close"] for x in c]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    if e20 is None or e50 is None:
        return None

    recent = c[-8:]

    touched_zone = False

    for x in recent:
        distance20 = abs(x["close"] - e20) / x["close"]
        distance50 = abs(x["close"] - e50) / x["close"]

        if min(distance20, distance50) <= 0.004:
            touched_zone = True
            break

    if not touched_zone:
        return None

    if not rejection_candle(recent, direction):
        return None

    if not mtf_confirmation(m15, direction):
        return None

    if not entry_trigger(m5, direction):
        return None

    return {
        "direction": direction,
        "name": "PULLBACK",
        "strength": "STRONG",
        "reason": "Trend + EMA pullback zone + rejection + 15M confirmation + 5M trigger",
    }


# ============================================================
# BREAKOUT
# ============================================================

def detect_breakout(m15, m5):
    c = closed(m15)

    if len(c) < 30:
        return None

    previous = c[-21:-1]
    last = c[-1]

    resistance = max(x["high"] for x in previous)
    support = min(x["low"] for x in previous)

    vol_ok = volume_spike(m15, 1.30, 20)

    if not vol_ok:
        return None

    body_ok = body_ratio(last) >= 0.55

    if last["close"] > resistance and body_ok:
        direction = "LONG"

        # Require breakout to hold above the broken level.
        if last["low"] < resistance:
            return None

        if not entry_trigger(m5, direction):
            return None

        return {
            "direction": direction,
            "name": "BREAKOUT",
            "strength": "STRONG",
            "reason": "15M breakout + volume + hold above resistance + 5M trigger",
        }

    if last["close"] < support and body_ok:
        direction = "SHORT"

        if last["high"] > support:
            return None

        if not entry_trigger(m5, direction):
            return None

        return {
            "direction": direction,
            "name": "BREAKOUT",
            "strength": "STRONG",
            "reason": "15M breakdown + volume + hold below support + 5M trigger",
        }

    return None


# ============================================================
# REVERSAL
# ============================================================

def detect_reversal(h1, m15, m5):
    c15 = closed(m15)

    if len(c15) < 30:
        return None

    previous = c15[-11:-1]
    last = c15[-1]

    local_high = max(x["high"] for x in previous)
    local_low = min(x["low"] for x in previous)

    # Bullish reversal:
    # sweep below local low + reclaim + strong close
    if last["low"] < local_low:
        reclaimed = last["close"] > local_low
        strong_close = bullish(last) and body_ratio(last) >= 0.50

        if reclaimed and strong_close:
            if entry_trigger(m5, "LONG"):
                return {
                    "direction": "LONG",
                    "name": "REVERSAL",
                    "strength": "STRONG",
                    "reason": "15M downside sweep + reclaim + bullish confirmation + 5M trigger",
                }

    # Bearish reversal:
    # sweep above local high + rejection + strong close
    if last["high"] > local_high:
        rejected = last["close"] < local_high
        strong_close = bearish(last) and body_ratio(last) >= 0.50

        if rejected and strong_close:
            if entry_trigger(m5, "SHORT"):
                return {
                    "direction": "SHORT",
                    "name": "REVERSAL",
                    "strength": "STRONG",
                    "reason": "15M upside sweep + rejection + bearish confirmation + 5M trigger",
                }

    return None


# ============================================================
# RANGE TRADING
# ============================================================

def detect_range(h1, m5):
    structure = market_structure(h1)
    adx = calculate_adx(h1)

    if structure != "RANGE":
        return None

    if adx > 22:
        return None

    c = closed(h1)

    if len(c) < 30:
        return None

    recent = c[-20:]

    range_high = max(x["high"] for x in recent)
    range_low = min(x["low"] for x in recent)

    current = recent[-1]

    width = range_high - range_low

    if width <= 0:
        return None

    position = (current["close"] - range_low) / width

    # Near range bottom -> LONG
    if position <= 0.20:
        if not rejection_candle(recent, "LONG"):
            return None

        if not entry_trigger(m5, "LONG"):
            return None

        return {
            "direction": "LONG",
            "name": "RANGE_TRADING",
            "strength": "MODERATE",
            "reason": "Low ADX + range low rejection + 5M confirmation",
        }

    # Near range top -> SHORT
    if position >= 0.80:
        if not rejection_candle(recent, "SHORT"):
            return None

        if not entry_trigger(m5, "SHORT"):
            return None

        return {
            "direction": "SHORT",
            "name": "RANGE_TRADING",
            "strength": "MODERATE",
            "reason": "Low ADX + range high rejection + 5M confirmation",
        }

    return None


# ============================================================
# CONTEXT FILTER
# ============================================================

def context_allows(daily, h4, direction, strategy):
    daily_dir = ema_direction(daily)
    h4_dir = ema_direction(h4)

    # Reversal and range are allowed to work against trend,
    # but only because they have their own confirmation.
    if strategy in ("REVERSAL", "RANGE_TRADING"):
        return True

    if direction == "LONG":
        if daily_dir == "BEARISH" and h4_dir == "BEARISH":
            return False

        if h4_dir == "BEARISH":
            return False

    if direction == "SHORT":
        if daily_dir == "BULLISH" and h4_dir == "BULLISH":
            return False

        if h4_dir == "BULLISH":
            return False

    return True


# ============================================================
# NEARBY SUPPORT / RESISTANCE
# ============================================================

def nearby_levels(candles):
    c = closed(candles)

    if len(c) < 30:
        return [], []

    highs = swing_highs(c, 2)
    lows = swing_lows(c, 2)

    resistances = [x[1] for x in highs[-10:]]
    supports = [x[1] for x in lows[-10:]]

    return supports, resistances


def target_reachable(entry, direction, tp, candles):
    supports, resistances = nearby_levels(candles)

    if direction == "LONG":
        blockers = [x for x in resistances if x > entry and x < tp]

        if blockers:
            return False

    if direction == "SHORT":
        blockers = [x for x in supports if x < entry and x > tp]

        if blockers:
            return False

    return True


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_trade_levels(direction, h1, m5):
    h1c = closed(h1)
    m5c = closed(m5)

    if len(h1c) < 30 or len(m5c) < 10:
        return None

    entry = m5c[-1]["close"]

    atr = calculate_atr(h1)

    if atr <= 0:
        return None

    lows = swing_lows(h1c, 2)
    highs = swing_highs(h1c, 2)

    if direction == "LONG":

        recent_lows = [x[1] for x in lows[-5:]]

        swing = min(recent_lows) if recent_lows else entry - atr

        sl = swing - atr * 0.35

        risk = entry - sl

        min_risk = atr * 1.20
        max_risk = atr * 3.00

        if risk < min_risk:
            risk = min_risk
            sl = entry - risk

        if risk > max_risk:
            return None

        tp1 = entry + risk * 1.50
        tp2 = entry + risk * 2.50
        tp3 = entry + risk * 3.00

    else:

        recent_highs = [x[1] for x in highs[-5:]]

        swing = max(recent_highs) if recent_highs else entry + atr

        sl = swing + atr * 0.35

        risk = sl - entry

        min_risk = atr * 1.20
        max_risk = atr * 3.00

        if risk < min_risk:
            risk = min_risk
            sl = entry + risk

        if risk > max_risk:
            return None

        tp1 = entry - risk * 1.50
        tp2 = entry - risk * 2.50
        tp3 = entry - risk * 3.00

    if entry <= 0 or risk <= 0:
        return None

    risk_percent = (risk / entry) * 100

    # Prevent extremely wide trades.
    if risk_percent > 3.5:
        return None

    # Basic target reachability.
    if not target_reachable(entry, direction, tp1, h1c):
        return None

    return {
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk": risk,
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
    daily_ema="RANGE",
    h4_ema="RANGE",
    h1_ema="RANGE",
    rsi_15m=50.0,
    adx_1h=0.0,
    adx_15m=0.0,
    mtf_confirmed=False,
    volume_spike_value=False,
    confirmation=False,
    strategies=None,
):
    return {
        "signal": "NO_TRADE",
        "direction": None,
        "quality": "LOW",
        "score": 0,

        "daily": daily,
        "4h": h4,
        "1h": h1,

        "daily_ema": daily_ema,
        "4h_ema": h4_ema,
        "1h_ema": h1_ema,

        "rsi_15m": round(rsi_15m, 2),
        "adx_1h": round(adx_1h, 2),
        "adx_15m": round(adx_15m, 2),

        "mtf_confirmed": mtf_confirmed,
        "volume_spike": volume_spike_value,
        "confirmation": confirmation,

        "strategies": strategies or [],
        "strategy_matches": [],
        "strategy": None,
        "strategy_details": {},

        "trend_following": False,
        "pullback": False,
        "breakout": False,
        "reversal": False,
        "range_trading": False,

        "entry": None,
        "sl": None,
        "tp1": None,
        "tp2": None,
        "tp3": None,
        "risk": None,
        "rr": None,

        "reason": reason,
    }


# ============================================================
# MAIN SIGNAL GENERATOR
# ============================================================

def generate_signal(daily, h4, h1, m15, m5):

    daily_c = closed(daily)
    h4_c = closed(h4)
    h1_c = closed(h1)
    m15_c = closed(m15)
    m5_c = closed(m5)

    if (
        len(daily_c) < 50
        or len(h4_c) < 50
        or len(h1_c) < 50
        or len(m15_c) < 30
        or len(m5_c) < 20
    ):
        return no_trade("INSUFFICIENT_DATA")

    daily_ema = ema_direction(daily_c)
    h4_ema = ema_direction(h4_c)
    h1_ema = ema_direction(h1_c)

    daily_structure = market_structure(daily_c)
    h4_structure = market_structure(h4_c)
    h1_structure = market_structure(h1_c)

    # Prefer structure when available.
    daily_dir = (
        daily_structure
        if daily_structure in ("BULLISH", "BEARISH")
        else daily_ema
    )

    h4_dir = (
        h4_structure
        if h4_structure in ("BULLISH", "BEARISH")
        else h4_ema
    )

    h1_dir = (
        h1_structure
        if h1_structure in ("BULLISH", "BEARISH")
        else h1_ema
    )

    rsi15 = calculate_rsi(m15_c)
    adx1 = calculate_adx(h1_c)
    adx15 = calculate_adx(m15_c)

    vol_spike = volume_spike(m15_c)

    matches = []

    # --------------------------------------------------------
    # STRATEGY DETECTION
    # --------------------------------------------------------

    trend = detect_trend_following(h1_c, m15_c, m5_c)

    if trend:
        matches.append(trend)

    pullback = detect_pullback(h1_c, m15_c, m5_c)

    if pullback:
        matches.append(pullback)

    breakout = detect_breakout(m15_c, m5_c)

    if breakout:
        matches.append(breakout)

    reversal = detect_reversal(h1_c, m15_c, m5_c)

    if reversal:
        matches.append(reversal)

    range_setup = detect_range(h1_c, m5_c)

    if range_setup:
        matches.append(range_setup)

    strategy_names = [x["name"] for x in matches]

    # --------------------------------------------------------
    # NO VALID SETUP
    # --------------------------------------------------------

    if not matches:
        return no_trade(
            reason="NO_VALID_STRATEGY",
            daily=daily_dir,
            h4=h4_dir,
            h1=h1_dir,
            daily_ema=daily_ema,
            h4_ema=h4_ema,
            h1_ema=h1_ema,
            rsi_15m=rsi15,
            adx_1h=adx1,
            adx_15m=adx15,
            mtf_confirmed=False,
            volume_spike_value=vol_spike,
            confirmation=False,
            strategies=[],
        )

    # --------------------------------------------------------
    # SELECT STRATEGY
    # --------------------------------------------------------

    priority = {
        "REVERSAL": 5,
        "BREAKOUT": 4,
        "PULLBACK": 3,
        "TREND_FOLLOWING": 2,
        "RANGE_TRADING": 1,
    }

    matches.sort(
        key=lambda x: priority.get(x["name"], 0),
        reverse=True,
    )

    selected = matches[0]

    direction = selected["direction"]
    strategy = selected["name"]

    # --------------------------------------------------------
    # CONTEXT FILTER
    # --------------------------------------------------------

    if not context_allows(
        daily_c,
        h4_c,
        direction,
        strategy,
    ):
        return no_trade(
            reason="4H_OPPOSITE_TREND",
            daily=daily_dir,
            h4=h4_dir,
            h1=h1_dir,
            daily_ema=daily_ema,
            h4_ema=h4_ema,
            h1_ema=h1_ema,
            rsi_15m=rsi15,
            adx_1h=adx1,
            adx_15m=adx15,
            mtf_confirmed=mtf_confirmation(m15_c, direction),
            volume_spike_value=vol_spike,
            confirmation=entry_trigger(m5_c, direction),
            strategies=strategy_names,
        )

    # --------------------------------------------------------
    # STRICT HIGH REQUIREMENTS
    # --------------------------------------------------------

    mtf_ok = mtf_confirmation(m15_c, direction)
    trigger_ok = entry_trigger(m5_c, direction)

    # Every HIGH setup needs actual 5M confirmation.
    if not trigger_ok:
        return no_trade(
            reason="NO_5M_CONFIRMATION",
            daily=daily_dir,
            h4=h4_dir,
            h1=h1_dir,
            daily_ema=daily_ema,
            h4_ema=h4_ema,
            h1_ema=h1_ema,
            rsi_15m=rsi15,
            adx_1h=adx1,
            adx_15m=adx15,
            mtf_confirmed=mtf_ok,
            volume_spike_value=vol_spike,
            confirmation=False,
            strategies=strategy_names,
        )

    # Trend/pullback need MTF confirmation.
    if strategy in ("TREND_FOLLOWING", "PULLBACK"):
        if not mtf_ok:
            return no_trade(
                reason="NO_MTF_CONFIRMATION",
                daily=daily_dir,
                h4=h4_dir,
                h1=h1_dir,
                daily_ema=daily_ema,
                h4_ema=h4_ema,
                h1_ema=h1_ema,
                rsi_15m=rsi15,
                adx_1h=adx1,
                adx_15m=adx15,
                mtf_confirmed=False,
                volume_spike_value=vol_spike,
                confirmation=trigger_ok,
                strategies=strategy_names,
            )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    # Strategy quality
    if strategy == "REVERSAL":
        score += 4
    elif strategy == "BREAKOUT":
        score += 4
    elif strategy == "PULLBACK":
        score += 4
    elif strategy == "TREND_FOLLOWING":
        score += 3
    elif strategy == "RANGE_TRADING":
        score += 3

    # Extra strategy confluence
    if len(matches) >= 2:
        score += 2

    if len(matches) >= 3:
        score += 1

    # 5M confirmation
    if trigger_ok:
        score += 2

    # MTF confirmation
    if mtf_ok:
        score += 2

    # ADX context
    if adx1 >= 30:
        score += 2
    elif adx1 >= 22:
        score += 1

    # Volume
    if vol_spike:
        score += 1

    # RSI sanity filter
    if direction == "LONG":
        if rsi15 > 78:
            return no_trade(
                reason="RSI_TOO_EXTENDED",
                daily=daily_dir,
                h4=h4_dir,
                h1=h1_dir,
                daily_ema=daily_ema,
                h4_ema=h4_ema,
                h1_ema=h1_ema,
                rsi_15m=rsi15,
                adx_1h=adx1,
                adx_15m=adx15,
                mtf_confirmed=mtf_ok,
                volume_spike_value=vol_spike,
                confirmation=trigger_ok,
                strategies=strategy_names,
            )

    if direction == "SHORT":
        if rsi15 < 22:
            return no_trade(
                reason="RSI_TOO_EXTENDED",
                daily=daily_dir,
                h4=h4_dir,
                h1=h1_dir,
                daily_ema=daily_ema,
                h4_ema=h4_ema,
                h1_ema=h1_ema,
                rsi_15m=rsi15,
                adx_1h=adx1,
                adx_15m=adx15,
                mtf_confirmed=mtf_ok,
                volume_spike_value=vol_spike,
                confirmation=trigger_ok,
                strategies=strategy_names,
            )

    # --------------------------------------------------------
    # IMPORTANT:
    # SCORE ALONE CANNOT CREATE HIGH.
    # --------------------------------------------------------

    valid_high_setup = False

    if strategy == "TREND_FOLLOWING":
        valid_high_setup = (
            h1_dir in ("BULLISH", "BEARISH")
            and h1_dir == ("BULLISH" if direction == "LONG" else "BEARISH")
            and mtf_ok
            and trigger_ok
            and adx1 >= 22
            and len(matches) >= 2
        )

    elif strategy == "PULLBACK":
        valid_high_setup = (
            mtf_ok
            and trigger_ok
            and len(matches) >= 1
            and adx1 >= 20
        )

    elif strategy == "BREAKOUT":
        valid_high_setup = (
            trigger_ok
            and vol_spike
            and len(matches) >= 1
        )

    elif strategy == "REVERSAL":
        valid_high_setup = (
            trigger_ok
            and len(matches) >= 1
        )

    elif strategy == "RANGE_TRADING":
        valid_high_setup = (
            trigger_ok
            and adx1 <= 22
        )

    if not valid_high_setup:
        return no_trade(
            reason="SETUP_NOT_STRONG_ENOUGH",
            daily=daily_dir,
            h4=h4_dir,
            h1=h1_dir,
            daily_ema=daily_ema,
            h4_ema=h4_ema,
            h1_ema=h1_ema,
            rsi_15m=rsi15,
            adx_1h=adx1,
            adx_15m=adx15,
            mtf_confirmed=mtf_ok,
            volume_spike_value=vol_spike,
            confirmation=trigger_ok,
            strategies=strategy_names,
        )

    # --------------------------------------------------------
    # HIGH THRESHOLD
    # --------------------------------------------------------

    if score < 11:
        return no_trade(
            reason="SIGNAL_QUALITY_TOO_LOW",
            daily=daily_dir,
            h4=h4_dir,
            h1=h1_dir,
            daily_ema=daily_ema,
            h4_ema=h4_ema,
            h1_ema=h1_ema,
            rsi_15m=rsi15,
            adx_1h=adx1,
            adx_15m=adx15,
            mtf_confirmed=mtf_ok,
            volume_spike_value=vol_spike,
            confirmation=trigger_ok,
            strategies=strategy_names,
        )

    # --------------------------------------------------------
    # TRADE LEVELS
    # --------------------------------------------------------

    levels = calculate_trade_levels(
        direction,
        h1_c,
        m5_c,
    )

    if not levels:
        return no_trade(
            reason="INVALID_TRADE_LEVELS",
            daily=daily_dir,
            h4=h4_dir,
            h1=h1_dir,
            daily_ema=daily_ema,
            h4_ema=h4_ema,
            h1_ema=h1_ema,
            rsi_15m=rsi15,
            adx_1h=adx1,
            adx_15m=adx15,
            mtf_confirmed=mtf_ok,
            volume_spike_value=vol_spike,
            confirmation=trigger_ok,
            strategies=strategy_names,
        )

    # --------------------------------------------------------
    # FINAL HIGH SIGNAL
    # --------------------------------------------------------

    strategy_details = {}

    for item in matches:
        strategy_details[item["name"]] = item["reason"]

    return {
        "signal": direction,
        "direction": direction,

        "quality": "HIGH",
        "score": score,

        "daily": daily_dir,
        "4h": h4_dir,
        "1h": h1_dir,

        "daily_ema": daily_ema,
        "4h_ema": h4_ema,
        "1h_ema": h1_ema,

        "rsi_15m": round(rsi15, 2),
        "adx_1h": round(adx1, 2),
        "adx_15m": round(adx15, 2),

        "mtf_confirmed": mtf_ok,
        "volume_spike": vol_spike,
        "confirmation": trigger_ok,

        "strategies": strategy_names,
        "strategy_matches": strategy_names,
        "strategy": strategy,

        "strategy_details": strategy_details,

        "trend_following": "TREND_FOLLOWING" in strategy_names,
        "pullback": "PULLBACK" in strategy_names,
        "breakout": "BREAKOUT" in strategy_names,
        "reversal": "REVERSAL" in strategy_names,
        "range_trading": "RANGE_TRADING" in strategy_names,

        "entry": levels["entry"],
        "sl": levels["sl"],
        "tp1": levels["tp1"],
        "tp2": levels["tp2"],
        "tp3": levels["tp3"],

        "risk": levels["risk"],
        "rr": levels["rr"],

        "reason": selected["reason"],
    }
