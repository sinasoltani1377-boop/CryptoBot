# ============================================================
# CryptoBot - Analysis Engine v14
#
# 1H  = Main trend / strategy environment
# 15M = Setup confirmation
# 5M  = Entry trigger
#
# EXACTLY 5 STRATEGIES:
#   1. TREND_FOLLOWING
#   2. PULLBACK
#   3. BREAKOUT
#   4. REVERSAL
#   5. RANGE_TRADING
#
# v14:
# - closed candles only
# - standard Wilder ADX
# - HIGH only
# - strategy-specific logic
# - 1H RANGE is evaluated instead of being abandoned
# - 5M trigger is less brittle
# - breakout detection improved
# - reversal detection improved
# - range detection improved
# - HTF context is a filter, not an unnecessary hard wall
# - existing signal/level keys preserved
# - SL/TP model unchanged
# ============================================================

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        if math.isfinite(x):
            return x
    except Exception:
        pass
    return default


def candle_values(c: Any) -> Tuple[float, float, float, float, float]:
    if isinstance(c, dict):
        return (
            safe_float(c.get("open", c.get("o", c.get("Open", 0)))),
            safe_float(c.get("high", c.get("h", c.get("High", 0)))),
            safe_float(c.get("low", c.get("l", c.get("Low", 0)))),
            safe_float(c.get("close", c.get("c", c.get("Close", 0)))),
            safe_float(c.get("volume", c.get("v", c.get("Volume", 0)))),
        )

    if isinstance(c, (list, tuple)):
        if len(c) >= 6:
            return (
                safe_float(c[1]),
                safe_float(c[2]),
                safe_float(c[3]),
                safe_float(c[4]),
                safe_float(c[5]),
            )

        if len(c) >= 5:
            return (
                safe_float(c[0]),
                safe_float(c[1]),
                safe_float(c[2]),
                safe_float(c[3]),
                safe_float(c[4]),
            )

    return 0.0, 0.0, 0.0, 0.0, 0.0


def normalize_candles(candles: Any) -> List[Any]:
    if not candles:
        return []

    if isinstance(candles, dict):
        for key in ("data", "result", "rows", "klines", "candles"):
            value = candles.get(key)
            if isinstance(value, list):
                candles = value
                break

    if not isinstance(candles, list):
        return []

    result = []

    for c in candles:
        o, h, l, cl, v = candle_values(c)

        if h <= 0 or l <= 0 or cl <= 0:
            continue

        if h < l:
            continue

        result.append(c)

    return result


def closed(candles: Any, count: int = 2) -> List[Any]:
    """
    Remove the currently forming candle.
    """

    arr = normalize_candles(candles)

    if len(arr) <= count:
        return []

    return arr[:-1]


def closes(candles: List[Any]) -> List[float]:
    return [candle_values(c)[3] for c in candles]


def highs(candles: List[Any]) -> List[float]:
    return [candle_values(c)[1] for c in candles]


def lows(candles: List[Any]) -> List[float]:
    return [candle_values(c)[2] for c in candles]


def volumes(candles: List[Any]) -> List[float]:
    return [candle_values(c)[4] for c in candles]


def body(c: Any) -> float:
    o, _, _, cl, _ = candle_values(c)
    return abs(cl - o)


def candle_range(c: Any) -> float:
    _, h, l, _, _ = candle_values(c)
    return max(h - l, 0.0)


def body_ratio(c: Any) -> float:
    r = candle_range(c)

    if r <= 0:
        return 0.0

    return body(c) / r


def upper_wick(c: Any) -> float:
    o, h, _, cl, _ = candle_values(c)
    return max(0.0, h - max(o, cl))


def lower_wick(c: Any) -> float:
    o, _, l, cl, _ = candle_values(c)
    return max(0.0, min(o, cl) - l)


def bullish(c: Any) -> bool:
    o, _, _, cl, _ = candle_values(c)
    return cl > o


def bearish(c: Any) -> bool:
    o, _, _, cl, _ = candle_values(c)
    return cl < o


# ============================================================
# INDICATORS
# ============================================================

def ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None

    k = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period

    for x in values[period:]:
        value = x * k + value * (1.0 - k)

    return value


def ema_direction(candles: List[Any]) -> str:
    cls = closes(candles)

    e20 = ema(cls, 20)
    e50 = ema(cls, 50)
    e200 = ema(cls, 200) if len(cls) >= 200 else None

    if e20 is None or e50 is None:
        return "RANGE"

    price = cls[-1]

    if e200 is not None:
        if price > e20 > e50 > e200:
            return "BULLISH"

        if price < e20 < e50 < e200:
            return "BEARISH"

    if price > e20 > e50:
        return "BULLISH"

    if price < e20 < e50:
        return "BEARISH"

    return "RANGE"


