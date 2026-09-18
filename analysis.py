# ============================================================
# CryptoBot - Professional Analysis Engine v2
# ============================================================

from math import isfinite


# ============================================================
# BASIC HELPERS
# ============================================================

def get_closes(candles):
    return [safe_float(c.get("close")) for c in candles]


def get_highs(candles):
    return [safe_float(c.get("high")) for c in candles]


def get_lows(candles):
    return [safe_float(c.get("low")) for c in candles]


def get_opens(candles):
    return [safe_float(c.get("open")) for c in candles]


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

        if current_high > max(left_highs + right_highs):
            swing_highs.append({
                "index": i,
                "price": current_high
           
