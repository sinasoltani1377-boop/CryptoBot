# ============================================================
# CryptoBot - Analysis Engine v13
#
# 1H  = Main direction
# 15M = Setup / confirmation
# 5M  = Entry trigger
#
# EXACTLY 5 STRATEGIES:
#   1. TREND_FOLLOWING
#   2. PULLBACK
#   3. BREAKOUT
#   4. REVERSAL
#   5. RANGE_TRADING
#
# v13 goals:
# - closed candles only
# - standard Wilder ADX
# - HIGH signals only
# - strategy-specific quality instead of one overly strict gate
# - stronger 5M confirmation
# - better pullback detection
# - breakout requires volume + hold/retest
# - reversal requires sweep + reclaim + structure shift
# - range has its own scoring model
# - preserve existing signal/level keys for bot.py compatibility
# - SL/TP model intentionally unchanged from v11
# ============================================================

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


# ------------------------------------------------------------
# Basic helpers
# ------------------------------------------------------------

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
        o = safe_float(c.get("open", c.get("o", c.get("Open", 0))))
        h = safe_float(c.get("high", c.get("h", c.get("High", 0))))
        l = safe_float(c.get("low", c.get("l", c.get("Low", 0))))
        cl = safe_float(c.get("close", c.get("c", c.get("Close", 0))))
        v = safe_float(c.get("volume", c.get("v", c.get("Volume", 0))))
        return o, h, l, cl, v

    if isinstance(c, (list, tuple)):
        # Toobit/Binance-like kline: [time, open, high, low, close, volume, ...]
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

    out = []
    for c in candles:
        o, h, l, cl, v = candle_values(c)
        if h <= 0 or l <= 0 or cl <= 0:
            continue
        if h < l:
            continue
        out.append(c)
    return out


def closed(candles: Any, count: int = 2) -> List[Any]:
    """Return candles excluding the currently-forming candle."""
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
    return body(c) / r if r > 0 else 0.0


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


def pct_distance(a: float, b: float) -> float:
    if b == 0:
        return 999.0
    return abs(a - b) / abs(b) * 100.0


# ------------------------------------------------------------
# Indicators
# ------------------------------------------------------------

def ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    k = 2.0 / (period + 1.0)
    e = sum(values[:period]) / period
    for value in values[period:]:
        e = value * k + e * (1.0 - k)
    return e


def ema_series(values: List[float], period: int) -> List[float]:
    if len(values) < period or period <= 0:
        return []
    k = 2.0 / (period + 1.0)
    e = sum(values[:period]) / period
    out = [e]
    for value in values[period:]:
        e = value * k + e * (1.0 - k)
        out.append(e)
    return out


def ema_direction(candles: List[Any]) -> str:
    cls = closes(candles)
    e20 = ema(cls, 20)
    e50 = ema(cls, 50)
    e200 = ema(cls, 200) if len(cls) >= 200 else None
    if e20 is None or e50 is None:
        return "RANGE"
    last = cls[-1]
    if e200 is not None:
        if last > e20 > e50 > e200:
            return "BULLISH"
        if last < e20 < e50 < e200:
            return "BEARISH"
    if last > e20 > e50:
        return "BULLISH"
    if last < e20 < e50:
        return "BEARISH"
    return "RANGE"


