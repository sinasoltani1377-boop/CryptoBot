# ============================================================
# CryptoBot - Analysis Engine v12
#
# 1H  = Main Direction
# 15M = Setup / Filter
# 5M  = Entry Confirmation
#
# Strategies:
#   1. TREND_FOLLOWING
#   2. PULLBACK
#   3. BREAKOUT
#   4. REVERSAL
#   5. RANGE_TRADING
#
# v12:
#   - Keeps existing SL/TP model unchanged
#   - 1H direction can come from clear structure OR EMA alignment
#   - 15M confirmation is less brittle
#   - 5M confirmation accepts either micro-breakout or 2-candle shift
#   - Pullback checks the recent pullback zone instead of only last candle
#   - Breakout uses closed 15M candle + volume + hold
#   - HIGH requires a real strategy and confluence
#   - Reversal/Breakout are not incorrectly killed by every 4H conflict
#   - Diagnostics preserve the real candidate direction
#   - Exactly five strategies; old strategy names removed
# ============================================================

from __future__ import annotations

import math


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def candle_values(candle):
    if isinstance(candle, dict):
        return (
            safe_float(candle.get("open", candle.get("o", candle.get("Open", 0)))),
            safe_float(candle.get("high", candle.get("h", candle.get("High", 0)))),
            safe_float(candle.get("low", candle.get("l", candle.get("Low", 0)))),
            safe_float(candle.get("close", candle.get("c", candle.get("Close", 0)))),
            safe_float(candle.get("volume", candle.get("v", candle.get("Volume", 0)))),
        )

    if isinstance(candle, (list, tuple)) and len(candle) >= 5:
        return (
            safe_float(candle[1]),
            safe_float(candle[2]),
            safe_float(candle[3]),
            safe_float(candle[4]),
            safe_float(candle[5]) if len(candle) > 5 else 0.0,
        )

    return 0.0, 0.0, 0.0, 0.0, 0.0


def normalize_candles(candles):
    result = []
    if not isinstance(candles, list):
        return result

    for candle in candles:
        o, h, l, close, v = candle_values(candle)
        if h <= 0 or l <= 0 or close <= 0 or h < l:
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
        current = ((price - current) * multiplier) + current

    return current


def ema_direction(candles):
    c = normalize_candles(candles)
    if len(c) < 55:
        return "RANGE"

    closes = [x["close"] for x in c]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200)
    last = closes[-1]

    if e20 is None or e50 is None:
        return "RANGE"

    if e200 is not None:
        if last > e20 > e50 > e200:
            return "BULLISH"
        if last < e20 < e50 < e200:
            return "BEARISH"
        return "RANGE"

    if last > e20 > e50:
        return "BULLISH"
    if last < e20 < e50:
        return "BEARISH"
    return "RANGE"


# ============================================================
# RSI / ATR
# ============================================================

def calculate_rsi(candles, period=14):
    c = normalize_candles(candles)
    if len(c) < period + 2:
        return 50.0

    closes = [x["close"] for x in c]
    gains, losses = [], []

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


def calculate_atr(candles, period=14):
    c = normalize_candles(candles)
    if len(c) < period + 2:
        return 0.0

    trs = []
    for i in range(1, len(c)):
        high = c[i]["high"]
        low = c[i]["low"]
        prev_close = c[i - 1]["close"]
        trs.append(max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        ))

    if len(trs) < period:
        return 0.0

    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = ((atr * (period - 1)) + tr) / period
    return atr


# ============================================================
# WILDER ADX
# ============================================================