def rsi(candles: List[Any], period: int = 14) -> float:
    cls = closes(candles)

    if len(cls) <= period:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(cls)):
        diff = cls[i] - cls[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles: List[Any], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0

    trs = []
    previous_close = candle_values(candles[0])[3]

    for c in candles[1:]:
        _, h, l, cl, _ = candle_values(c)

        tr = max(
            h - l,
            abs(h - previous_close),
            abs(l - previous_close),
        )

        trs.append(tr)
        previous_close = cl

    if len(trs) < period:
        return 0.0

    value = sum(trs[:period]) / period

    for tr in trs[period:]:
        value = (
            value * (period - 1) + tr
        ) / period

    return value


def adx(candles: List[Any], period: int = 14) -> float:
    """
    Standard Wilder ADX.
    """

    if len(candles) < period * 2 + 1:
        return 0.0

    tr_values = []
    plus_dm = []
    minus_dm = []

    previous_close = candle_values(candles[0])[3]

    for i in range(1, len(candles)):
        _, h, l, cl, _ = candle_values(candles[i])
        _, prev_h, prev_l, _, _ = candle_values(candles[i - 1])

        up_move = h - prev_h
        down_move = prev_l - l

        plus = (
            up_move
            if up_move > down_move and up_move > 0
            else 0.0
        )

        minus = (
            down_move
            if down_move > up_move and down_move > 0
            else 0.0
        )

        tr = max(
            h - l,
            abs(h - previous_close),
            abs(l - previous_close),
        )

        tr_values.append(tr)
        plus_dm.append(plus)
        minus_dm.append(minus)
        previous_close = cl

    if len(tr_values) < period * 2:
        return 0.0

    tr14 = sum(tr_values[:period])
    plus14 = sum(plus_dm[:period])
    minus14 = sum(minus_dm[:period])

    dx_values = []

    for i in range(period, len(tr_values)):
        tr14 = tr14 - tr14 / period + tr_values[i]
        plus14 = plus14 - plus14 / period + plus_dm[i]
        minus14 = minus14 - minus14 / period + minus_dm[i]

        if tr14 <= 0:
            continue

        plus_di = 100.0 * plus14 / tr14
        minus_di = 100.0 * minus14 / tr14
        denominator = plus_di + minus_di

        if denominator <= 0:
            dx = 0.0
        else:
            dx = (
                100.0
                * abs(plus_di - minus_di)
                / denominator
            )

        dx_values.append(dx)

    if len(dx_values) < period:
        return 0.0

    value = sum(dx_values[:period]) / period

    for dx in dx_values[period:]:
        value = (
            value * (period - 1) + dx
        ) / period

    return value


def volume_spike(
    candles: List[Any],
    multiplier: float = 1.10,
    lookback: int = 20,
) -> bool:
    vs = volumes(candles)

    if len(vs) < lookback + 1:
        return False

    average = sum(vs[-lookback - 1:-1]) / lookback

    if average <= 0:
        return False

    return vs[-1] >= average * multiplier


# ============================================================
# MARKET STRUCTURE
# ============================================================

def swing_high(
    candles: List[Any],
    strength: int = 2,
) -> Optional[float]:
    if len(candles) < strength * 2 + 1:
        return None

    hs = highs(candles)

    for i in range(
        len(hs) - strength - 1,
        strength - 1,
        -1,
    ):
        value = hs[i]

        left_ok = all(
            value > hs[i - j]
            for j in range(1, strength + 1)
        )

        right_ok = all(
            value >= hs[i + j]
            for j in range(1, strength + 1)
        )

        if left_ok and right_ok:
            return value

    return None


def swing_low(
    candles: List[Any],
    strength: int = 2,
) -> Optional[float]:
    if len(candles) < strength * 2 + 1:
        return None

    ls = lows(candles)

    for i in range(
        len(ls) - strength - 1,
        strength - 1,
        -1,
    ):
        value = ls[i]

        left_ok = all(
            value < ls[i - j]
            for j in range(1, strength + 1)
        )

        right_ok = all(
            value <= ls[i + j]
            for j in range(1, strength + 1)
        )

        if left_ok and right_ok:
            return value

    return None


def market_structure(
    candles: List[Any],
    lookback: int = 40,
) -> str:
    arr = candles[-lookback:] if len(candles) > lookback else candles

    if len(arr) < 12:
        return "RANGE"

    mid = len(arr) // 2

    early_high = max(highs(arr[:mid]))
    late_high = max(highs(arr[mid:]))
    early_low = min(lows(arr[:mid]))
    late_low = min(lows(arr[mid:]))

    cls = closes(arr)
    average_recent = sum(cls[-5:]) / 5

    bullish_structure = (
        late_high > early_high
        and late_low > early_low
        and cls[-1] >= average_recent
    )

    bearish_structure = (
        late_high < early_high
        and late_low < early_low
        and cls[-1] <= average_recent
    )

    if bullish_structure:
        return "BULLISH"

    if bearish_structure:
        return "BEARISH"

    return "RANGE"


def direction_from_tf(candles: List[Any]) -> str:
    structure = market_structure(candles)

    if structure in ("BULLISH", "BEARISH"):
        return structure

    return ema_direction(candles)


# ============================================================
# 15M / 5M CONFIRMATION
# ============================================================

def mtf_confirmation(
    m15: List[Any],
    direction: str,
) -> bool:
    if len(m15) < 25:
        return False

    cls = closes(m15)
    e20 = ema(cls, 20)
    e50 = ema(cls, 50)

    if e20 is None or e50 is None:
        return False

    recent = m15[-3:]

    if direction == "LONG":
        bullish_count = sum(1 for c in recent if bullish(c))

        return (
            bullish_count >= 2
            and cls[-1] >= e20 * 0.999
            and cls[-1] >= e50 * 0.995
        )

    if direction == "SHORT":
        bearish_count = sum(1 for c in recent if bearish(c))

        return (
            bearish_count >= 2
            and cls[-1] <= e20 * 1.001
            and cls[-1] <= e50 * 1.005
        )

    return False


def strong_confirmation_5m(
    m5: List[Any],
    direction: str,
) -> bool:
    if len(m5) < 8:
        return False

    last = m5[-1]
    previous = m5[-2]
    recent = m5[-7:-1]

    _, prev_high, prev_low, _, _ = candle_values(previous)
    _, _, _, last_close, _ = candle_values(last)

    if direction == "LONG":
        two_candle_push = (
            bullish(previous)
            and bullish(last)
            and body_ratio(last) >= 0.35
            and last_close > prev_high
        )

        structure_break = (
            bullish(last)
            and body_ratio(last) >= 0.45
            and last_close > max(highs(recent))
        )

        return two_candle_push or structure_break

    if direction == "SHORT":
        two_candle_push = (
            bearish(previous)
            and bearish(last)
            and body_ratio(last) >= 0.35
            and last_close < prev_low
        )

        structure_break = (
            bearish(last)
            and body_ratio(last) >= 0.45
            and last_close < min(lows(recent))
        )

        return two_candle_push or structure_break

    return False


def entry_trigger_5m(
    m5: List[Any],
    direction: str,
) -> bool:
    # First accept the stronger two-candle or full structure-break trigger.
    if strong_confirmation_5m(m5, direction):
        return True

    # A smaller 3-candle structure break is also accepted. Requiring a break
    # of all five preceding highs/lows was filtering out many otherwise valid
    # setups; body direction and minimum body size still reject weak candles.
    if len(m5) < 6:
        return False

    recent = m5[-4:-1]
    last = m5[-1]
    last_close = candle_values(last)[3]

    if direction == "LONG":
        return (
            bullish(last)
            and body_ratio(last) >= 0.30
            and last_close > max(highs(recent))
        )

    if direction == "SHORT":
        return (
            bearish(last)
            and body_ratio(last) >= 0.30
            and last_close < min(lows(recent))
        )

    return False


# ============================================================
# PULLBACK
# ============================================================

def near_ema_zone(
    h1: List[Any],
    direction: str,
) -> bool:
    cls = closes(h1)
    e20 = ema(cls, 20)
    e50 = ema(cls, 50)
    atr_value = atr(h1)

    if e20 is None or e50 is None or atr_value <= 0:
        return False

    price = cls[-1]
    zone = max(atr_value * 0.80, price * 0.005)
    distance = min(abs(price - e20), abs(price - e50))

    if direction == "LONG":
        return (
            distance <= zone
            and price >= min(e20, e50) * 0.992
        )

    if direction == "SHORT":
        return (
            distance <= zone
            and price <= max(e20, e50) * 1.008
        )

    return False


def rejection(
    candle: Any,
    direction: str,
) -> bool:
    r = candle_range(candle)

    if r <= 0:
        return False

    if direction == "LONG":
        return (
            lower_wick(candle) >= body(candle) * 0.60
            and lower_wick(candle) / r >= 0.20
            and candle_values(candle)[3] >= candle_values(candle)[0]
        )

    if direction == "SHORT":
        return (
            upper_wick(candle) >= body(candle) * 0.60
            and upper_wick(candle) / r >= 0.20
            and candle_values(candle)[3] <= candle_values(candle)[0]
        )

    return False


def recent_rejection(
    candles: List[Any],
    direction: str,
    lookback: int = 6,
) -> bool:
    return any(rejection(c, direction) for c in candles[-lookback:])


def pullback_detected(
    h1: List[Any],
    direction: str,
) -> bool:
    if len(h1) < 25:
        return False

    cls = closes(h1)
    e20 = ema(cls, 20)
    e50 = ema(cls, 50)
    atr_value = atr(h1)

    if e20 is None or e50 is None or atr_value <= 0:
        return False

    zone = max(atr_value * 0.90, cls[-1] * 0.006)
    recent = h1[-14:]

    if direction == "LONG":
        touched = any(
            candle_values(c)[2] <= max(e20, e50) + zone
            for c in recent
        )
        recovery = cls[-1] > e20
        return touched and recovery

    if direction == "SHORT":
        touched = any(
            candle_values(c)[1] >= min(e20, e50) - zone
            for c in recent
        )
        recovery = cls[-1] < e20
        return touched and recovery

    return False


# ============================================================
# BREAKOUT
# ============================================================

def local_breakout(
    m15: List[Any],
    direction: str,
    lookback: int = 20,
) -> Tuple[bool, float]:
    if len(m15) < lookback + 2:
        return False, 0.0

    previous = m15[-lookback - 1:-1]
    last = m15[-1]
    level_high = max(highs(previous))
    level_low = min(lows(previous))
    close = candle_values(last)[3]

    if direction == "LONG":
        return close > level_high, level_high

    if direction == "SHORT":
        return close < level_low, level_low

    return False, 0.0


def breakout_hold(
    m15: List[Any],
    direction: str,
    level: float,
) -> bool:
    if level <= 0 or len(m15) < 3:
        return False

    recent = m15[-3:]

    if direction == "LONG":
        good = sum(
            candle_values(c)[3] >= level * 0.997
            for c in recent
        )
        return good >= 2

    if direction == "SHORT":
        good = sum(
            candle_values(c)[3] <= level * 1.003
            for c in recent
        )
        return good >= 2

    return False


# ============================================================
# REVERSAL
# ============================================================

def sweep_reclaim_recent(
    m15: List[Any],
    direction: str,
    lookback: int = 12,
) -> bool:
    if len(m15) < lookback + 3:
        return False

    previous = m15[-lookback - 3:-3]

    if not previous:
        return False

    previous_high = max(highs(previous))
    previous_low = min(lows(previous))
    recent = m15[-3:]

    for c in recent:
        _, h, l, close, _ = candle_values(c)

        if direction == "LONG":
            if l < previous_low and close > previous_low and bullish(c):
                return True

        if direction == "SHORT":
            if h > previous_high and close < previous_high and bearish(c):
                return True

    return False


def structure_shift_5m(
    m5: List[Any],
    direction: str,
) -> bool:
    if len(m5) < 12:
        return False

    previous = m5[-8:-1]
    last = m5[-1]
    close = candle_values(last)[3]

    if direction == "LONG":
        return (
            bullish(last)
            and body_ratio(last) >= 0.30
            and close > max(highs(previous))
        )

    if direction == "SHORT":
        return (
            bearish(last)
            and body_ratio(last) >= 0.30
            and close < min(lows(previous))
        )

    return False


# ============================================================
# RANGE
# ============================================================

def range_info(
    h1: List[Any],
) -> Tuple[bool, float, float]:
    if len(h1) < 30:
        return False, 0.0, 0.0

    recent = h1[-24:]
    high = max(highs(recent))
    low = min(lows(recent))
    width = high - low
    atr_value = atr(recent)

    if width <= 0 or atr_value <= 0:
        return False, high, low

    is_range = width <= atr_value * 7.5
    return is_range, high, low


def near_range_boundary(
    h1: List[Any],
    direction: str,
    high: float,
    low: float,
) -> bool:
    price = closes(h1)[-1]
    width = high - low

    if width <= 0:
        return False

    edge = width * 0.25

    if direction == "LONG":
        return price <= low + edge

    if direction == "SHORT":
        return price >= high - edge

    return False


def range_direction(
    h1: List[Any],
) -> Optional[str]:
    ok, high, low = range_info(h1)

    if not ok:
        return None

    if near_range_boundary(h1, "LONG", high, low):
        return "LONG"

    if near_range_boundary(h1, "SHORT", high, low):
        return "SHORT"

    return None


# ============================================================
# STRATEGIES
# ============================================================

def detect_trend_following(
    h1: List[Any],
    m15: List[Any],
    m5: List[Any],
    direction: str,
) -> Dict[str, Any]:
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    structure = market_structure(h1)
    ema_dir = ema_direction(h1)
    adx1 = adx(h1)

    if structure != expected and ema_dir != expected:
        return {"valid": False, "reason": "H1_TREND_MISSING"}

    if adx1 < 18:
        return {"valid": False, "reason": "ADX_LOW"}

    trigger = entry_trigger_5m(m5, direction)

    if not trigger:
        return {"valid": False, "reason": "5M_TRIGGER"}

    mtf = mtf_confirmation(m15, direction)
    pullback = pullback_detected(h1, direction)
    score = 4

    if structure == expected:
        score += 2

    if ema_dir == expected:
        score += 2

    if adx1 >= 25:
        score += 1

    if mtf:
        score += 1

    if pullback:
        score += 1

    return {"valid": True, "reason": "VALID", "score": score, "mtf": mtf}


def detect_pullback(
    h1: List[Any],
    m15: List[Any],
    m5: List[Any],
    direction: str,
) -> Dict[str, Any]:
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    structure = direction_from_tf(h1)
    ema_dir = ema_direction(h1)

    if structure != expected and ema_dir != expected:
        return {"valid": False, "reason": "H1_TREND_MISSING"}

    if not pullback_detected(h1, direction):
        return {"valid": False, "reason": "NO_PULLBACK_ZONE"}

    ema_zone = near_ema_zone(h1, direction)
    rejection_found = recent_rejection(h1, direction, 6)

    if not ema_zone and not rejection_found:
        return {"valid": False, "reason": "NO_PULLBACK_CONFIRMATION"}

    if not entry_trigger_5m(m5, direction):
        return {"valid": False, "reason": "5M_TRIGGER"}

    mtf = mtf_confirmation(m15, direction)
    score = 5

    if ema_zone:
        score += 2

    if rejection_found:
        score += 1

    if mtf:
        score += 1

    if adx(h1) >= 22:
        score += 1

    return {"valid": True, "reason": "VALID", "score": score, "mtf": mtf}


def detect_breakout(
    h1: List[Any],
    m15: List[Any],
    m5: List[Any],
    direction: str,
) -> Dict[str, Any]:
    ok, level = local_breakout(m15, direction, 20)

    if not ok:
        return {"valid": False, "reason": "NO_BREAKOUT"}

    last = m15[-1]

    if body_ratio(last) < 0.38:
        return {"valid": False, "reason": "WEAK_BREAKOUT_CANDLE"}

    if not volume_spike(m15, 1.08, 20):
        return {"valid": False, "reason": "NO_VOLUME"}

    if not breakout_hold(m15, direction, level):
        return {"valid": False, "reason": "NO_HOLD"}

    if not entry_trigger_5m(m5, direction):
        return {"valid": False, "reason": "5M_TRIGGER"}

    mtf = mtf_confirmation(m15, direction)
    score = 6

    if mtf:
        score += 2

    if adx(h1) >= 20:
        score += 1

    return {
        "valid": True,
        "reason": "VALID",
        "score": score,
        "mtf": mtf,
        "level": level,
    }


def detect_reversal(
    h1: List[Any],
    m15: List[Any],
    m5: List[Any],
    direction: str,
) -> Dict[str, Any]:
    if not sweep_reclaim_recent(m15, direction):
        return {"valid": False, "reason": "NO_SWEEP_RECLAIM"}

    if not structure_shift_5m(m5, direction):
        return {"valid": False, "reason": "NO_5M_STRUCTURE_SHIFT"}

    last = m15[-1]

    if body_ratio(last) < 0.30:
        return {"valid": False, "reason": "WEAK_RECLAIM"}

    mtf = mtf_confirmation(m15, direction)
    score = 7

    if mtf:
        score += 1

    return {"valid": True, "reason": "VALID", "score": score, "mtf": mtf}


def detect_range(
    h1: List[Any],
    m5: List[Any],
    direction: str,
) -> Dict[str, Any]:
    ok, high, low = range_info(h1)

    if not ok:
        return {"valid": False, "reason": "NOT_RANGE"}

    adx1 = adx(h1)

    if adx1 > 24:
        return {"valid": False, "reason": "ADX_TOO_HIGH"}

    if not near_range_boundary(h1, direction, high, low):
        return {"valid": False, "reason": "NOT_AT_BOUNDARY"}

    rejection_found = recent_rejection(h1, direction, 6)

    if not rejection_found:
        return {"valid": False, "reason": "NO_REJECTION"}

    if not entry_trigger_5m(m5, direction):
        return {"valid": False, "reason": "5M_TRIGGER"}

    score = 6

    if adx1 <= 18:
        score += 1

    return {"valid": True, "reason": "VALID", "score": score, "mtf": False}


# ============================================================
# HIGHER TIMEFRAME CONTEXT
# ============================================================

def context_allows(
    strategy: str,
    daily: str,
    h4: str,
    direction: str,
    h4_adx: float,
) -> bool:
    expected = "BULLISH" if direction == "LONG" else "BEARISH"

    # Only block continuation setups when H4 is strongly opposite.
    if strategy in ("TREND_FOLLOWING", "PULLBACK", "BREAKOUT"):
        if (
            h4 in ("BULLISH", "BEARISH")
            and h4 != expected
            and h4_adx >= 30
        ):
            return False

    # Range can work against weaker HTF trends.
    if strategy == "RANGE_TRADING":
        if (
            h4 in ("BULLISH", "BEARISH")
            and h4 != expected
            and h4_adx >= 32
        ):
            return False

    # Reversal is intentionally allowed against HTF trend.
    return True


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_trade_levels(
    h1: List[Any],
    m5: List[Any],
    direction: str,
) -> Optional[Dict[str, float]]:
    # Same SL/TP model as the previous version.
    if direction not in ("LONG", "SHORT") or not h1 or not m5:
        return None

    entry = closes(m5)[-1]
    atr1 = atr(h1, 14)

    if entry <= 0 or atr1 <= 0:
        return None

    sh = swing_high(h1, 2)
    slw = swing_low(h1, 2)

    if direction == "LONG":
        base_sl = slw - 0.35 * atr1 if slw else entry - 1.2 * atr1
        risk = entry - base_sl
        min_risk = 1.2 * atr1

        if risk < min_risk:
            base_sl = entry - min_risk
            risk = min_risk

        if risk > 3.0 * atr1:
            return None

        if risk / entry > 0.035:
            return None

        sl = base_sl
        tp1 = entry + 1.5 * risk
        tp2 = entry + 2.5 * risk
        tp3 = entry + 3.0 * risk

    else:
        base_sl = sh + 0.35 * atr1 if sh else entry + 1.2 * atr1
        risk = base_sl - entry
        min_risk = 1.2 * atr1

        if risk < min_risk:
            base_sl = entry + min_risk
            risk = min_risk

        if risk > 3.0 * atr1:
            return None

        if risk / entry > 0.035:
            return None

        sl = base_sl
        tp1 = entry - 1.5 * risk
        tp2 = entry - 2.5 * risk
        tp3 = entry - 3.0 * risk

    return {
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": "1:3",
    }


def target_reachable(
    levels: Dict[str, float],
    h1: List[Any],
    direction: str,
) -> bool:
    """Reject TP1 only when a confirmed 1H swing blocks the target path.

    The previous version treated every candle high/low as a resistance/support
    barrier. That made ordinary candle noise block many trades. Here we inspect
    confirmed local pivots in the recent 1H structure instead.
    """
    entry = safe_float(levels.get("entry"))
    tp1 = safe_float(levels.get("tp1"))
    if entry <= 0 or tp1 <= 0 or direction not in ("LONG", "SHORT"):
        return False

    recent = h1[-25:] if len(h1) > 25 else h1
    if len(recent) < 6:
        return True

    hs = highs(recent)
    ls = lows(recent)
    pivots = []
    strength = 2

    # Exclude the most recent candle because the current entry candle may not
    # yet have a fully confirmed pivot around it.
    end = len(recent) - strength
    for i in range(strength, end):
        is_pivot_high = all(hs[i] > hs[i-j] for j in range(1, strength+1)) and all(
            hs[i] >= hs[i+j] for j in range(1, strength+1)
        )
        is_pivot_low = all(ls[i] < ls[i-j] for j in range(1, strength+1)) and all(
            ls[i] <= ls[i+j] for j in range(1, strength+1)
        )
        if is_pivot_high:
            pivots.append(("HIGH", hs[i]))
        if is_pivot_low:
            pivots.append(("LOW", ls[i]))

    if direction == "LONG":
        barriers = [price for kind, price in pivots if kind == "HIGH" and entry < price < tp1]
        return not barriers

    barriers = [price for kind, price in pivots if kind == "LOW" and tp1 < price < entry]
    return not barriers


# ============================================================
# NO TRADE
# ============================================================

def no_trade(
    reason: str,
    daily: str = "RANGE",
    h4: str = "RANGE",
    h1: str = "RANGE",
    direction: Optional[str] = None,
    diagnostics: Optional[Dict[str, str]] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = {
        "signal": "NO_TRADE",
        "direction": direction,
        "score": 0,
        "quality": "LOW",
        "reason": reason,
        # Keep valid strategy names visible in diagnostics even when no HIGH
        # signal is emitted. This prevents bot.py from misleadingly logging NONE.
        "strategies": [
            name for name, status in (diagnostics or {}).items()
            if status == "VALID" or status.startswith("HIGH_FAIL:")
        ],
        "strategy": None,
        "strategy_diagnostics": diagnostics or {},
        "daily": daily,
        "4h": h4,
        "1h": h1,
    }

    if metrics:
        result.update(metrics)

    return result


# ============================================================
# MAIN ENGINE
# ============================================================

def generate_signal(
    daily: Any,
    h4: Any,
    h1: Any,
    m15: Any,
    m5: Any,
) -> Dict[str, Any]:
    d = closed(daily)
    h4c = closed(h4)
    h1c = closed(h1)
    m15c = closed(m15)
    m5c = closed(m5)

    if min(len(d), len(h4c), len(h1c), len(m15c), len(m5c)) < 50:
        return no_trade("INSUFFICIENT_DATA")

    # GLOBAL CONTEXT
    daily_dir = direction_from_tf(d)
    h4_dir = direction_from_tf(h4c)
    h1_dir = direction_from_tf(h1c)

    rsi15 = round(rsi(m15c), 2)
    adx1 = round(adx(h1c), 2)
    adx15 = round(adx(m15c), 2)
    h4_adx = adx(h4c)
    volume = volume_spike(m15c, 1.08, 20)

    diagnostics = {}

    metrics = {
        "15m_rsi": rsi15,
        "adx_1h": adx1,
        "adx_15m": adx15,
        "mtf_confirmation": False,
        "volume_spike": bool(volume),
        "confirmation": False,
    }

    if h1_dir == "BULLISH":
        candidate_directions = ["LONG"]
    elif h1_dir == "BEARISH":
        candidate_directions = ["SHORT"]
    else:
        candidate_directions = ["LONG", "SHORT"]

    # STRATEGY EVALUATION
    strategy_results = []

    strategy_names = [
        "TREND_FOLLOWING",
        "PULLBACK",
        "BREAKOUT",
        "REVERSAL",
        "RANGE_TRADING",
    ]

    for strategy_name in strategy_names:
        best_for_strategy = None
        best_direction = None

        # FIX: this condition belongs inside the strategy loop.
        # Breakout and reversal check both directions.
        if strategy_name in ("BREAKOUT", "REVERSAL"):
            directions_to_check = ["LONG", "SHORT"]
        else:
            directions_to_check = candidate_directions

        for direction in directions_to_check:
            try:
                if strategy_name == "TREND_FOLLOWING":
                    result = detect_trend_following(h1c, m15c, m5c, direction)
                elif strategy_name == "PULLBACK":
                    result = detect_pullback(h1c, m15c, m5c, direction)
                elif strategy_name == "BREAKOUT":
                    result = detect_breakout(h1c, m15c, m5c, direction)
                elif strategy_name == "REVERSAL":
                    result = detect_reversal(h1c, m15c, m5c, direction)
                else:
                    result = detect_range(h1c, m5c, direction)

            except Exception as exc:
                result = {
                    "valid": False,
                    "reason": f"ERROR_{type(exc).__name__}",
                }

            if result.get("valid"):
                if not context_allows(
                    strategy_name,
                    daily_dir,
                    h4_dir,
                    direction,
                    h4_adx,
                ):
                    continue

                if (
                    best_for_strategy is None
                    or result.get("score", 0)
                    > best_for_strategy.get("score", 0)
                ):
                    best_for_strategy = result
                    best_direction = direction

        # Diagnostics
        if best_for_strategy is not None:
            diagnostics[strategy_name] = "VALID"
            strategy_results.append(
                (strategy_name, best_direction, best_for_strategy)
            )
        else:
            diagnostic_reasons = []

            # Use the same direction rules as the actual evaluation.
            for direction in directions_to_check:
                try:
                    if strategy_name == "TREND_FOLLOWING":
                        test = detect_trend_following(h1c, m15c, m5c, direction)
                    elif strategy_name == "PULLBACK":
                        test = detect_pullback(h1c, m15c, m5c, direction)
                    elif strategy_name == "BREAKOUT":
                        test = detect_breakout(h1c, m15c, m5c, direction)
                    elif strategy_name == "REVERSAL":
                        test = detect_reversal(h1c, m15c, m5c, direction)
                    else:
                        test = detect_range(h1c, m5c, direction)

                    reason = test.get("reason", "UNKNOWN")

                    if (
                        test.get("valid")
                        and not context_allows(
                            strategy_name,
                            daily_dir,
                            h4_dir,
                            direction,
                            h4_adx,
                        )
                    ):
                        reason = "HTF_CONTEXT"

                    diagnostic_reasons.append(f"{direction}:{reason}")

                except Exception as exc:
                    diagnostic_reasons.append(
                        f"{direction}:ERROR_{type(exc).__name__}"
                    )

            diagnostics[strategy_name] = "FAIL:" + "|".join(diagnostic_reasons)

    # METRICS
    diagnostic_direction = None

    if strategy_results:
        diagnostic_direction = strategy_results[0][1]
    elif h1_dir == "BULLISH":
        diagnostic_direction = "LONG"
    elif h1_dir == "BEARISH":
        diagnostic_direction = "SHORT"

    if diagnostic_direction:
        metrics["mtf_confirmation"] = bool(
            mtf_confirmation(m15c, diagnostic_direction)
        )
        metrics["confirmation"] = bool(
            entry_trigger_5m(m5c, diagnostic_direction)
        )

    # NO VALID STRATEGY
    if not strategy_results:
        return no_trade(
            "NO_VALID_STRATEGY",
            daily_dir,
            h4_dir,
            h1_dir,
            None,
            diagnostics,
            metrics,
        )

    # Evaluate every valid strategy independently. Do not let a high-priority
    # strategy that fails the HIGH gate hide another strategy that passes it.
    priority = {
        "REVERSAL": 5,
        "BREAKOUT": 4,
        "PULLBACK": 3,
        "TREND_FOLLOWING": 2,
        "RANGE_TRADING": 1,
    }

    high_candidates = []
    rejection_reasons = []

    for strategy, direction, candidate in strategy_results:
        score = int(candidate.get("score", 0))

        # Confluence only counts strategies that agree on the same direction.
        same_direction_count = sum(
            1 for name, other_direction, _ in strategy_results
            if other_direction == direction and name != strategy
        )
        if same_direction_count >= 1:
            score += 2

        candidate_metrics = dict(metrics)
        candidate_metrics["mtf_confirmation"] = bool(
            mtf_confirmation(m15c, direction)
        )
        candidate_metrics["confirmation"] = bool(
            entry_trigger_5m(m5c, direction)
        )

        # Avoid continuation entries when the 15M RSI is already stretched.
        if strategy in ("TREND_FOLLOWING", "PULLBACK", "BREAKOUT"):
            if direction == "LONG" and rsi15 >= 78:
                diagnostics[strategy] = "HIGH_FAIL:RSI_TOO_EXTENDED"
                rejection_reasons.append("RSI_TOO_EXTENDED")
                continue
            if direction == "SHORT" and rsi15 <= 22:
                diagnostics[strategy] = "HIGH_FAIL:RSI_TOO_EXTENDED"
                rejection_reasons.append("RSI_TOO_EXTENDED")
                continue

        # Strategy-specific HIGH gates remain strict; this change fixes
        # candidate selection, not by lowering the quality requirements.
        if strategy == "TREND_FOLLOWING":
            high = (
                score >= 8
                and adx1 >= 18
                and candidate_metrics["confirmation"]
            )
        elif strategy == "PULLBACK":
            high = (
                score >= 8
                and candidate_metrics["confirmation"]
                and (
                    near_ema_zone(h1c, direction)
                    or recent_rejection(h1c, direction, 6)
                )
            )
        elif strategy == "BREAKOUT":
            high = (
                score >= 9
                and candidate_metrics["confirmation"]
                and volume
                and adx1 >= 18
            )
        elif strategy == "REVERSAL":
            high = (
                score >= 9
                and candidate_metrics["confirmation"]
                and structure_shift_5m(m5c, direction)
            )
        else:  # RANGE_TRADING
            high = (
                score >= 7
                and candidate_metrics["confirmation"]
                and adx1 <= 24
            )

        if not high:
            diagnostics[strategy] = "HIGH_FAIL:QUALITY_GATE"
            rejection_reasons.append("SIGNAL_QUALITY_TOO_LOW")
            continue

        levels = calculate_trade_levels(h1c, m5c, direction)
        if not levels:
            diagnostics[strategy] = "HIGH_FAIL:INVALID_TRADE_LEVELS"
            rejection_reasons.append("INVALID_TRADE_LEVELS")
            continue

        if not target_reachable(levels, h1c, direction):
            diagnostics[strategy] = "HIGH_FAIL:TP1_BLOCKED"
            rejection_reasons.append("TP1_BLOCKED")
            continue

        high_candidates.append({
            "strategy": strategy,
            "direction": direction,
            "score": score,
            "levels": levels,
            "metrics": candidate_metrics,
            "priority": priority.get(strategy, 0),
        })

    if not high_candidates:
        # Return the most informative final reason while retaining per-strategy
        # diagnostics, including which strategies were valid but failed later.
        if "TP1_BLOCKED" in rejection_reasons:
            final_reason = "TP1_BLOCKED"
        elif "INVALID_TRADE_LEVELS" in rejection_reasons:
            final_reason = "INVALID_TRADE_LEVELS"
        elif "RSI_TOO_EXTENDED" in rejection_reasons and len(set(rejection_reasons)) == 1:
            final_reason = "RSI_TOO_EXTENDED"
        else:
            final_reason = "SIGNAL_QUALITY_TOO_LOW"

        return no_trade(
            final_reason,
            daily_dir,
            h4_dir,
            h1_dir,
            None,
            diagnostics,
            metrics,
        )

    # Prefer the strongest qualified candidate; use strategy priority only as
    # a tie-breaker. A REVERSAL that fails HIGH can no longer block a PULLBACK.
    high_candidates.sort(
        key=lambda item: (item["score"], item["priority"]),
        reverse=True,
    )
    selected = high_candidates[0]
    strategy = selected["strategy"]
    direction = selected["direction"]
    score = selected["score"]
    levels = selected["levels"]
    selected_metrics = selected["metrics"]

    return {
        "signal": direction,
        "direction": direction,
        "score": score,
        "quality": "HIGH",
        "reason": f"VALID_{strategy}",
        "strategies": [
            item["strategy"] for item in high_candidates
            if item["direction"] == direction
        ],
        "strategy": strategy,
        "strategy_diagnostics": diagnostics,
        "daily": daily_dir,
        "4h": h4_dir,
        "1h": h1_dir,
        "15m_rsi": rsi15,
        "adx_1h": adx1,
        "adx_15m": adx15,
        "mtf_confirmation": bool(selected_metrics["mtf_confirmation"]),
        "volume_spike": bool(selected_metrics["volume_spike"]),
        "confirmation": bool(selected_metrics["confirmation"]),
        **levels,
    }


# ============================================================
# COMPATIBILITY ALIASES
# ============================================================

analyze = generate_signal
get_signal = generate_signal
