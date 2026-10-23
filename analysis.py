# ============================================================
# CryptoBot - Analysis Engine v22
#
# v22: Market Regime Switch
#   - If ADX < 22 (Ranging): Only RANGE_TRADING, BB_REVERSION, REVERSAL
#   - If ADX >= 22 (Trending): Only TREND_FOLLOWING, PULLBACK, BREAKOUT, REVERSAL
#   - Saves compute, stops bot from buying fake breakouts in dead markets.
# ============================================================

from __future__ import annotations

import logging
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
            return (safe_float(c[1]), safe_float(c[2]), safe_float(c[3]),
                    safe_float(c[4]), safe_float(c[5]))
        if len(c) >= 5:
            return (safe_float(c[0]), safe_float(c[1]), safe_float(c[2]),
                    safe_float(c[3]), safe_float(c[4]))
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
        _, h, l, cl, _ = candle_values(c)
        if h <= 0 or l <= 0 or cl <= 0 or h < l:
            continue
        result.append(c)
    return result


def closed(candles: Any, count: int = 2) -> List[Any]:
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


def ema_series(values: List[float], period: int) -> List[Optional[float]]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1.0)
    result: List[Optional[float]] = [None] * (period - 1)
    v = sum(values[:period]) / period
    result.append(v)
    for x in values[period:]:
        v = x * k + v * (1 - k)
        result.append(v)
    return result


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
    gains, losses = [], []
    for i in range(1, len(cls)):
        diff = cls[i] - cls[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
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
    if len(candles) < period * 2 + 1:
        return 0.0
    tr_values, plus_dm, minus_dm = [], [], []
    prev_close = candle_values(candles[0])[3]
    for i in range(1, len(candles)):
        _, h, l, cl, _ = candle_values(candles[i])
        _, ph, pl, _, _ = candle_values(candles[i - 1])
        up = h - ph
        down = pl - l
        plus = up if up > down and up > 0 else 0.0
        minus = down if down > up and down > 0 else 0.0
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        tr_values.append(tr)
        plus_dm.append(plus)
        minus_dm.append(minus)
        prev_close = cl
    if len(tr_values) < period * 2:
        return 0.0
    tr14 = sum(tr_values[:period])
    plus14 = sum(plus_dm[:period])
    minus14 = sum(minus_dm[:period])
    dxs = []
    for i in range(period, len(tr_values)):
        tr14 = tr14 - tr14 / period + tr_values[i]
        plus14 = plus14 - plus14 / period + plus_dm[i]
        minus14 = minus14 - minus14 / period + minus_dm[i]
        if tr14 <= 0:
            continue
        pdi = 100.0 * plus14 / tr14
        mdi = 100.0 * minus14 / tr14
        denom = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / denom if denom > 0 else 0.0
        dxs.append(dx)
    if len(dxs) < period:
        return 0.0
    value = sum(dxs[:period]) / period
    for dx in dxs[period:]:
        value = (value * (period - 1) + dx) / period
    return value


def volume_spike(candles: List[Any], multiplier: float = 1.10, lookback: int = 20) -> bool:
    vs = volumes(candles)
    if len(vs) < lookback + 1:
        return False
    avg = sum(vs[-lookback - 1:-1]) / lookback
    if avg <= 0:
        return False
    return vs[-1] >= avg * multiplier


def bollinger_bands(candles: List[Any], period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float]:
    cls = closes(candles)
    if len(cls) < period:
        return 0.0, 0.0, 0.0
    recent_closes = cls[-period:]
    sma = sum(recent_closes) / period
    variance = sum((x - sma) ** 2 for x in recent_closes) / period
    std = math.sqrt(variance)
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, sma, lower


# ============================================================
# MARKET STRUCTURE
# ============================================================

def swing_high(candles: List[Any], strength: int = 2) -> Optional[float]:
    if len(candles) < strength * 2 + 1:
        return None
    hs = highs(candles)
    for i in range(len(hs) - strength - 1, strength - 1, -1):
        v = hs[i]
        if all(v > hs[i - j] for j in range(1, strength + 1)) and \
           all(v >= hs[i + j] for j in range(1, strength + 1)):
            return v
    return None


def swing_low(candles: List[Any], strength: int = 2) -> Optional[float]:
    if len(candles) < strength * 2 + 1:
        return None
    ls = lows(candles)
    for i in range(len(ls) - strength - 1, strength - 1, -1):
        v = ls[i]
        if all(v < ls[i - j] for j in range(1, strength + 1)) and \
           all(v <= ls[i + j] for j in range(1, strength + 1)):
            return v
    return None


def market_structure(candles: List[Any], lookback: int = 40) -> str:
    arr = candles[-lookback:] if len(candles) > lookback else candles
    if len(arr) < 20:
        return "RANGE"
    hs, ls, cls = highs(arr), lows(arr), closes(arr)
    mid = len(arr) // 2
    early_high, late_high = max(hs[:mid]), max(hs[mid:])
    early_low, late_low = min(ls[:mid]), min(ls[mid:])
    recent_atr = atr(arr, 14)
    if recent_atr <= 0:
        return "RANGE"
    bull = (
        late_high > early_high and late_low > early_low
        and cls[-1] > cls[mid]
        and (cls[-1] - cls[mid]) >= recent_atr * 0.25
    )
    bear = (
        late_high < early_high and late_low < early_low
        and cls[-1] < cls[mid]
        and (cls[mid] - cls[-1]) >= recent_atr * 0.25
    )
    full_closes = closes(candles)
    if len(full_closes) >= 200:
        e200 = ema(full_closes, 200)
        if e200 is not None:
            if bull and full_closes[-1] < e200:
                bull = False
            if bear and full_closes[-1] > e200:
                bear = False
    if bull:
        return "BULLISH"
    if bear:
        return "BEARISH"
    return "RANGE"


# ============================================================
# CONFIRMATION
# ============================================================

def strong_confirmation_5m(m5: List[Any], direction: str) -> bool:
    if len(m5) < 8:
        return False
    last = m5[-1]
    prev = m5[-2]
    recent = m5[-7:-1]
    _, ph, pl, _, _ = candle_values(prev)
    _, _, _, lc, _ = candle_values(last)
    if direction == "LONG":
        return (
            (bullish(prev) and bullish(last)
             and body_ratio(last) >= 0.35 and lc > ph)
            or (bullish(last) and body_ratio(last) >= 0.45
                and lc > max(highs(recent)))
        )
    if direction == "SHORT":
        return (
            (bearish(prev) and bearish(last)
             and body_ratio(last) >= 0.35 and lc < pl)
            or (bearish(last) and body_ratio(last) >= 0.45
                and lc < min(lows(recent)))
        )
    return False


def entry_trigger_5m(m5: List[Any], direction: str) -> bool:
    if strong_confirmation_5m(m5, direction):
        return True
    if len(m5) < 6:
        return False
    recent = m5[-4:-1]
    last = m5[-1]
    lc = candle_values(last)[3]
    if direction == "LONG":
        return bullish(last) and body_ratio(last) >= 0.30 and lc > max(highs(recent))
    if direction == "SHORT":
        return bearish(last) and body_ratio(last) >= 0.30 and lc < min(lows(recent))
    return False


def htf_breakout_confirm(h1: List[Any], direction: str,
                         lookback: int = 20, recent_window: int = 5) -> bool:
    if len(h1) < lookback + recent_window + 1:
        return False
    hs, ls, cls = highs(h1), lows(h1), closes(h1)
    n = len(h1)
    lh = max(hs[n - lookback - recent_window : n - recent_window])
    ll = min(ls[n - lookback - recent_window : n - recent_window])
    rc = cls[n - recent_window:]
    if direction == "LONG":
        return any(c > lh for c in rc)
    if direction == "SHORT":
        return any(c < ll for c in rc)
    return False


def not_far_from_breakout(h1: List[Any], direction: str,
                          lookback: int = 20, recent_window: int = 5,
                          max_atr: float = 0.7) -> bool:
    if len(h1) < lookback + recent_window + 1:
        return True
    hs, ls, cls = highs(h1), lows(h1), closes(h1)
    n = len(h1)
    price = cls[-1]
    atr_1h = atr(h1, 14)
    if atr_1h <= 0:
        return True
    if direction == "LONG":
        level = max(hs[n - lookback - recent_window : n - recent_window])
        distance = price - level
        return 0 <= distance <= max_atr * atr_1h
    if direction == "SHORT":
        level = min(ls[n - lookback - recent_window : n - recent_window])
        distance = level - price
        return 0 <= distance <= max_atr * atr_1h
    return True


# ============================================================
# CANDLE PATTERNS
# ============================================================

def is_doji(candle: Any, threshold: float = 0.20) -> bool:
    r = candle_range(candle)
    if r <= 0:
        return False
    return body(candle) / r <= threshold


def bull_engulfing(prev: Any, curr: Any) -> bool:
    po, _, _, pc, _ = candle_values(prev)
    co, _, _, cc, _ = candle_values(curr)
    return (pc < po and cc > co and co <= pc and cc >= po
            and (cc - co) > (po - pc))


def bear_engulfing(prev: Any, curr: Any) -> bool:
    po, _, _, pc, _ = candle_values(prev)
    co, _, _, cc, _ = candle_values(curr)
    return (pc > po and cc < co and co >= pc and cc <= po
            and (co - cc) > (pc - po))


def is_morning_star(c1: Any, c2: Any, c3: Any) -> bool:
    if not bearish(c1) or not bullish(c3):
        return False
    if not is_doji(c2, 0.30):
        return False
    o1, _, _, c1c, _ = candle_values(c1)
    o3, _, _, c3c, _ = candle_values(c3)
    midpoint = (o1 + c1c) / 2
    return c3c > midpoint and c3c > o3


def is_evening_star(c1: Any, c2: Any, c3: Any) -> bool:
    if not bullish(c1) or not bearish(c3):
        return False
    if not is_doji(c2, 0.30):
        return False
    o1, _, _, c1c, _ = candle_values(c1)
    o3, _, _, c3c, _ = candle_values(c3)
    midpoint = (o1 + c1c) / 2
    return c3c < midpoint and c3c < o3


def is_inside_bar(prev: Any, curr: Any) -> bool:
    _, ph, pl, _, _ = candle_values(prev)
    _, ch, cl, _, _ = candle_values(curr)
    return ch <= ph and cl >= pl


def bullish_reversal_pattern(candles_ctx: List[Any]) -> bool:
    if len(candles_ctx) < 2:
        return False
    last = candles_ctx[-1]
    prev = candles_ctx[-2]
    r = candle_range(last)
    if r > 0 and lower_wick(last) / r >= 0.40 and lower_wick(last) >= body(last) * 0.8:
        return True
    if bull_engulfing(prev, last):
        return True
    if is_doji(last, 0.20) and (lower_wick(last) / r >= 0.45 if r > 0 else False):
        return True
    if len(candles_ctx) >= 3:
        if is_morning_star(candles_ctx[-3], candles_ctx[-2], candles_ctx[-1]):
            return True
        if is_inside_bar(candles_ctx[-3], candles_ctx[-2]):
            _, _, _, last_close, _ = candle_values(last)
            _, _, _, inner_close, _ = candle_values(candles_ctx[-2])
            if last_close > inner_close and bullish(last):
                return True
    return False


def bearish_reversal_pattern(candles_ctx: List[Any]) -> bool:
    if len(candles_ctx) < 2:
        return False
    last = candles_ctx[-1]
    prev = candles_ctx[-2]
    r = candle_range(last)
    if r > 0 and upper_wick(last) / r >= 0.40 and upper_wick(last) >= body(last) * 0.8:
        return True
    if bear_engulfing(prev, last):
        return True
    if is_doji(last, 0.20) and (upper_wick(last) / r >= 0.45 if r > 0 else False):
        return True
    if len(candles_ctx) >= 3:
        if is_evening_star(candles_ctx[-3], candles_ctx[-2], candles_ctx[-1]):
            return True
        if is_inside_bar(candles_ctx[-3], candles_ctx[-2]):
            _, _, _, last_close, _ = candle_values(last)
            _, _, _, inner_close, _ = candle_values(candles_ctx[-2])
            if last_close < inner_close and bearish(last):
                return True
    return False


def rejection(candle: Any, direction: str, prev_candle: Optional[Any] = None) -> bool:
    r = candle_range(candle)
    if r <= 0:
        return False
    if direction == "LONG":
        pin = (lower_wick(candle) >= body(candle) * 0.60
               and lower_wick(candle) / r >= 0.20
               and candle_values(candle)[3] >= candle_values(candle)[0])
        if pin:
            return True
        if prev_candle is not None and bull_engulfing(prev_candle, candle):
            return True
        return False
    if direction == "SHORT":
        pin = (upper_wick(candle) >= body(candle) * 0.60
               and upper_wick(candle) / r >= 0.20
               and candle_values(candle)[3] <= candle_values(candle)[0])
        if pin:
            return True
        if prev_candle is not None and bear_engulfing(prev_candle, candle):
            return True
        return False
    return False


def recent_rejection(candles: List[Any], direction: str, lookback: int = 6) -> bool:
    return any(rejection(c, direction) for c in candles[-lookback:])


# ============================================================
# FIBONACCI + IMPULSE LEG
# ============================================================

def find_last_impulse(h1: List[Any], direction: str,
                      lookback: int = 50) -> Tuple[Optional[float], Optional[float]]:
    arr = h1[-lookback:] if len(h1) > lookback else h1
    if len(arr) < 15:
        return None, None
    hs, ls = highs(arr), lows(arr)
    if direction == "LONG":
        peak_idx = hs.index(max(hs))
        if peak_idx < 3:
            return None, None
        before_peak = ls[:peak_idx]
        trough_idx = before_peak.index(min(before_peak))
        return before_peak[trough_idx], hs[peak_idx]
    else:
        trough_idx = ls.index(min(ls))
        if trough_idx < 3:
            return None, None
        before_trough = hs[:trough_idx]
        peak_idx = before_trough.index(max(before_trough))
        return before_trough[peak_idx], ls[trough_idx]


def fib_pullback_zone(h1: List[Any], direction: str,
                      low_pct: float = 0.35, high_pct: float = 0.72) -> bool:
    impulse_low, impulse_high = find_last_impulse(h1, direction)
    if impulse_low is None or impulse_high is None:
        return False
    rng = impulse_high - impulse_low
    if rng <= 0:
        return False
    price = closes(h1)[-1]
    if direction == "LONG":
        retr = (impulse_high - price) / rng
    else:
        retr = (price - impulse_low) / rng
    return low_pct <= retr <= high_pct


def fib_golden_zone(h1: List[Any], direction: str) -> bool:
    impulse_low, impulse_high = find_last_impulse(h1, direction)
    if impulse_low is None or impulse_high is None:
        return False
    rng = impulse_high - impulse_low
    if rng <= 0:
        return False
    price = closes(h1)[-1]
    if direction == "LONG":
        retr = (impulse_high - price) / rng
    else:
        retr = (price - impulse_low) / rng
    return 0.382 <= retr <= 0.618


# ============================================================
# SWING LOW ZONE
# ============================================================

def near_swing_low_zone(h1: List[Any], direction: str,
                        lookback: int = 20, atr_buffer: float = 0.6) -> bool:
    arr = h1[-lookback:] if len(h1) > lookback else h1
    if len(arr) < 6:
        return False
    atr1 = atr(h1)
    if atr1 <= 0:
        return False
    price = closes(h1)[-1]
    if direction == "LONG":
        sl = swing_low(arr, 2)
        if sl is None:
            return False
        return abs(price - sl) <= atr_buffer * atr1 and price >= sl * 0.995
    else:
        sh = swing_high(arr, 2)
        if sh is None:
            return False
        return abs(price - sh) <= atr_buffer * atr1 and price <= sh * 1.005


# ============================================================
# PULLBACK DETECTION
# ============================================================

def near_ema_zone(h1: List[Any], direction: str) -> bool:
    cls = closes(h1)
    e20 = ema(cls, 20)
    e50 = ema(cls, 50)
    atr1 = atr(h1)
    if e20 is None or e50 is None or atr1 <= 0:
        return False
    price = cls[-1]
    zone = max(atr1 * 0.50, price * 0.003)
    distance = min(abs(price - e20), abs(price - e50))
    if distance > zone:
        return False
    if direction == "LONG":
        return price >= e50 * 0.995 and price <= e20 * 1.03
    if direction == "SHORT":
        return price <= e50 * 1.005 and price >= e20 * 0.97
    return False


def pullback_detected(h1: List[Any], direction: str) -> bool:
    if len(h1) < 25:
        return False
    cls = closes(h1)
    e20 = ema(cls, 20)
    e50 = ema(cls, 50)
    atr1 = atr(h1)
    if e20 is None or e50 is None or atr1 <= 0:
        return False
    zone = max(atr1 * 0.50, cls[-1] * 0.003)
    recent = h1[-8:]
    if direction == "LONG":
        touched = any(candle_values(c)[2] <= max(e20, e50) + zone for c in recent)
        return touched and cls[-1] > e20
    if direction == "SHORT":
        touched = any(candle_values(c)[1] >= min(e20, e50) - zone for c in recent)
        return touched and cls[-1] < e20
    return False


def pullback_duration_ok(h1: List[Any], direction: str,
                         min_bars: int = 3, max_bars: int = 10) -> bool:
    lookback = max_bars * 3
    arr = h1[-lookback:] if len(h1) > lookback else h1
    if len(arr) < min_bars + 2:
        return False
    if direction == "LONG":
        peak_idx = highs(arr).index(max(highs(arr)))
        bars_since_peak = len(arr) - peak_idx - 1
    else:
        trough_idx = lows(arr).index(min(lows(arr)))
        bars_since_peak = len(arr) - trough_idx - 1
    return min_bars <= bars_since_peak <= max_bars


def pullback_depth_ok(h1: List[Any], direction: str,
                      lookback: int = 30, min_pct: float = 0.35,
                      max_pct: float = 0.78) -> bool:
    arr = h1[-lookback:] if len(h1) > lookback else h1
    if len(arr) < 10:
        return True
    hs, ls, cls = highs(arr), lows(arr), closes(arr)
    price = cls[-1]
    sh, sl = max(hs), min(ls)
    rng = sh - sl
    if rng <= 0:
        return True
    if direction == "LONG":
        if price >= sh * 0.999 or price <= sl:
            return False
        depth = (sh - price) / rng
        return min_pct <= depth <= max_pct
    if direction == "SHORT":
        if price <= sl * 1.001 or price >= sh:
            return False
        depth = (price - sl) / rng
        return min_pct <= depth <= max_pct
    return True


def rsi_in_pullback_zone(h1: List[Any], direction: str,
                         min_r: float = 40.0, max_r: float = 55.0) -> bool:
    r = rsi(h1, 14)
    if direction == "LONG":
        return min_r <= r <= max_r
    if direction == "SHORT":
        return (100.0 - max_r) <= r <= (100.0 - min_r)
    return False


# ============================================================
# REJECTION AT ZONE
# ============================================================

def rejection_at_zone(h1: List[Any], direction: str, lookback: int = 3) -> bool:
    e20 = ema(closes(h1), 20)
    e50 = ema(closes(h1), 50)
    atr1 = atr(h1)
    if e20 is None or e50 is None or atr1 <= 0:
        return False
    zone_buffer = atr1 * 0.60
    ema_high = max(e20, e50)
    ema_low = min(e20, e50)
    start = max(2, len(h1) - lookback)
    for i in range(start, len(h1)):
        c = h1[i]
        _, h, l, _, _ = candle_values(c)
        if direction == "LONG":
            at_zone = (l <= ema_high + zone_buffer and l >= ema_low - zone_buffer * 2.0)
        else:
            at_zone = (h >= ema_low - zone_buffer and h <= ema_high + zone_buffer * 2.0)
        if not at_zone:
            continue
        window = h1[max(0, i - 2):i + 1]
        if direction == "LONG" and bullish_reversal_pattern(window):
            return True
        if direction == "SHORT" and bearish_reversal_pattern(window):
            return True
    return False


# ============================================================
# VOLUME DECREASING
# ============================================================

def volume_decreasing_in_pullback(h1: List[Any], direction: str, lookback: int = 4) -> bool:
    vs = volumes(h1)
    if len(vs) < 21:
        return False
    baseline = sum(vs[-20:-lookback]) / max(1, 20 - lookback)
    recent = sum(vs[-lookback:]) / lookback
    if baseline <= 0:
        return False
    return recent <= baseline * 1.10


# ============================================================
# 15M PULLBACK CONFIRMATION
# ============================================================

def mtf_pullback_confirmation(m15: List[Any], direction: str) -> bool:
    if len(m15) < 30:
        return False
    cls = closes(m15)
    e20 = ema(cls, 20)
    e50 = ema(cls, 50)
    atr15 = atr(m15)
    if e20 is None or e50 is None or atr15 <= 0:
        return False
    price = cls[-1]
    zone = max(atr15 * 0.8, price * 0.004)
    if direction == "LONG":
        near = abs(price - e20) <= zone or abs(price - e50) <= zone
        if not near or price < e50 * 0.99:
            return False
    else:
        near = abs(price - e20) <= zone or abs(price - e50) <= zone
        if not near or price > e50 * 1.01:
            return False
    window = m15[-3:]
    if direction == "LONG":
        return bullish_reversal_pattern(window)
    else:
        return bearish_reversal_pattern(window)


# ============================================================
# PULLBACK COUNT
# ============================================================

def count_recent_pullbacks(h1: List[Any], direction: str,
                           lookback: int = 60, zone_atr: float = 0.6) -> int:
    arr = h1[-lookback:] if len(h1) > lookback else h1
    if len(arr) < 25:
        return 1
    cls = closes(arr)
    ema20 = ema_series(cls, 20)
    atr1 = atr(arr, 14)
    if atr1 <= 0:
        return 1
    zone = atr1 * zone_atr
    count = 0
    in_zone = False
    for i in range(20, len(arr)):
        e = ema20[i] if i < len(ema20) else None
        if e is None:
            continue
        _, _, l, c, _ = candle_values(arr[i])
        if direction == "LONG":
            touched = l <= e + zone
            far = c > e + zone * 2
        else:
            touched = candle_values(arr[i])[1] >= e - zone
            far = c < e - zone * 2
        if touched and not in_zone:
            count += 1
            in_zone = True
        elif far:
            in_zone = False
    return max(1, count)


# ============================================================
# ORDERLY PULLBACK
# ============================================================

def is_orderly_pullback(h1: List[Any], direction: str, lookback: int = 5) -> bool:
    if len(h1) < lookback + 5:
        return False
    recent = h1[-lookback:]
    avg_br = sum(body_ratio(c) for c in recent) / lookback
    if avg_br > 0.60:
        return False
    for c in recent:
        r = candle_range(c)
        if r <= 0:
            continue
        if direction == "LONG" and bearish(c) and body_ratio(c) > 0.75:
            return False
        if direction == "SHORT" and bullish(c) and body_ratio(c) > 0.75:
            return False
    return True


# ============================================================
# RANGE DETECTION HELPERS
# ============================================================

def detect_range_condition(h1: List[Any], lookback: int = 40,
                           min_touches: int = 2) -> Dict[str, Any]:
    default = {
        "is_range": False, "high": 0.0, "low": 0.0, "mid": 0.0,
        "width_pct": 0.0, "touches_high": 0, "touches_low": 0,
    }
    if len(h1) < lookback + 5:
        return default
    adx1 = adx(h1, 14)
    if adx1 >= 22:
        return default
    arr = h1[-lookback:]
    hs = highs(arr)
    ls = lows(arr)
    cls = closes(arr)
    r_high = max(hs)
    r_low = min(ls)
    rng = r_high - r_low
    if rng <= 0 or r_low <= 0:
        return default
    width_pct = (rng / r_low) * 100
    if width_pct < 1.5 or width_pct > 15.0:
        return default
    atr1 = atr(h1, 14)
    if atr1 <= 0:
        return default
    tol = atr1 * 0.5
    touches_high = sum(1 for h in hs if h >= r_high - tol)
    touches_low = sum(1 for l in ls if l <= r_low + tol)
    if touches_high < min_touches or touches_low < min_touches:
        return default
    last_close = cls[-1]
    if last_close > r_high * 1.01 or last_close < r_low * 0.99:
        return default
    return {
        "is_range": True,
        "high": r_high, "low": r_low,
        "mid": (r_high + r_low) / 2,
        "width_pct": round(width_pct, 2),
        "touches_high": touches_high, "touches_low": touches_low,
    }


def price_near_range_boundary(h1: List[Any], direction: str,
                              range_high: float, range_low: float,
                              atr_mult: float = 0.8) -> bool:
    if range_high <= 0 or range_low <= 0:
        return False
    atr1 = atr(h1, 14)
    if atr1 <= 0:
        return False
    price = closes(h1)[-1]
    tol = atr1 * atr_mult
    if direction == "LONG":
        return abs(price - range_low) <= tol
    if direction == "SHORT":
        return abs(price - range_high) <= tol
    return False


# ============================================================
# BREAKOUT HELPERS
# ============================================================

def local_breakout(m15: List[Any], direction: str, lookback: int = 20) -> Tuple[bool, float]:
    if len(m15) < lookback + 2:
        return False, 0.0
    previous = m15[-lookback - 1:-1]
    last = m15[-1]
    lh = max(highs(previous))
    ll = min(lows(previous))
    close = candle_values(last)[3]
    if direction == "LONG":
        return close > lh, lh
    if direction == "SHORT":
        return close < ll, ll
    return False, 0.0


def breakout_hold(m15: List[Any], direction: str, level: float) -> bool:
    if level <= 0 or len(m15) < 2:
        return False
    last = m15[-1]
    _, h, l, c, _ = candle_values(last)
    if direction == "LONG":
        return bullish(last) and c > level and h >= c
    if direction == "SHORT":
        return bearish(last) and c < level and l <= c
    return False


def is_squeeze(m15: List[Any], lookback: int = 20) -> bool:
    if len(m15) < lookback + 15:
        return False
    current_atr = atr(m15[-15:], 14)
    historical_atrs = []
    for i in range(15, lookback + 15):
        historical_atrs.append(atr(m15[-i-15:-i], 14))
    avg_atr = sum(historical_atrs) / len(historical_atrs) if historical_atrs else 0
    if avg_atr <= 0:
        return False
    return current_atr < avg_atr * 0.9


def not_overextended(m15: List[Any], direction: str, level: float,
                     max_atr_mult: float = 1.5) -> bool:
    if len(m15) < 20 or level <= 0:
        return False
    current_price = candle_values(m15[-1])[3]
    m15_atr = atr(m15, 14)
    if m15_atr <= 0:
        return False
    distance = abs(current_price - level)
    if direction == "LONG":
        return (current_price > level) and (distance <= max_atr_mult * m15_atr)
    if direction == "SHORT":
        return (current_price < level) and (distance <= max_atr_mult * m15_atr)
    return False


# ============================================================
# REVERSAL HELPERS
# ============================================================

def sweep_reclaim_recent(m15: List[Any], direction: str, lookback: int = 12) -> bool:
    if len(m15) < lookback + 3:
        return False
    previous = m15[-lookback - 3:-3]
    if not previous:
        return False
    ph = max(highs(previous))
    pl = min(lows(previous))
    for c in m15[-3:]:
        _, h, l, cl, _ = candle_values(c)
        if direction == "LONG" and l < pl and cl > pl and bullish(c):
            return True
        if direction == "SHORT" and h > ph and cl < ph and bearish(c):
            return True
    return False


def structure_shift_5m(m5: List[Any], direction: str) -> bool:
    if len(m5) < 12:
        return False
    prev = m5[-8:-1]
    last = m5[-1]
    cl = candle_values(last)[3]
    if direction == "LONG":
        return bullish(last) and body_ratio(last) >= 0.30 and cl > max(highs(prev))
    if direction == "SHORT":
        return bearish(last) and body_ratio(last) >= 0.30 and cl < min(lows(prev))
    return False


def _mtf_basic(m15: List[Any], direction: str) -> bool:
    if len(m15) < 25:
        return False
    cls = closes(m15)
    e20 = ema(cls, 20)
    e50 = ema(cls, 50)
    if e20 is None or e50 is None:
        return False
    recent = m15[-3:]
    if direction == "LONG":
        cnt = sum(1 for c in recent if bullish(c))
        return cnt >= 2 and cls[-1] >= e20 * 0.999 and cls[-1] >= e50 * 0.995
    if direction == "SHORT":
        cnt = sum(1 for c in recent if bearish(c))
        return cnt >= 2 and cls[-1] <= e20 * 1.001 and cls[-1] <= e50 * 1.005
    return False


# ============================================================
# STRATEGIES
# ============================================================

def detect_trend_following(h1, m15, m5, direction):
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    structure = market_structure(h1)
    ema_dir = ema_direction(h1)
    adx1 = adx(h1)
    if structure != expected and ema_dir != expected:
        return {"valid": False, "reason": "H1_TREND_MISSING"}
    if adx1 < 22:
        return {"valid": False, "reason": "ADX_LOW"}
    if not htf_breakout_confirm(h1, direction, lookback=20, recent_window=5):
        return {"valid": False, "reason": "NO_H1_BREAKOUT"}
    if not not_far_from_breakout(h1, direction, lookback=20,
                                  recent_window=5, max_atr=0.7):
        return {"valid": False, "reason": "TOO_FAR_FROM_BREAKOUT"}
    r_15 = rsi(m15, 14)
    if direction == "LONG" and r_15 > 72:
        return {"valid": False, "reason": "RSI_TOO_HIGH"}
    if direction == "SHORT" and r_15 < 28:
        return {"valid": False, "reason": "RSI_TOO_LOW"}
    if not entry_trigger_5m(m5, direction):
        return {"valid": False, "reason": "5M_TRIGGER"}
    mtf = mtf_pullback_confirmation(m15, direction) or _mtf_basic(m15, direction)
    vol = volume_spike(h1, 1.10, 20)
    score = 4
    if structure == expected:
        score += 2
    if ema_dir == expected:
        score += 2
    if adx1 >= 25:
        score += 1
    if mtf:
        score += 1
    if vol:
        score += 1
    return {"valid": True, "reason": "VALID", "score": score, "mtf": mtf}


def detect_pullback(h1, m15, m5, direction):
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    structure = market_structure(h1)
    ema_dir = ema_direction(h1)
    if structure != expected and ema_dir != expected:
        return {"valid": False, "reason": "H1_TREND_MISSING"}
    adx1 = adx(h1)
    if adx1 < 22:
        return {"valid": False, "reason": "ADX_LOW"}
    pullback_count = count_recent_pullbacks(h1, direction)
    if pullback_count >= 4:
        return {"valid": False, "reason": "LATE_TREND_FATIGUE"}
    if not pullback_detected(h1, direction):
        return {"valid": False, "reason": "NO_PULLBACK_ZONE"}
    if not pullback_duration_ok(h1, direction, min_bars=3, max_bars=10):
        return {"valid": False, "reason": "PULLBACK_DURATION_INVALID"}
    if not pullback_depth_ok(h1, direction, min_pct=0.35, max_pct=0.78):
        return {"valid": False, "reason": "PULLBACK_DEPTH_INVALID"}
    at_ema = near_ema_zone(h1, direction)
    at_fib = fib_pullback_zone(h1, direction)
    at_swing = near_swing_low_zone(h1, direction)
    if not (at_ema or at_fib or at_swing):
        return {"valid": False, "reason": "NOT_AT_ANY_ZONE"}
    if not rejection_at_zone(h1, direction, lookback=3):
        return {"valid": False, "reason": "NO_REJECTION_AT_ZONE"}
    if not rsi_in_pullback_zone(h1, direction, min_r=40, max_r=55):
        return {"valid": False, "reason": "RSI_OUT_OF_PULLBACK_ZONE"}
    if not is_orderly_pullback(h1, direction):
        return {"valid": False, "reason": "DISORDERLY_PULLBACK"}
    if not volume_decreasing_in_pullback(h1, direction):
        return {"valid": False, "reason": "VOLUME_INCREASING"}
    if not mtf_pullback_confirmation(m15, direction):
        return {"valid": False, "reason": "NO_15M_PATTERN"}
    if not entry_trigger_5m(m5, direction):
        return {"valid": False, "reason": "5M_TRIGGER"}
    score = 7
    if at_ema:
        score += 1
    if at_fib:
        score += 1
    if fib_golden_zone(h1, direction):
        score += 1
    if at_swing:
        score += 1
    if adx1 >= 25:
        score += 1
    if adx1 >= 30:
        score += 1
    if pullback_count <= 1:
        score += 1
    return {"valid": True, "reason": "VALID", "score": score, "mtf": True,
            "zones": {"ema": at_ema, "fib": at_fib, "swing": at_swing},
            "pullback_count": pullback_count}


def detect_breakout(h1, m15, m5, direction):
    ok, level = local_breakout(m15, direction, 20)
    if not ok:
        return {"valid": False, "reason": "NO_BREAKOUT"}
    last = m15[-1]
    if body_ratio(last) < 0.50:
        return {"valid": False, "reason": "WEAK_BREAKOUT_CANDLE"}
    if not volume_spike(m15, 1.50, 20):
        return {"valid": False, "reason": "NO_VOLUME_SPIKE"}
    if not not_overextended(m15, direction, level):
        return {"valid": False, "reason": "OVEREXTENDED_FROM_LEVEL"}
    if not is_squeeze(m15):
        return {"valid": False, "reason": "NO_SQUEEZE_BEFORE_BREAKOUT"}
    if not breakout_hold(m15, direction, level):
        return {"valid": False, "reason": "NO_HOLD"}
    if not entry_trigger_5m(m5, direction):
        return {"valid": False, "reason": "5M_TRIGGER"}
    adx1 = adx(h1)
    if adx1 < 22:
        return {"valid": False, "reason": "ADX_LOW"}
    mtf = _mtf_basic(m15, direction)
    score = 6
    if mtf:
        score += 2
    if adx1 >= 30:
        score += 1
    if volume_spike(m15, 2.0, 20):
        score += 1
    return {"valid": True, "reason": "VALID", "score": score,
            "mtf": mtf, "level": level}


def detect_reversal(h1, m15, m5, direction):
    if not sweep_reclaim_recent(m15, direction):
        return {"valid": False, "reason": "NO_SWEEP_RECLAIM"}
    if not structure_shift_5m(m5, direction):
        return {"valid": False, "reason": "NO_5M_STRUCTURE_SHIFT"}
    last = m15[-1]
    if body_ratio(last) < 0.30:
        return {"valid": False, "reason": "WEAK_RECLAIM"}
    mtf = _mtf_basic(m15, direction)
    score = 7
    if mtf:
        score += 1
    return {"valid": True, "reason": "VALID", "score": score, "mtf": mtf}


def detect_range_trading(h1, m15, m5, direction):
    range_info = detect_range_condition(h1, lookback=40, min_touches=2)
    if not range_info["is_range"]:
        return {"valid": False, "reason": "NOT_IN_RANGE"}
    r_high = range_info["high"]
    r_low = range_info["low"]
    r_mid = range_info["mid"]
    if not price_near_range_boundary(h1, direction, r_high, r_low, atr_mult=0.8):
        return {"valid": False, "reason": "NOT_AT_BOUNDARY"}
    r = rsi(h1, 14)
    if direction == "LONG":
        if r > 40:
            return {"valid": False, "reason": "RSI_NOT_OVERSOLD"}
    elif direction == "SHORT":
        if r < 60:
            return {"valid": False, "reason": "RSI_NOT_OVERBOUGHT"}
    else:
        return {"valid": False, "reason": "INVALID_DIRECTION"}
    if not rejection_at_zone(h1, direction, lookback=3):
        if not recent_rejection(h1, direction, lookback=4):
            return {"valid": False, "reason": "NO_REJECTION"}
    if not entry_trigger_5m(m5, direction):
        return {"valid": False, "reason": "5M_TRIGGER"}
    mtf = _mtf_basic(m15, direction)
    score = 7
    if mtf:
        score += 1
    if direction == "LONG" and r <= 30:
        score += 1
    if direction == "SHORT" and r >= 70:
        score += 1
    if range_info["width_pct"] >= 3.0:
        score += 1
    if range_info["touches_high"] >= 3 and range_info["touches_low"] >= 3:
        score += 1
    return {
        "valid": True, "reason": "VALID", "score": score, "mtf": mtf,
        "range_high": r_high, "range_low": r_low, "range_mid": r_mid,
        "range_width_pct": range_info["width_pct"],
    }


def detect_bb_reversion(h1, m15, m5, direction):
    adx1 = adx(h1)
    if adx1 >= 25:
        return {"valid": False, "reason": "ADX_TOO_HIGH_FOR_REVERSION"}
    upper, mid, lower = bollinger_bands(h1, 20, 2.0)
    if upper == 0 or lower == 0:
        return {"valid": False, "reason": "BB_CALCULATION_FAILED"}
    last_candle = h1[-1]
    _, h, l, c, _ = candle_values(last_candle)
    r = rsi(h1, 14)
    if direction == "LONG":
        if l > lower * 1.005:
            return {"valid": False, "reason": "PRICE_NOT_AT_LOWER_BAND"}
        if r > 32:
            return {"valid": False, "reason": "RSI_NOT_OVERSOLD"}
        window = h1[-3:]
        if not bullish_reversal_pattern(window):
            return {"valid": False, "reason": "NO_BULLISH_REVERSAL_PATTERN"}
    elif direction == "SHORT":
        if h < upper * 0.995:
            return {"valid": False, "reason": "PRICE_NOT_AT_UPPER_BAND"}
        if r < 68:
            return {"valid": False, "reason": "RSI_NOT_OVERBOUGHT"}
        window = h1[-3:]
        if not bearish_reversal_pattern(window):
            return {"valid": False, "reason": "NO_BEARISH_REVERSAL_PATTERN"}
    else:
        return {"valid": False, "reason": "INVALID_DIRECTION"}
    if not entry_trigger_5m(m5, direction):
        return {"valid": False, "reason": "5M_TRIGGER"}
    mtf = _mtf_basic(m15, direction)
    score = 8
    if mtf:
        score += 1
    if adx1 < 20:
        score += 1
    return {
        "valid": True, "reason": "VALID", "score": score, "mtf": mtf,
        "bb_upper": upper, "bb_mid": mid, "bb_lower": lower,
    }


# ============================================================
# HTF CONTEXT
# ============================================================

def context_allows(strategy: str, daily: str, h4: str,
                   direction: str, h4_adx: float) -> bool:
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    daily_opp = daily in ("BULLISH", "BEARISH") and daily != expected
    h4_opp = h4 in ("BULLISH", "BEARISH") and h4 != expected

    if strategy in ("RANGE_TRADING", "BB_REVERSION"):
        if daily_opp and h4_opp and h4_adx >= 30:
            return False
        return True

    if strategy in ("TREND_FOLLOWING", "PULLBACK", "BREAKOUT"):
        if daily_opp:
            return False
        if h4_opp and h4_adx >= 22:
            return False
        return True

    if strategy == "REVERSAL":
        if daily_opp and h4_opp:
            return False
        if daily_opp and h4_adx >= 22:
            return False
        if h4_opp and h4_adx >= 28:
            return False
        return True

    return True


# ============================================================
# BTC FILTER
# ============================================================

def btc_filter(direction: str, btc_context: Optional[Dict[str, Any]],
               strategy: str = "") -> str:
    if not btc_context:
        return "ALLOW"
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    btc_dir = btc_context.get("h4") or "RANGE"
    btc_adx = float(btc_context.get("adx_h4") or 0.0)
    daily_dir = btc_context.get("daily") or "RANGE"
    daily_adx = float(btc_context.get("adx_daily") or 0.0)
    btc_opposes = btc_dir in ("BULLISH", "BEARISH") and btc_dir != expected
    daily_opposes = daily_dir in ("BULLISH", "BEARISH") and daily_dir != expected

    if strategy in ("RANGE_TRADING", "BB_REVERSION"):
        if btc_opposes and btc_adx >= 35:
            return "BLOCK"
        return "ALLOW"

    if btc_opposes and daily_opposes and max(btc_adx, daily_adx) >= 30:
        return "BLOCK"
    if btc_opposes and btc_adx >= 30:
        return "BLOCK"
    if btc_opposes and btc_adx >= 22:
        return "WARN"
    if daily_opposes and daily_adx >= 30 and not btc_opposes:
        return "WARN"
    return "ALLOW"


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_trade_levels(h1, m5, direction, strategy: str = "DEFAULT"):
    if direction not in ("LONG", "SHORT") or not h1 or not m5:
        return None
    entry = closes(m5)[-1]
    if entry <= 0:
        return None
    if strategy == "RANGE_TRADING":
        return _calc_range_levels(h1, m5, direction, entry)
    if strategy == "BB_REVERSION":
        return _calc_bb_reversion_levels(h1, m5, direction, entry)
    return _calc_trend_levels(h1, m5, direction, entry)


def _calc_trend_levels(h1, m5, direction, entry):
    atr_1h = atr(h1, 14)
    atr_5m = atr(m5, 14) if len(m5) >= 15 else 0.0
    if atr_1h <= 0:
        return None
    candidates = [entry * 0.012]
    if atr_5m > 0:
        candidates.append(2.5 * atr_5m)
    candidates.append(0.8 * atr_1h)
    sl_dist = max(candidates)
    if sl_dist > entry * 0.02:
        sl_dist = entry * 0.02
    if direction == "LONG":
        sl = entry - sl_dist
        tp1 = entry + sl_dist * 1.25
        tp2 = entry + sl_dist * 2.50
        tp3 = entry + sl_dist * 3.75
        if not (sl < entry < tp1 < tp2 < tp3):
            return None
    else:
        sl = entry + sl_dist
        tp1 = entry - sl_dist * 1.25
        tp2 = entry - sl_dist * 2.50
        tp3 = entry - sl_dist * 3.75
        if not (sl > entry > tp1 > tp2 > tp3):
            return None
    return {
        "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "risk": sl_dist, "rr": "1:1.25/1:2.5/1:3.75",
        "trail_mode": "BREAKEVEN_AT_TP1_THEN_ATR",
        "trail_atr_mult": 2.0, "trail_bar_count": 10,
        "breakeven_at_tp1": True,
    }


def _calc_range_levels(h1, m5, direction, entry):
    range_info = detect_range_condition(h1, lookback=40, min_touches=2)
    if not range_info["is_range"]:
        return None
    r_high = range_info["high"]
    r_low = range_info["low"]
    r_mid = range_info["mid"]
    rng = r_high - r_low
    atr1 = atr(h1, 14)
    if atr1 <= 0 or rng <= 0:
        return None
    buffer = atr1 * 0.3
    if direction == "LONG":
        sl = r_low - buffer
        risk = entry - sl
        if risk <= 0:
            return None
        tp1 = r_mid
        tp2 = r_low + rng * 0.75
        tp3 = r_high - buffer
        if not (sl < entry < tp1 < tp2 < tp3):
            return None
        if risk / entry > 0.05:
            return None
    else:
        sl = r_high + buffer
        risk = sl - entry
        if risk <= 0:
            return None
        tp1 = r_mid
        tp2 = r_high - rng * 0.75
        tp3 = r_low + buffer
        if not (sl > entry > tp1 > tp2 > tp3):
            return None
        if risk / entry > 0.05:
            return None
    return {
        "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "risk": risk, "rr": "1:2",
        "trail_mode": "BREAKEVEN_AT_TP1",
        "breakeven_at_tp1": True,
        "range_high": r_high, "range_low": r_low, "range_mid": r_mid,
    }


def _calc_bb_reversion_levels(h1, m5, direction, entry):
    upper, mid, lower = bollinger_bands(h1, 20, 2.0)
    atr1 = atr(h1, 14)
    if upper <= 0 or lower <= 0 or atr1 <= 0:
        return None
    buffer = atr1 * 0.5
    if direction == "LONG":
        sl = lower - buffer
        risk = entry - sl
        if risk <= 0:
            return None
        tp1 = mid
        tp2 = upper
        tp3 = upper + buffer
        if not (sl < entry < tp1 < tp2 < tp3):
            return None
        if risk / entry > 0.05:
            return None
    else:
        sl = upper + buffer
        risk = sl - entry
        if risk <= 0:
            return None
        tp1 = mid
        tp2 = lower
        tp3 = lower - buffer
        if not (sl > entry > tp1 > tp2 > tp3):
            return None
        if risk / entry > 0.05:
            return None
    return {
        "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "risk": risk, "rr": "BB_BASED",
        "trail_mode": "BREAKEVEN_AT_TP1",
        "breakeven_at_tp1": True,
        "bb_upper": upper, "bb_mid": mid, "bb_lower": lower,
    }


def target_reachable(levels, h1, direction):
    entry = safe_float(levels.get("entry"))
    tp1 = safe_float(levels.get("tp1"))
    if entry <= 0 or tp1 <= 0 or direction not in ("LONG", "SHORT"):
        return False
    recent = h1[-25:] if len(h1) > 25 else h1
    if len(recent) < 6:
        return True
    hs, ls = highs(recent), lows(recent)
    pivots = []
    strength = 2
    end = len(recent) - strength
    for i in range(strength, end):
        if all(hs[i] > hs[i - j] for j in range(1, strength + 1)) and \
           all(hs[i] >= hs[i + j] for j in range(1, strength + 1)):
            pivots.append(("HIGH", hs[i]))
        if all(ls[i] < ls[i - j] for j in range(1, strength + 1)) and \
           all(ls[i] <= ls[i + j] for j in range(1, strength + 1)):
            pivots.append(("LOW", ls[i]))
    if direction == "LONG":
        return not [p for k, p in pivots if k == "HIGH" and entry < p < tp1]
    return not [p for k, p in pivots if k == "LOW" and tp1 < p < entry]


# ============================================================
# NO TRADE
# ============================================================

def no_trade(reason, daily="RANGE", h4="RANGE", h1="RANGE",
             direction=None, diagnostics=None, metrics=None, btc=None):
    result = {
        "signal": "NO_TRADE", "direction": direction, "score": 0,
        "quality": "LOW", "reason": reason,
        "strategies": [
            name for name, status in (diagnostics or {}).items()
            if status == "VALID" or status.startswith("HIGH_FAIL:")
        ],
        "strategy": None,
        "strategy_diagnostics": diagnostics or {},
        "daily": daily, "4h": h4, "1h": h1,
    }
    if metrics:
        result.update(metrics)
    if btc:
        result["btc_dir"] = btc.get("h4", "RANGE")
        result["btc_adx"] = round(float(btc.get("adx_h4", 0.0)), 2)
        if direction in ("LONG", "SHORT"):
            expected = "BULLISH" if direction == "LONG" else "BEARISH"
            btc_h4 = btc.get("h4", "RANGE")
            result["btc_relation"] = (
                "ALIGNED" if btc_h4 == expected
                else "OPPOSED" if btc_h4 in ("BULLISH", "BEARISH")
                else "NEUTRAL"
            )
        else:
            result["btc_relation"] = "NEUTRAL"
    return result


def direction_from_tf(candles):
    if not candles or len(candles) < 30:
        return "RANGE"
    try:
        d = market_structure(candles)
        return d if d in ("BULLISH", "BEARISH", "RANGE") else "RANGE"
    except Exception:
        logging.exception("direction_from_tf failed")
        return "RANGE"


def run_strategy(name, h1, m15, m5, direction):
    if name == "TREND_FOLLOWING":
        return detect_trend_following(h1, m15, m5, direction)
    if name == "PULLBACK":
        return detect_pullback(h1, m15, m5, direction)
    if name == "BREAKOUT":
        return detect_breakout(h1, m15, m5, direction)
    if name == "REVERSAL":
        return detect_reversal(h1, m15, m5, direction)
    if name == "RANGE_TRADING":
        return detect_range_trading(h1, m15, m5, direction)
    if name == "BB_REVERSION":
        return detect_bb_reversion(h1, m15, m5, direction)
    return {"valid": False, "reason": "UNKNOWN_STRATEGY"}


# ============================================================
# MAIN ENGINE (v22 REGIME SWITCH)
# ============================================================

def generate_signal(daily, h4, h1, m15, m5,
                    btc_context: Optional[Dict[str, Any]] = None):
    d = closed(daily)
    h4c = closed(h4)
    h1c = closed(h1)
    m15c = closed(m15)
    m5c = closed(m5)
    if btc_context is None:
        btc_context = {
            "daily": "RANGE", "h4": "RANGE", "h1": "RANGE",
            "adx_h1": 0.0, "adx_h4": 0.0, "adx_daily": 0.0,
        }
    if min(len(d), len(h4c), len(h1c), len(m15c), len(m5c)) < 50:
        return no_trade("INSUFFICIENT_DATA", btc=btc_context)

    daily_dir = direction_from_tf(d)
    h4_dir = direction_from_tf(h4c)
    h1_dir = direction_from_tf(h1c)

    rsi15 = round(rsi(m15c), 2)
    adx1 = round(adx(h1c), 2)
    adx15 = round(adx(m15c), 2)
    h4_adx = adx(h4c)
    vol = volume_spike(m15c, 1.50, 20)

    # ============================================================
    # v22: MARKET REGIME SWITCH
    # ============================================================
    if adx1 < 22:
        # Ranging Market: ONLY Mean Reversion
        strategy_names = ["RANGE_TRADING", "BB_REVERSION", "REVERSAL"]
        logger.info("REGIME_SWITCH | %s | RANGING (ADX=%.1f)", "MARKET", adx1)
    else:
        # Trending Market: ONLY Momentum
        strategy_names = ["TREND_FOLLOWING", "PULLBACK", "BREAKOUT", "REVERSAL"]
        logger.info("REGIME_SWITCH | %s | TRENDING (ADX=%.1f)", "MARKET", adx1)

    diagnostics = {}
    metrics = {
        "15m_rsi": rsi15, "adx_1h": adx1, "adx_15m": adx15,
        "mtf_confirmation": False, "volume_spike": bool(vol),
        "confirmation": False,
    }
    strategy_results = []

    for strategy_name in strategy_names:
        best_result = None
        best_direction = None
        direction_results = {}
        for direction in ("LONG", "SHORT"):
            try:
                result = run_strategy(strategy_name, h1c, m15c, m5c, direction)
            except Exception as exc:
                result = {"valid": False, "reason": f"ERROR_{type(exc).__name__}"}
            
            # HTF Context
            if result.get("valid") and not context_allows(
                strategy_name, daily_dir, h4_dir, direction, h4_adx
            ):
                result["_htf_blocked"] = True
            
            direction_results[direction] = result

            if result.get("valid") and not result.get("_htf_blocked"):
                if best_result is None or result.get("score", 0) > best_result.get("score", 0):
                    best_result = result
                    best_direction = direction
                    
        if best_result is not None:
            diagnostics[strategy_name] = "VALID"
            strategy_results.append((strategy_name, best_direction, best_result))
        else:
            reasons = []
            for direction, res in direction_results.items():
                r = res.get("reason", "UNKNOWN")
                if res.get("_htf_blocked"):
                    r = f"{r}|HTF_CONTEXT"
                reasons.append(f"{direction}:{r}")
            diagnostics[strategy_name] = "FAIL:" + "|".join(reasons)

    diag_dir = None
    if strategy_results:
        diag_dir = strategy_results[0][1]
    elif h1_dir == "BULLISH":
        diag_dir = "LONG"
    elif h1_dir == "BEARISH":
        diag_dir = "SHORT"
    if diag_dir:
        metrics["mtf_confirmation"] = bool(_mtf_basic(m15c, diag_dir))
        metrics["confirmation"] = bool(entry_trigger_5m(m5c, diag_dir))
        
    if not strategy_results:
        return no_trade("NO_VALID_STRATEGY", daily_dir, h4_dir,
                        h1_dir, None, diagnostics, metrics, btc=btc_context)

    priority = {
        "BB_REVERSION": 6,
        "RANGE_TRADING": 5,
        "TREND_FOLLOWING": 4,
        "PULLBACK": 3,
        "BREAKOUT": 2,
        "REVERSAL": 1,
    }
    high_candidates = []
    rejection_reasons = []

    for strategy, direction, candidate in strategy_results:
        score = int(candidate.get("score", 0))
        expected = "BULLISH" if direction == "LONG" else "BEARISH"
        same_dir = sum(
            1 for name, od, _ in strategy_results
            if od == direction and name != strategy
        )
        if same_dir >= 1:
            score += 2
        if daily_dir == expected:
            score += 2
        if h4_dir == expected:
            score += 1
        elif h4_dir == "RANGE":
            score += 1
        cand_metrics = dict(metrics)
        cand_metrics["mtf_confirmation"] = bool(_mtf_basic(m15c, direction))
        cand_metrics["confirmation"] = bool(entry_trigger_5m(m5c, direction))

        if strategy in ("TREND_FOLLOWING", "PULLBACK", "BREAKOUT"):
            if direction == "LONG" and rsi15 >= 72:
                diagnostics[strategy] = "HIGH_FAIL:RSI_TOO_EXTENDED"
                rejection_reasons.append("RSI_TOO_EXTENDED")
                continue
            if direction == "SHORT" and rsi15 <= 28:
                diagnostics[strategy] = "HIGH_FAIL:RSI_TOO_EXTENDED"
                rejection_reasons.append("RSI_TOO_EXTENDED")
                continue

        if strategy == "TREND_FOLLOWING":
            high = (
                score >= 8 and adx1 >= 22
                and cand_metrics["confirmation"]
                and htf_breakout_confirm(h1c, direction)
                and not_far_from_breakout(h1c, direction)
            )
        elif strategy == "PULLBACK":
            high = score >= 9 and cand_metrics["confirmation"]
        elif strategy == "BREAKOUT":
            high = (score >= 9 and cand_metrics["confirmation"]
                    and vol and adx1 >= 22)
        elif strategy == "REVERSAL":
            high = (score >= 9 and cand_metrics["confirmation"]
                    and structure_shift_5m(m5c, direction))
        elif strategy == "RANGE_TRADING":
            high = score >= 8 and cand_metrics["confirmation"]
        elif strategy == "BB_REVERSION":
            high = score >= 8 and cand_metrics["confirmation"]
        else:
            high = False

        if not high:
            failed = []
            min_score = {
                "TREND_FOLLOWING": 8, "PULLBACK": 9,
                "BREAKOUT": 9, "REVERSAL": 9,
                "RANGE_TRADING": 8, "BB_REVERSION": 8,
            }.get(strategy, 999)
            if score < min_score:
                failed.append(f"SCORE={score}<{min_score}")
            if not cand_metrics["confirmation"]:
                failed.append("NO_5M_CONFIRMATION")
            if strategy == "TREND_FOLLOWING":
                if adx1 < 22:
                    failed.append(f"ADX1_LOW={adx1}")
                if not htf_breakout_confirm(h1c, direction):
                    failed.append("NO_H1_BREAKOUT")
                if not not_far_from_breakout(h1c, direction):
                    failed.append("TOO_FAR_FROM_BREAKOUT")
            elif strategy == "BREAKOUT":
                if not vol:
                    failed.append("NO_VOLUME_SPIKE")
                if adx1 < 22:
                    failed.append(f"ADX1_LOW={adx1}")
            elif strategy == "REVERSAL":
                if not structure_shift_5m(m5c, direction):
                    failed.append("NO_5M_STRUCTURE_SHIFT")
            diagnostics[strategy] = (
                "HIGH_FAIL:" + "|".join(failed) if failed else "HIGH_FAIL:UNKNOWN"
            )
            rejection_reasons.append("SIGNAL_QUALITY_TOO_LOW")
            continue

        levels = calculate_trade_levels(h1c, m5c, direction, strategy)
        if not levels:
            diagnostics[strategy] = "HIGH_FAIL:INVALID_TRADE_LEVELS"
            rejection_reasons.append("INVALID_TRADE_LEVELS")
            continue
        if not target_reachable(levels, h1c, direction):
            diagnostics[strategy] = "HIGH_FAIL:TP1_BLOCKED"
            rejection_reasons.append("TP1_BLOCKED")
            continue
        high_candidates.append({
            "strategy": strategy, "direction": direction, "score": score,
            "levels": levels, "metrics": cand_metrics,
            "priority": priority.get(strategy, 0),
        })

    if not high_candidates:
        if "TP1_BLOCKED" in rejection_reasons:
            final_reason = "TP1_BLOCKED"
        elif "INVALID_TRADE_LEVELS" in rejection_reasons:
            final_reason = "INVALID_TRADE_LEVELS"
        elif "RSI_TOO_EXTENDED" in rejection_reasons and len(set(rejection_reasons)) == 1:
            final_reason = "RSI_TOO_EXTENDED"
        else:
            final_reason = "SIGNAL_QUALITY_TOO_LOW"
        return no_trade(final_reason, daily_dir, h4_dir, h1_dir,
                        None, diagnostics, metrics, btc=btc_context)

    high_candidates.sort(
        key=lambda item: (item["score"], item["priority"]),
        reverse=True,
    )
    selected = high_candidates[0]

    btc_status = btc_filter(selected["direction"], btc_context, selected["strategy"])

    if btc_status == "BLOCK":
        for s_name in list(diagnostics.keys()):
            if diagnostics[s_name] == "VALID":
                diagnostics[s_name] = "HIGH_FAIL:BTC_OPPOSES"
        return no_trade(
            "BTC_OPPOSES",
            daily_dir, h4_dir, h1_dir,
            selected["direction"], diagnostics, metrics,
            btc=btc_context,
        )
    expected_dir = "BULLISH" if selected["direction"] == "LONG" else "BEARISH"
    btc_h4 = btc_context.get("h4", "RANGE")
    btc_relation = (
        "ALIGNED" if btc_h4 == expected_dir
        else "OPPOSED" if btc_h4 in ("BULLISH", "BEARISH")
        else "NEUTRAL"
    )
    return {
        "signal": selected["direction"],
        "direction": selected["direction"],
        "score": selected["score"],
        "quality": "HIGH",
        "reason": f"VALID_{selected['strategy']}",
        "strategies": [
            item["strategy"] for item in high_candidates
            if item["direction"] == selected["direction"]
        ],
        "strategy": selected["strategy"],
        "strategy_diagnostics": diagnostics,
        "daily": daily_dir, "4h": h4_dir, "1h": h1_dir,
        "15m_rsi": rsi15, "adx_1h": adx1, "adx_15m": adx15,
        "mtf_confirmation": bool(selected["metrics"]["mtf_confirmation"]),
        "volume_spike": bool(selected["metrics"]["volume_spike"]),
        "confirmation": bool(selected["metrics"]["confirmation"]),
        "btc_warning": btc_status == "WARN",
        "btc_dir": btc_h4,
        "btc_adx": round(float(btc_context.get("adx_h4", 0.0)), 2),
        "btc_relation": btc_relation,
        **selected["levels"],
    }


# ============================================================
# COMPATIBILITY
# ============================================================

analyze = generate_signal
get_signal = generate_signal