def calculate_adx(candles, period=14):
    c = normalize_candles(candles)
    if len(c) < (period * 2) + 5:
        return 0.0

    tr_list, plus_dm_list, minus_dm_list = [], [], []

    for i in range(1, len(c)):
        high = c[i]["high"]
        low = c[i]["low"]
        prev_high = c[i - 1]["high"]
        prev_low = c[i - 1]["low"]
        prev_close = c[i - 1]["close"]

        up_move = high - prev_high
        down_move = prev_low - low

        plus_dm_list.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm_list.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        tr_list.append(max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        ))

    if len(tr_list) < period * 2:
        return 0.0

    tr_sum = sum(tr_list[:period])
    plus_sum = sum(plus_dm_list[:period])
    minus_sum = sum(minus_dm_list[:period])

    dx_values = []

    for i in range(period, len(tr_list)):
        tr_sum = tr_sum - (tr_sum / period) + tr_list[i]
        plus_sum = plus_sum - (plus_sum / period) + plus_dm_list[i]
        minus_sum = minus_sum - (minus_sum / period) + minus_dm_list[i]

        if tr_sum <= 0:
            continue

        plus_di = 100.0 * plus_sum / tr_sum
        minus_di = 100.0 * minus_sum / tr_sum
        denominator = plus_di + minus_di

        dx_values.append(
            0.0 if denominator <= 0 else
            100.0 * abs(plus_di - minus_di) / denominator
        )

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
    c = normalize_candles(candles)
    if len(c) < lookback + 2:
        return False

    current = c[-1]["volume"]
    previous = [x["volume"] for x in c[-lookback - 1:-1] if x["volume"] > 0]
    if len(previous) < 10:
        return False

    average = sum(previous) / len(previous)
    return average > 0 and current >= average * multiplier


# ============================================================
# MARKET STRUCTURE
# ============================================================

def swing_highs(candles, strength=2):
    c = normalize_candles(candles)
    highs = []
    for i in range(strength, len(c) - strength):
        current = c[i]["high"]
        left = [c[j]["high"] for j in range(i - strength, i)]
        right = [c[j]["high"] for j in range(i + 1, i + strength + 1)]
        if current > max(left) and current > max(right):
            highs.append((i, current))
    return highs


def swing_lows(candles, strength=2):
    c = normalize_candles(candles)
    lows = []
    for i in range(strength, len(c) - strength):
        current = c[i]["low"]
        left = [c[j]["low"] for j in range(i - strength, i)]
        right = [c[j]["low"] for j in range(i + 1, i + strength + 1)]
        if current < min(left) and current < min(right):
            lows.append((i, current))
    return lows


def market_structure(candles):
    c = normalize_candles(candles)
    highs = swing_highs(c, 2)
    lows = swing_lows(c, 2)

    if len(highs) < 2 or len(lows) < 2:
        return "RANGE"

    h1, h2 = highs[-2][1], highs[-1][1]
    l1, l2 = lows[-2][1], lows[-1][1]

    if h2 > h1 and l2 > l1:
        return "BULLISH"
    if h2 < h1 and l2 < l1:
        return "BEARISH"
    return "RANGE"


def timeframe_direction(candles):
    structure = market_structure(candles)
    ema_dir = ema_direction(candles)

    if structure in ("BULLISH", "BEARISH"):
        return structure
    if ema_dir in ("BULLISH", "BEARISH"):
        return ema_dir
    return "RANGE"


def trend_strength(candles):
    adx = calculate_adx(candles)
    if adx >= 30:
        return "STRONG"
    if adx >= 22:
        return "MODERATE"
    return "WEAK"


# ============================================================
# 15M CONFIRMATION
# ============================================================

def mtf_confirmation(m15, direction):
    if direction not in ("LONG", "SHORT"):
        return False

    c = normalize_candles(m15)
    if len(c) < 30:
        return False

    ema_dir = ema_direction(c)
    structure = market_structure(c)
    last = c[-1]
    prev = c[-2]

    if direction == "LONG":
        context_ok = ema_dir == "BULLISH" or structure == "BULLISH"
        price_action_ok = (
            bullish(last)
            or (bullish(prev) and last["close"] >= prev["close"])
            or last["close"] > max(x["high"] for x in c[-6:-1])
        )
        return context_ok and price_action_ok

    context_ok = ema_dir == "BEARISH" or structure == "BEARISH"
    price_action_ok = (
        bearish(last)
        or (bearish(prev) and last["close"] <= prev["close"])
        or last["close"] < min(x["low"] for x in c[-6:-1])
    )
    return context_ok and price_action_ok


