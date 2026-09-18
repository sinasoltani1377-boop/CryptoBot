# ============================================================
# CryptoBot - Professional Analysis Engine v4
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
    """
    تبدیل انواع مختلف کندل به دیکشنری استاندارد.
    داده‌های خراب یا ناشناخته حذف می‌شوند.
    """

    if isinstance(candle, dict):
        return {
            "timestamp": candle.get(
                "timestamp",
                candle.get("time")
            ),
            "open": safe_float(candle.get("open")),
            "high": safe_float(candle.get("high")),
            "low": safe_float(candle.get("low")),
            "close": safe_float(candle.get("close")),
            "volume": safe_float(candle.get("volume")),
        }

    if isinstance(candle, (list, tuple)):
        if len(candle) < 5:
            return None

        return {
            "timestamp": candle[0],
            "open": safe_float(candle[1]),
            "high": safe_float(candle[2]),
            "low": safe_float(candle[3]),
            "close": safe_float(candle[4]),
            "volume": safe_float(candle[5])
            if len(candle) > 5
            else 0.0,
        }

    return None


def clean_candles(candles):
    """
    فقط کندل‌های معتبر را نگه می‌دارد.
    """

    if not isinstance(candles, (list, tuple)):
        return []

    cleaned = []

    for candle in candles:
        normalized = normalize_candle(candle)

        if normalized is None:
            continue

        if (
            normalized["open"] <= 0
            or normalized["high"] <= 0
            or normalized["low"] <= 0
            or normalized["close"] <= 0
        ):
            continue

        if normalized["high"] < normalized["low"]:
            continue

        cleaned.append(normalized)

    return cleaned


def get_closes(candles):
    return [
        safe_float(c.get("close"))
        for c in candles
        if isinstance(c, dict)
    ]


def get_highs(candles):
    return [
        safe_float(c.get("high"))
        for c in candles
        if isinstance(c, dict)
    ]


def get_lows(candles):
    return [
        safe_float(c.get("low"))
        for c in candles
        if isinstance(c, dict)
    ]


def get_opens(candles):
    return [
        safe_float(c.get("open"))
        for c in candles
        if isinstance(c, dict)
    ]


# ============================================================
# EMA
# ============================================================

def calculate_ema(candles, period):

    candles = clean_candles(candles)

    if len(candles) < period:
        return None

    closes = get_closes(candles)

    if len(closes) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(closes[:period]) / period

    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def ema_trend(candles):

    candles = clean_candles(candles)

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

    candles = clean_candles(candles)

    swing_highs = []
    swing_lows = []

    required = strength * 2 + 1

    if len(candles) < required:
        return swing_highs, swing_lows

    for i in range(
        strength,
        len(candles) - strength
    ):

        current_high = safe_float(
            candles[i].get("high")
        )

        current_low = safe_float(
            candles[i].get("low")
        )

        left_highs = [
            safe_float(candles[j].get("high"))
            for j in range(
                i - strength,
                i
            )
        ]

        right_highs = [
            safe_float(candles[j].get("high"))
            for j in range(
                i + 1,
                i + strength + 1
            )
        ]

        left_lows = [
            safe_float(candles[j].get("low"))
            for j in range(
                i - strength,
                i
            )
        ]

        right_lows = [
            safe_float(candles[j].get("low"))
            for j in range(
                i + 1,
                i + strength + 1
            )
        ]

        if current_high > max(
            left_highs + right_highs
        ):
            swing_highs.append({
                "index": i,
                "price": current_high,
            })

        if current_low < min(
            left_lows + right_lows
        ):
            swing_lows.append({
                "index": i,
                "price": current_low,
            })

    return swing_highs, swing_lows


# ============================================================
# MARKET STRUCTURE
# ============================================================

def get_structure_direction(candles):

    candles = clean_candles(candles)

    swing_highs, swing_lows = find_swings(candles)

    if len(swing_highs) < 2:
        return "RANGE"

    if len(swing_lows) < 2:
        return "RANGE"

    last_high = swing_highs[-1]["price"]
    previous_high = swing_highs[-2]["price"]

    last_low = swing_lows[-1]["price"]
    previous_low = swing_lows[-2]["price"]

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


def structure_details(candles):

    candles = clean_candles(candles)

    swing_highs, swing_lows = find_swings(candles)

    return {
        "direction": get_structure_direction(candles),
        "swing_highs": swing_highs[-5:],
        "swing_lows": swing_lows[-5:],
    }


# ============================================================
# MULTI TIMEFRAME
# ============================================================

def analyze_all_timeframes(
    daily,
    h4,
    h1
):

    return {
        "daily": get_structure_direction(daily),
        "4h": get_structure_direction(h4),
        "1h": get_structure_direction(h1),
    }


def check_trend_alignment(
    daily,
    h4,
    h1
):

    d = get_structure_direction(daily)
    h4_trend = get_structure_direction(h4)
    h1_trend = get_structure_direction(h1)

    if (
        d == "BULLISH"
        and h4_trend == "BULLISH"
    ):
        return "BULLISH"

    if (
        d == "BEARISH"
        and h4_trend == "BEARISH"
    ):
        return "BEARISH"

    if (
        d == "BULLISH"
        and h4_trend == "RANGE"
    ):
        return "BULLISH_WEAK"

    if (
        d == "BEARISH"
        and h4_trend == "RANGE"
    ):
        return "BEARISH_WEAK"

    return "NO_ALIGNMENT"


# ============================================================
# BREAK OF STRUCTURE
# ============================================================

def detect_bos(candles):

    candles = clean_candles(candles)

    if len(candles) < 10:
        return None

    swing_highs, swing_lows = find_swings(
        candles[:-1]
    )

    current_close = safe_float(
        candles[-1].get("close")
    )

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

def detect_pullback(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 8:
        return False

    recent = candles[-6:]

    highs = get_highs(recent)
    lows = get_lows(recent)

    if not highs or not lows:
        return False

    current_close = safe_float(
        candles[-1].get("close")
    )

    recent_high = max(highs)
    recent_low = min(lows)

    total_range = recent_high - recent_low

    if total_range <= 0:
        return False

    position = (
        current_close - recent_low
    ) / total_range

    if direction == "LONG":
        return position < 0.70

    if direction == "SHORT":
        return position > 0.30

    return False


# ============================================================
# SUPPORT / RESISTANCE
# ============================================================

def find_support_resistance(candles):

    candles = clean_candles(candles)

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

def detect_breakout_retest(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 12:
        return False

    sr = find_support_resistance(
        candles[:-3]
    )

    support = sr.get("support")
    resistance = sr.get("resistance")

    recent = candles[-3:]

    if (
        direction == "LONG"
        and resistance is not None
    ):

        breakout = (
            safe_float(
                recent[1].get("close")
            )
            > resistance
        )

        ret