def rsi(candles: List[Any], period: int = 14) -> float:
    cls = closes(candles)
    if len(cls) <= period:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(cls)):
        d = cls[i] - cls[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles: List[Any], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs = []
    prev_close = candle_values(candles[0])[3]
    for c in candles[1:]:
        _, h, l, cl, _ = candle_values(c)
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
        prev_close = cl
    if len(trs) < period:
        return 0.0
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def adx(candles: List[Any], period: int = 14) -> float:
    """Standard Wilder ADX."""
    if len(candles) < period * 2 + 1:
        return 0.0

    data = []
    prev_close = candle_values(candles[0])[3]
    for c in candles[1:]:
        _, h, l, cl, _ = candle_values(c)
        up = h - candle_values(candles[data.__len__()])[1] if data else 0.0
        down = candle_values(candles[data.__len__()])[2] - l if data else 0.0
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        plus_dm = up if up > down and up > 0 else 0.0
        minus_dm = down if down > up and down > 0 else 0.0
        data.append((tr, plus_dm, minus_dm))
        prev_close = cl

    if len(data) < period * 2:
        return 0.0

    tr14 = sum(x[0] for x in data[:period])
    plus14 = sum(x[1] for x in data[:period])
    minus14 = sum(x[2] for x in data[:period])

    dx_values = []
    for i in range(period, len(data)):
        tr14 = tr14 - tr14 / period + data[i][0]
        plus14 = plus14 - plus14 / period + data[i][1]
        minus14 = minus14 - minus14 / period + data[i][2]
        if tr14 <= 0:
            continue
        plus_di = 100.0 * plus14 / tr14
        minus_di = 100.0 * minus14 / tr14
        denom = plus_di + minus_di
        dx = 0.0 if denom <= 0 else 100.0 * abs(plus_di - minus_di) / denom
        dx_values.append(dx)

    if len(dx_values) < period:
        return 0.0
    value = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        value = (value * (period - 1) + dx) / period
    return value


def volume_spike(candles: List[Any], multiplier: float = 1.25, lookback: int = 20) -> bool:
    vs = volumes(candles)
    if len(vs) < lookback + 1:
        return False
    current = vs[-1]
    avg = sum(vs[-lookback-1:-1]) / lookback
    return avg > 0 and current >= avg * multiplier


def swing_high(candles: List[Any], strength: int = 2) -> Optional[float]:
    if len(candles) < strength * 2 + 1:
        return None
    hs = highs(candles)
    for i in range(len(hs) - strength - 1, strength - 1, -1):
        x = hs[i]
        if all(x > hs[i - j] for j in range(1, strength + 1)) and all(
            x >= hs[i + j] for j in range(1, strength + 1)
        ):
            return x
    return None


def swing_low(candles: List[Any], strength: int = 2) -> Optional[float]:
    if len(candles) < strength * 2 + 1:
        return None
    ls = lows(candles)
    for i in range(len(ls) - strength - 1, strength - 1, -1):
        x = ls[i]
        if all(x < ls[i - j] for j in range(1, strength + 1)) and all(
            x <= ls[i + j] for j in range(1, strength + 1)
        ):
            return x
    return None


def market_structure(candles: List[Any], lookback: int = 40) -> str:
    arr = candles[-lookback:] if len(candles) > lookback else candles
    if len(arr) < 10:
        return "RANGE"
    hs = highs(arr)
    ls = lows(arr)
    # Compare early and late portions. This is deliberately slower than
    # a one-candle EMA decision and avoids declaring trend from noise.
    mid = len(arr) // 2
    early_h = max(hs[:mid])
    late_h = max(hs[mid:])
    early_l = min(ls[:mid])
    late_l = min(ls[mid:])
    close = closes(arr)[-1]
    atrv = atr(arr, 14)
    if atrv <= 0:
        atrv = max(close * 0.002, 1e-12)
    up = late_h > early_h and late_l > early_l and close >= sum(closes(arr)[-5:]) / 5
    down = late_h < early_h and late_l < early_l and close <= sum(closes(arr)[-5:]) / 5
    if up:
        return "BULLISH"
    if down:
        return "BEARISH"
    return "RANGE"


def trend_strength(candles: List[Any]) -> float:
    return adx(candles, 14)


def direction_from_tf(candles: List[Any]) -> str:
    structure = market_structure(candles)
    if structure in ("BULLISH", "BEARISH"):
        return structure
    return ema_direction(candles)


# ------------------------------------------------------------
# Structure / confirmation helpers
# ------------------------------------------------------------

def mtf_confirmation(m15: List[Any], direction: str) -> bool:
    """15M directional confirmation; intentionally not exact EMA equality."""
    if len(m15) < 30:
        return False
    cls = closes(m15)
    e20 = ema(cls, 20)
    e50 = ema(cls, 50)
    if e20 is None or e50 is None:
        return False
    recent = m15[-3:]
    if direction == "LONG":
        bullish_count = sum(1 for c in recent if bullish(c))
        close = cls[-1]
        return bullish_count >= 2 and close >= e20 and close >= e50 * 0.998
    if direction == "SHORT":
        bearish_count = sum(1 for c in recent if bearish(c))
        close = cls[-1]
        return bearish_count >= 2 and close <= e20 and close <= e50 * 1.002
    return False


def strong_confirmation_5m(m5: List[Any], direction: str) -> bool:
    """Require a real 5M push, not merely a green/red candle."""
    if len(m5) < 8:
        return False
    a, b, c = m5[-3], m5[-2], m5[-1]
    _, ah, al, ac, _ = candle_values(a)
    _, bh, bl, bc, _ = candle_values(b)
    _, ch, cl, cc, _ = candle_values(c)
    if direction == "LONG":
        return (
            bullish(c)
            and bullish(b)
            and body_ratio(c) >= 0.45
            and cc > bh
            and cc > ac
            and cl >= al
        )
    if direction == "SHORT":
        return (
            bearish(c)
            and bearish(b)
            and body_ratio(c) >= 0.45
            and cc < bl
            and cc < ac
            and ch <= ah
        )
    return False


def rejection(c: Any, direction: str) -> bool:
    r = candle_range(c)
    if r <= 0:
        return False
    if direction == "LONG":
        return lower_wick(c) >= body(c) * 0.8 and lower_wick(c) / r >= 0.25
    if direction == "SHORT":
        return upper_wick(c) >= body(c) * 0.8 and upper_wick(c) / r >= 0.25
    return False


def recent_rejection(candles: List[Any], direction: str, lookback: int = 4) -> bool:
    return any(rejection(c, direction) for c in candles[-lookback:])


def near_ema_zone(h1: List[Any], direction: str) -> bool:
    cls = closes(h1)
    if len(cls) < 50:
        return False
    price = cls[-1]
    e20 = ema(cls, 20)
    e50 = ema(cls, 50)
    atrv = atr(h1, 14)
    if not e20 or not e50 or not atrv:
        return False
    zone = max(atrv * 0.55, price * 0.004)
    if direction == "LONG":
        return min(abs(price - e20), abs(price - e50)) <= zone and price >= min(e20, e50) * 0.995
    if direction == "SHORT":
        return min(abs(price - e20), abs(price - e50)) <= zone and price <= max(e20, e50) * 1.005
    return False


def pullback_detected(h1: List[Any], direction: str) -> bool:
    if len(h1) < 12:
        return False
    recent = h1[-8:]
    cls = closes(h1)
    e20 = ema(cls, 20)
    e50 = ema(cls, 50)
    if e20 is None or e50 is None:
        return False
    zone = max(atr(h1, 14) * 0.75, cls[-1] * 0.005)
    if direction == "LONG":
        touched = any(
            abs(candle_values(c)[2] - e20) <= zone
            or abs(candle_values(c)[2] - e50) <= zone
            for c in recent
        )
        recovery = closes(recent)[-1] > e20
        return touched and recovery
    if direction == "SHORT":
        touched = any(
            abs(candle_values(c)[1] - e20) <= zone
            or abs(candle_values(c)[1] - e50) <= zone
            for c in recent
        )
        recovery = closes(recent)[-1] < e20
        return touched and recovery
    return False


def structure_shift_5m(m5: List[Any], direction: str) -> bool:
    if len(m5) < 12:
        return False
    recent = m5[-8:]
    if direction == "LONG":
        prior_high = max(highs(recent[:-2]))
        return closes(recent)[-1] > prior_high and bullish(recent[-1])
    if direction == "SHORT":
        prior_low = min(lows(recent[:-2]))
        return closes(recent)[-1] < prior_low and bearish(recent[-1])
    return False


def local_breakout(m15: List[Any], direction: str, lookback: int = 20) -> Tuple[bool, float]:
    if len(m15) < lookback + 2:
        return False, 0.0
    prev = m15[-lookback-1:-1]
    last = m15[-1]
    level_high = max(highs(prev))
    level_low = min(lows(prev))
    close = candle_values(last)[3]
    if direction == "LONG":
        return close > level_high, level_high
    if direction == "SHORT":
        return close < level_low, level_low
    return False, 0.0


def breakout_hold(m15: List[Any], direction: str, level: float) -> bool:
    if level <= 0 or len(m15) < 4:
        return False
    recent = m15[-3:]
    if direction == "LONG":
        return all(candle_values(c)[3] >= level * 0.998 for c in recent)
    if direction == "SHORT":
        return all(candle_values(c)[3] <= level * 1.002 for c in recent)
    return False


def sweep_reclaim(m15: List[Any], direction: str) -> bool:
    if len(m15) < 12:
        return False
    prior = m15[-11:-1]
    last = m15[-1]
    prior_high = max(highs(prior))
    prior_low = min(lows(prior))
    _, h, l, cl, _ = candle_values(last)
    if direction == "LONG":
        return l < prior_low and cl > prior_low and bullish(last)
    if direction == "SHORT":
        return h > prior_high and cl < prior_high and bearish(last)
    return False


def range_info(h1: List[Any]) -> Tuple[bool, float, float]:
    if len(h1) < 30:
        return False, 0.0, 0.0
    recent = h1[-24:]
    hi = max(highs(recent))
    lo = min(lows(recent))
    width = hi - lo
    price = closes(recent)[-1]
    if width <= 0 or price <= 0:
        return False, hi, lo
    atrv = atr(recent, 14)
    # Range should not be abnormally wide relative to volatility.
    is_range = atrv > 0 and width <= atrv * 6.0
    return is_range, hi, lo


def near_range_boundary(h1: List[Any], direction: str, hi: float, lo: float) -> bool:
    price = closes(h1)[-1]
    width = hi - lo
    if width <= 0:
        return False
    edge = width * 0.20
    if direction == "LONG":
        return price <= lo + edge
    if direction == "SHORT":
        return price >= hi - edge
    return False


# ------------------------------------------------------------
# Strategy detectors
# ------------------------------------------------------------

def detect_trend_following(h1: List[Any], m15: List[Any], m5: List[Any], direction: str) -> Dict[str, Any]:
    if direction not in ("LONG", "SHORT"):
        return {"valid": False, "reason": "NO_DIRECTION"}
    h1_dir = direction_from_tf(h1)
    ema_dir = ema_direction(h1)
    adx1 = adx(h1)
    mtf = mtf_confirmation(m15, direction)
    trigger = strong_confirmation_5m(m5, direction)
    if h1_dir != ("BULLISH" if direction == "LONG" else "BEARISH"):
        return {"valid": False, "reason": "H1_STRUCTURE"}
    if ema_dir not in ("BULLISH", "BEARISH"):
        return {"valid": False, "reason": "H1_EMA"}
    if adx1 < 20:
        return {"valid": False, "reason": "ADX_LOW"}
    # v13: MTF is a quality bonus, not an absolute gate.
    if not trigger:
        return {"valid": False, "reason": "5M_CONFIRMATION"}
    score = 0
    if ema_dir == ("BULLISH" if direction == "LONG" else "BEARISH"):
        score += 2
    if adx1 >= 25:
        score += 2
    elif adx1 >= 20:
        score += 1
    if mtf:
        score += 2
    if strong_confirmation_5m(m5, direction):
        score += 2
    if pullback_detected(h1, direction):
        score += 1
    return {"valid": True, "reason": "VALID", "score": score, "mtf": mtf}


def detect_pullback(h1: List[Any], m15: List[Any], m5: List[Any], direction: str) -> Dict[str, Any]:
    if direction not in ("LONG", "SHORT"):
        return {"valid": False, "reason": "NO_DIRECTION"}
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    if direction_from_tf(h1) != expected:
        return {"valid": False, "reason": "H1_STRUCTURE"}
    if ema_direction(h1) != expected:
        return {"valid": False, "reason": "H1_EMA"}
    if not pullback_detected(h1, direction):
        return {"valid": False, "reason": "NO_PULLBACK_ZONE"}
    if not (recent_rejection(h1, direction, 5) or near_ema_zone(h1, direction)):
        return {"valid": False, "reason": "NO_REJECTION"}
    trigger = strong_confirmation_5m(m5, direction)
    if not trigger:
        return {"valid": False, "reason": "5M_CONFIRMATION"}
    mtf = mtf_confirmation(m15, direction)
    score = 0
    score += 2
    if near_ema_zone(h1, direction):
        score += 2
    if recent_rejection(h1, direction, 5):
        score += 2
    if mtf:
        score += 2
    score += 2  # strong 5M confirmation is mandatory
    return {"valid": True, "reason": "VALID", "score": score, "mtf": mtf}


def detect_breakout(h1: List[Any], m15: List[Any], m5: List[Any], direction: str) -> Dict[str, Any]:
    ok, level = local_breakout(m15, direction, 20)
    if not ok:
        return {"valid": False, "reason": "NO_BREAKOUT"}
    if not volume_spike(m15, 1.20, 20):
        return {"valid": False, "reason": "NO_VOLUME"}
    last = m15[-1]
    if body_ratio(last) < 0.50:
        return {"valid": False, "reason": "WEAK_BREAKOUT_CANDLE"}
    if not breakout_hold(m15, direction, level):
        return {"valid": False, "reason": "NO_HOLD"}
    if not strong_confirmation_5m(m5, direction):
        return {"valid": False, "reason": "5M_CONFIRMATION"}
    mtf = mtf_confirmation(m15, direction)
    score = 3 + 2 + 2  # breakout + volume + hold
    if mtf:
        score += 2
    if adx(h1) >= 22:
        score += 1
    return {"valid": True, "reason": "VALID", "score": score, "mtf": mtf, "level": level}


def detect_reversal(h1: List[Any], m15: List[Any], m5: List[Any], direction: str) -> Dict[str, Any]:
    if not sweep_reclaim(m15, direction):
        return {"valid": False, "reason": "NO_SWEEP"}
    last = m15[-1]
    if body_ratio(last) < 0.40:
        return {"valid": False, "reason": "WEAK_RECLAIM"}
    if not structure_shift_5m(m5, direction):
        return {"valid": False, "reason": "NO_5M_STRUCTURE_SHIFT"}
    score = 4 + 3 + 2
    if mtf_confirmation(m15, direction):
        score += 1
    return {"valid": True, "reason": "VALID", "score": score, "mtf": mtf_confirmation(m15, direction)}


def detect_range(h1: List[Any], m5: List[Any], direction: str) -> Dict[str, Any]:
    ok, hi, lo = range_info(h1)
    if not ok:
        return {"valid": False, "reason": "NOT_RANGE"}
    if adx(h1) > 22:
        return {"valid": False, "reason": "ADX_TOO_HIGH"}
    if not near_range_boundary(h1, direction, hi, lo):
        return {"valid": False, "reason": "NOT_AT_BOUNDARY"}
    if not recent_rejection(h1, direction, 5):
        return {"valid": False, "reason": "NO_REJECTION"}
    if not strong_confirmation_5m(m5, direction):
        return {"valid": False, "reason": "5M_CONFIRMATION"}
    score = 3 + 3 + 2
    if adx(h1) <= 18:
        score += 1
    return {"valid": True, "reason": "VALID", "score": score, "mtf": False}


# ------------------------------------------------------------
# Context and trade levels
# ------------------------------------------------------------

def context_allows(strategy: str, daily: str, h4: str, h1: str, direction: str) -> bool:
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    # Do not allow a trend trade directly against a strongly confirmed H4 trend.
    if strategy in ("TREND_FOLLOWING", "PULLBACK"):
        if h4 in ("BULLISH", "BEARISH") and h4 != expected:
            return False
    # Breakout against H4 is allowed only when H4 is RANGE/unclear.
    if strategy == "BREAKOUT":
        if h4 in ("BULLISH", "BEARISH") and h4 != expected:
            return False
    # Reversal is allowed against higher timeframe only when it has a real sweep.
    if strategy == "REVERSAL":
        return True
    # Range strategy should not fight a strong H4 trend.
    if strategy == "RANGE_TRADING":
        if h4 in ("BULLISH", "BEARISH") and h4 != expected:
            return False
    return True


def calculate_trade_levels(h1: List[Any], m5: List[Any], direction: str) -> Optional[Dict[str, float]]:
    """v13: intentionally same level model as v11."""
    if direction not in ("LONG", "SHORT") or not h1 or not m5:
        return None
    entry = closes(m5)[-1]
    atr1 = atr(h1, 14)
    if entry <= 0 or atr1 <= 0:
        return None

    sh = swing_high(h1, 2)
    slw = swing_low(h1, 2)

    if direction == "LONG":
        base_sl = (slw - 0.35 * atr1) if slw else (entry - 1.2 * atr1)
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
        base_sl = (sh + 0.35 * atr1) if sh else (entry + 1.2 * atr1)
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


def target_reachable(levels: Dict[str, float], h1: List[Any], direction: str) -> bool:
    # Conservative sanity check: do not reject a setup just because an old
    # distant swing exists; only reject an immediate opposing barrier.
    entry = levels["entry"]
    tp1 = levels["tp1"]
    recent = h1[-25:] if len(h1) >= 25 else h1
    if direction == "LONG":
        barriers = [x for x in highs(recent[:-1]) if x > entry]
        if barriers and min(barriers) < tp1 * 0.995:
            return False
    else:
        barriers = [x for x in lows(recent[:-1]) if x < entry]
        if barriers and max(barriers) > tp1 * 1.005:
            return False
    return True


# ------------------------------------------------------------
# Main signal engine
# ------------------------------------------------------------

def no_trade(
    reason: str,
    daily: str = "RANGE",
    h4: str = "RANGE",
    h1: str = "RANGE",
    direction: Optional[str] = None,
    diagnostics: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return {
        "signal": "NO_TRADE",
        "direction": direction,
        "score": 0,
        "quality": "LOW",
        "reason": reason,
        "strategies": [],
        "strategy": None,
        "strategy_diagnostics": diagnostics or {},
        "daily": daily,
        "4h": h4,
        "1h": h1,
    }


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

    daily_dir = direction_from_tf(d)
    h4_dir = direction_from_tf(h4c)
    h1_dir = direction_from_tf(h1c)

    if h1_dir == "BULLISH":
        direction = "LONG"
    elif h1_dir == "BEARISH":
        direction = "SHORT"
    else:
        # Range can still produce a valid range/reversal direction from 5M.
        direction = None
        m5e = ema_direction(m5c)
        if m5e == "BULLISH":
            direction = "LONG"
        elif m5e == "BEARISH":
            direction = "SHORT"

    if direction is None:
        return no_trade("NO_DIRECTION", daily_dir, h4_dir, h1_dir)

    diagnostics: Dict[str, str] = {}

    detectors = [
        ("TREND_FOLLOWING", lambda: detect_trend_following(h1c, m15c, m5c, direction)),
        ("PULLBACK", lambda: detect_pullback(h1c, m15c, m5c, direction)),
        ("BREAKOUT", lambda: detect_breakout(h1c, m15c, m5c, direction)),
        ("REVERSAL", lambda: detect_reversal(h1c, m15c, m5c, direction)),
        ("RANGE_TRADING", lambda: detect_range(h1c, m5c, direction)),
    ]

    valid = []
    for name, fn in detectors:
        try:
            result = fn()
        except Exception as exc:
            result = {"valid": False, "reason": f"ERROR_{type(exc).__name__}"}
        if result.get("valid"):
            if context_allows(name, daily_dir, h4_dir, h1_dir, direction):
                valid.append((name, result))
                diagnostics[name] = "VALID"
            else:
                diagnostics[name] = "FAIL:HTF_CONTEXT"
        else:
            diagnostics[name] = f"FAIL:{result.get('reason', 'UNKNOWN')}"

    if not valid:
        return no_trade(
            "NO_VALID_STRATEGY",
            daily_dir,
            h4_dir,
            h1_dir,
            direction,
            diagnostics,
        )

    # Highest priority first. If multiple strategies agree, add confluence.
    priority = {
        "REVERSAL": 5,
        "BREAKOUT": 4,
        "PULLBACK": 3,
        "TREND_FOLLOWING": 2,
        "RANGE_TRADING": 1,
    }
    valid.sort(key=lambda x: (priority.get(x[0], 0), x[1].get("score", 0)), reverse=True)
    strategy, chosen = valid[0]
    score = int(chosen.get("score", 0))

    # Confluence from multiple independent strategies is valuable, but we do
    # not use it to rescue a weak base setup.
    if len(valid) >= 2:
        score += 2

    rsi15 = rsi(m15c)
    adx1 = adx(h1c)
    adx15 = adx(m15c)
    vol = volume_spike(m15c, 1.20, 20)
    confirmation = strong_confirmation_5m(m5c, direction)
    mtf = mtf_confirmation(m15c, direction)

    # Avoid chasing already extended momentum. This is intentionally not a
    # generic RSI gate for every setup.
    if strategy in ("TREND_FOLLOWING", "PULLBACK", "BREAKOUT"):
        if direction == "LONG" and rsi15 >= 76:
            return no_trade("RSI_TOO_EXTENDED", daily_dir, h4_dir, h1_dir, direction, diagnostics)
        if direction == "SHORT" and rsi15 <= 24:
            return no_trade("RSI_TOO_EXTENDED", daily_dir, h4_dir, h1_dir, direction, diagnostics)

    # HIGH criteria are strategy-specific. We deliberately do NOT simply say
    # score >= 8 because that recreated the old false-HIGH problem.
    high = False
    if strategy == "TREND_FOLLOWING":
        high = score >= 10 and confirmation and adx1 >= 22 and (mtf or adx15 >= 20)
    elif strategy == "PULLBACK":
        high = score >= 10 and confirmation and near_ema_zone(h1c, direction)
    elif strategy == "BREAKOUT":
        high = score >= 10 and confirmation and vol and adx1 >= 20
    elif strategy == "REVERSAL":
        high = score >= 10 and confirmation and structure_shift_5m(m5c, direction)
    elif strategy == "RANGE_TRADING":
        # Range has a lower raw score because its scoring model is different.
        high = score >= 9 and confirmation and adx1 <= 22

    if not high:
        return no_trade(
            "SIGNAL_QUALITY_TOO_LOW",
            daily_dir,
            h4_dir,
            h1_dir,
            direction,
            diagnostics,
        )

    levels = calculate_trade_levels(h1c, m5c, direction)
    if not levels:
        return no_trade(
            "INVALID_TRADE_LEVELS",
            daily_dir,
            h4_dir,
            h1_dir,
            direction,
            diagnostics,
        )

    if not target_reachable(levels, h1c, direction):
        return no_trade(
            "TP1_BLOCKED",
            daily_dir,
            h4_dir,
            h1_dir,
            direction,
            diagnostics,
        )

    return {
        "signal": direction,
        "direction": direction,
        "score": score,
        "quality": "HIGH",
        "reason": f"VALID_{strategy}",
        "strategies": [strategy],
        "strategy": strategy,
        "strategy_diagnostics": diagnostics,
        "daily": daily_dir,
        "4h": h4_dir,
        "1h": h1_dir,
        "15m_rsi": round(rsi15, 2),
        "adx_1h": round(adx1, 2),
        "adx_15m": round(adx15, 2),
        "mtf_confirmation": bool(mtf),
        "volume_spike": bool(vol),
        "confirmation": bool(confirmation),
        **levels,
    }


# Common aliases kept for compatibility with older imports.
analyze = generate_signal
get_signal = generate_signal