# ============================================================
# 5M ENTRY CONFIRMATION
# ============================================================

def entry_trigger(m5, direction):
    c = normalize_candles(m5)
    if len(c) < 10:
        return False

    last = c[-1]
    prev = c[-2]

    if body_ratio(last) < 0.35:
        return False

    if direction == "LONG":
        if not bullish(last):
            return False

        micro_high = max(x["high"] for x in c[-7:-1])
        breakout = last["close"] > micro_high

        two_candle_shift = (
            bullish(last)
            and bullish(prev)
            and last["close"] > prev["close"]
            and last["close"] > prev["high"] * 0.9995
            and body_ratio(last) >= 0.50
        )

        continuation = (
            bullish(last)
            and last["close"] > prev["high"]
            and body_ratio(last) >= 0.45
        )

        return breakout or two_candle_shift or continuation

    if direction == "SHORT":
        if not bearish(last):
            return False

        micro_low = min(x["low"] for x in c[-7:-1])
        breakdown = last["close"] < micro_low

        two_candle_shift = (
            bearish(last)
            and bearish(prev)
            and last["close"] < prev["close"]
            and last["close"] < prev["low"] * 1.0005
            and body_ratio(last) >= 0.50
        )

        continuation = (
            bearish(last)
            and last["close"] < prev["low"]
            and body_ratio(last) >= 0.45
        )

        return breakdown or two_candle_shift or continuation

    return False


# ============================================================
# REJECTION
# ============================================================

def rejection_candle(candles, direction):
    c = normalize_candles(candles)
    if not c:
        return False

    last = c[-1]
    rng = candle_range(last)
    body = candle_body(last)

    if direction == "LONG":
        return (
            lower_wick(last) >= max(body * 0.8, rng * 0.20)
            and last["close"] >= last["low"] + rng * 0.55
        )

    if direction == "SHORT":
        return (
            upper_wick(last) >= max(body * 0.8, rng * 0.20)
            and last["close"] <= last["high"] - rng * 0.55
        )

    return False


# ============================================================
# TREND FOLLOWING
# ============================================================

def detect_trend_following(h1, m15, m5):
    direction = timeframe_direction(h1)
    if direction not in ("LONG", "SHORT"):
        return None

    adx = calculate_adx(h1)
    if adx < 20:
        return None

    if not mtf_confirmation(m15, direction):
        return None

    if not entry_trigger(m5, direction):
        return None

    return {
        "direction": direction,
        "name": "TREND_FOLLOWING",
        "strength": "STRONG" if adx >= 30 else "MODERATE",
        "reason": "1H direction + ADX + 15M confirmation + 5M trigger",
    }


# ============================================================
# PULLBACK
# ============================================================

def detect_pullback(h1, m15, m5):
    direction = timeframe_direction(h1)
    if direction not in ("LONG", "SHORT"):
        return None

    c = normalize_candles(h1)
    if len(c) < 60:
        return None

    closes = [x["close"] for x in c]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    if e20 is None or e50 is None:
        return None

    recent = c[-10:]
    zone_touched = any(
        min(
            abs(x["close"] - e20) / x["close"],
            abs(x["close"] - e50) / x["close"],
        ) <= 0.008
        for x in recent
    )

    if not zone_touched:
        return None

    rejection_found = any(
        rejection_candle(recent[:i + 1], direction)
        for i in range(max(0, len(recent) - 4), len(recent))
    )

    if not rejection_found:
        return None

    if not mtf_confirmation(m15, direction):
        return None

    if not entry_trigger(m5, direction):
        return None

    return {
        "direction": direction,
        "name": "PULLBACK",
        "strength": "STRONG",
        "reason": "1H trend + EMA20/50 pullback zone + rejection + 15M + 5M confirmation",
    }


# ============================================================
# BREAKOUT
# ============================================================

def detect_breakout(m15, m5):
    c = normalize_candles(m15)
    if len(c) < 30:
        return None

    previous = c[-21:-1]
    last = c[-1]

    resistance = max(x["high"] for x in previous)
    support = min(x["low"] for x in previous)

    if not volume_spike(c, 1.25, 20):
        return None

    if body_ratio(last) < 0.45:
        return None

    if last["close"] > resistance:
        if not entry_trigger(m5, "LONG"):
            return None

        # A breakout that closes clearly above the level is preferred.
        hold_ok = last["close"] >= resistance * 1.0002
        if not hold_ok:
            return None

        return {
            "direction": "LONG",
            "name": "BREAKOUT",
            "strength": "STRONG",
            "reason": "15M resistance breakout + volume + hold + 5M trigger",
        }

    if last["close"] < support:
        if not entry_trigger(m5, "SHORT"):
            return None

        hold_ok = last["close"] <= support * 0.9998
        if not hold_ok:
            return None

        return {
            "direction": "SHORT",
            "name": "BREAKOUT",
            "strength": "STRONG",
            "reason": "15M support breakdown + volume + hold + 5M trigger",
        }

    return None


# ============================================================
# REVERSAL
# ============================================================

def detect_reversal(h1, m15, m5):
    c15 = normalize_candles(m15)
    if len(c15) < 30:
        return None

    previous = c15[-11:-1]
    last = c15[-1]

    local_high = max(x["high"] for x in previous)
    local_low = min(x["low"] for x in previous)

    if last["low"] < local_low:
        reclaimed = last["close"] > local_low
        strong_close = bullish(last) and body_ratio(last) >= 0.40
        if reclaimed and strong_close and entry_trigger(m5, "LONG"):
            return {
                "direction": "LONG",
                "name": "REVERSAL",
                "strength": "STRONG",
                "reason": "15M downside sweep + reclaim + bullish close + 5M trigger",
            }

    if last["high"] > local_high:
        rejected = last["close"] < local_high
        strong_close = bearish(last) and body_ratio(last) >= 0.40
        if rejected and strong_close and entry_trigger(m5, "SHORT"):
            return {
                "direction": "SHORT",
                "name": "REVERSAL",
                "strength": "STRONG",
                "reason": "15M upside sweep + rejection + bearish close + 5M trigger",
            }

    return None


# ============================================================
# RANGE TRADING
# ============================================================

def detect_range(h1, m5):
    structure = market_structure(h1)
    adx = calculate_adx(h1)

    if structure != "RANGE" or adx > 22:
        return None

    c = normalize_candles(h1)
    if len(c) < 30:
        return None

    recent = c[-20:]
    range_high = max(x["high"] for x in recent)
    range_low = min(x["low"] for x in recent)
    width = range_high - range_low

    if width <= 0:
        return None

    current = recent[-1]
    position = (current["close"] - range_low) / width

    if position <= 0.20:
        if rejection_candle(recent, "LONG") and entry_trigger(m5, "LONG"):
            return {
                "direction": "LONG",
                "name": "RANGE_TRADING",
                "strength": "MODERATE",
                "reason": "Low ADX + range low rejection + 5M confirmation",
            }

    if position >= 0.80:
        if rejection_candle(recent, "SHORT") and entry_trigger(m5, "SHORT"):
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
    daily_dir = timeframe_direction(daily)
    h4_dir = timeframe_direction(h4)

    if strategy == "RANGE_TRADING":
        return True

    if strategy == "REVERSAL":
        # Reversal is specifically allowed to oppose higher-timeframe trend,
        # but not when both higher timeframes strongly oppose the setup.
        if direction == "LONG" and daily_dir == "BEARISH" and h4_dir == "BEARISH":
            return False
        if direction == "SHORT" and daily_dir == "BULLISH" and h4_dir == "BULLISH":
            return False
        return True

    if strategy == "BREAKOUT":
        # A confirmed breakout can lead a higher-timeframe move. Require
        # 1H alignment rather than blindly rejecting every 4H conflict.
        h1_dir = timeframe_direction(h4)
        return True

    if direction == "LONG" and h4_dir == "BEARISH":
        return False
    if direction == "SHORT" and h4_dir == "BULLISH":
        return False

    return True


# ============================================================
# NEARBY SUPPORT / RESISTANCE
# ============================================================

def nearby_levels(candles):
    c = normalize_candles(candles)
    if len(c) < 30:
        return [], []

    highs = swing_highs(c, 2)
    lows = swing_lows(c, 2)
    return [x[1] for x in lows[-10:]], [x[1] for x in highs[-10:]]


def target_reachable(entry, direction, tp, candles):
    supports, resistances = nearby_levels(candles)

    if direction == "LONG":
        return not any(entry < x < tp for x in resistances)

    if direction == "SHORT":
        return not any(tp < x < entry for x in supports)

    return False


# ============================================================
# TRADE LEVELS
# NOTE: Same SL/TP model as v11/v9. Do not change here.
# ============================================================

def calculate_trade_levels(direction, h1, m5):
    h1c = normalize_candles(h1)
    m5c = normalize_candles(m5)

    if len(h1c) < 30 or len(m5c) < 10:
        return None

    entry = m5c[-1]["close"]
    atr = calculate_atr(h1c)
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

    elif direction == "SHORT":
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

    else:
        return None

    if entry <= 0 or risk <= 0:
        return None

    risk_percent = (risk / entry) * 100.0
    if risk_percent > 3.5:
        return None

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
    direction=None,
):
    return {
        "signal": "NO_TRADE",
        "direction": direction,
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

    daily_dir = timeframe_direction(daily_c)
    h4_dir = timeframe_direction(h4_c)
    h1_dir = timeframe_direction(h1_c)

    rsi15 = calculate_rsi(m15_c)
    adx1 = calculate_adx(h1_c)
    adx15 = calculate_adx(m15_c)
    vol_spike = volume_spike(m15_c)

    # The candidate direction is known from 1H even when no strategy has fired.
    candidate_direction = (
        "LONG" if h1_dir == "BULLISH"
        else "SHORT" if h1_dir == "BEARISH"
        else None
    )

    matches = []

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
            mtf_confirmed=(
                mtf_confirmation(m15_c, candidate_direction)
                if candidate_direction else False
            ),
            volume_spike_value=vol_spike,
            confirmation=(
                entry_trigger(m5_c, candidate_direction)
                if candidate_direction else False
            ),
            strategies=[],
            direction=candidate_direction,
        )

    priority = {
        "REVERSAL": 5,
        "BREAKOUT": 4,
        "PULLBACK": 3,
        "TREND_FOLLOWING": 2,
        "RANGE_TRADING": 1,
    }

    matches.sort(key=lambda x: priority.get(x["name"], 0), reverse=True)
    selected = matches[0]
    direction = selected["direction"]
    strategy = selected["name"]

    mtf_ok = mtf_confirmation(m15_c, direction)
    trigger_ok = entry_trigger(m5_c, direction)

    if not context_allows(daily_c, h4_c, direction, strategy):
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
            mtf_confirmed=mtf_ok,
            volume_spike_value=vol_spike,
            confirmation=trigger_ok,
            strategies=strategy_names,
            direction=direction,
        )

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
            direction=direction,
        )

    if strategy in ("TREND_FOLLOWING", "PULLBACK") and not mtf_ok:
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
            direction=direction,
        )

    if direction == "LONG" and rsi15 > 78:
        return no_trade(
            reason="RSI_TOO_EXTENDED", daily=daily_dir, h4=h4_dir, h1=h1_dir,
            daily_ema=daily_ema, h4_ema=h4_ema, h1_ema=h1_ema,
            rsi_15m=rsi15, adx_1h=adx1, adx_15m=adx15,
            mtf_confirmed=mtf_ok, volume_spike_value=vol_spike,
            confirmation=trigger_ok, strategies=strategy_names, direction=direction,
        )

    if direction == "SHORT" and rsi15 < 22:
        return no_trade(
            reason="RSI_TOO_EXTENDED", daily=daily_dir, h4=h4_dir, h1=h1_dir,
            daily_ema=daily_ema, h4_ema=h4_ema, h1_ema=h1_ema,
            rsi_15m=rsi15, adx_1h=adx1, adx_15m=adx15,
            mtf_confirmed=mtf_ok, volume_spike_value=vol_spike,
            confirmation=trigger_ok, strategies=strategy_names, direction=direction,
        )

    # --------------------------------------------------------
    # SCORE
    # Score supports quality; it does not create a strategy.
    # --------------------------------------------------------
    score = 0

    score += {
        "REVERSAL": 4,
        "BREAKOUT": 4,
        "PULLBACK": 4,
        "TREND_FOLLOWING": 3,
        "RANGE_TRADING": 3,
    }.get(strategy, 0)

    if len(matches) >= 2:
        score += 2
    if len(matches) >= 3:
        score += 1
    if trigger_ok:
        score += 2
    if mtf_ok:
        score += 2
    if adx1 >= 30:
        score += 2
    elif adx1 >= 22:
        score += 1
    if vol_spike:
        score += 1

    # --------------------------------------------------------
    # STRATEGY-SPECIFIC HIGH CONDITIONS
    # --------------------------------------------------------
    valid_high_setup = False

    if strategy == "TREND_FOLLOWING":
        valid_high_setup = (
            h1_dir == ("BULLISH" if direction == "LONG" else "BEARISH")
            and mtf_ok
            and trigger_ok
            and adx1 >= 20
        )

    elif strategy == "PULLBACK":
        valid_high_setup = (
            mtf_ok
            and trigger_ok
            and adx1 >= 20
        )

    elif strategy == "BREAKOUT":
        valid_high_setup = (
            trigger_ok
            and vol_spike
            and adx15 >= 18
        )

    elif strategy == "REVERSAL":
        valid_high_setup = (
            trigger_ok
            and adx15 >= 15
        )

    elif strategy == "RANGE_TRADING":
        valid_high_setup = (
            trigger_ok
            and adx1 <= 22
        )

    if not valid_high_setup:
        return no_trade(
            reason="SETUP_NOT_STRONG_ENOUGH",
            daily=daily_dir, h4=h4_dir, h1=h1_dir,
            daily_ema=daily_ema, h4_ema=h4_ema, h1_ema=h1_ema,
            rsi_15m=rsi15, adx_1h=adx1, adx_15m=adx15,
            mtf_confirmed=mtf_ok, volume_spike_value=vol_spike,
            confirmation=trigger_ok, strategies=strategy_names,
            direction=direction,
        )

    if score < 9:
        return no_trade(
            reason="SIGNAL_QUALITY_TOO_LOW",
            daily=daily_dir, h4=h4_dir, h1=h1_dir,
            daily_ema=daily_ema, h4_ema=h4_ema, h1_ema=h1_ema,
            rsi_15m=rsi15, adx_1h=adx1, adx_15m=adx15,
            mtf_confirmed=mtf_ok, volume_spike_value=vol_spike,
            confirmation=trigger_ok, strategies=strategy_names,
            direction=direction,
        )

    levels = calculate_trade_levels(direction, h1_c, m5_c)
    if not levels:
        return no_trade(
            reason="INVALID_TRADE_LEVELS",
            daily=daily_dir, h4=h4_dir, h1=h1_dir,
            daily_ema=daily_ema, h4_ema=h4_ema, h1_ema=h1_ema,
            rsi_15m=rsi15, adx_1h=adx1, adx_15m=adx15,
            mtf_confirmed=mtf_ok, volume_spike_value=vol_spike,
            confirmation=trigger_ok, strategies=strategy_names,
            direction=direction,
        )

    strategy_details = {item["name"]: item["reason"] for item in matches}

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
