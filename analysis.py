# ============================================================
# CryptoBot - Analysis Engine v8.2
#
# 1H  = Main Direction
# 15M = Filter + MTF Confirmation + Breaker/FVG
# 5M  = Entry Trigger
#
# Strategies:
#   STOP_HUNT
#   THREE_TAP
#   LIQUIDITY_ZONE
#   BREAKER_BLOCK
#   FVG_FILL
#
# v8.2 Changes:
#   - BREAKER_BLOCK moved from 5M to 15M (less noise)
#   - FVG_FILL moved from 5M to 15M
#   - Minimum SL raised from 0.4% to 0.6%
#   - Added is_breakout_valid filter (anti fake breakout)
# ============================================================

from statistics import mean


# ============================================================
# HELPERS
# ============================================================

def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def candle_values(candle):
    return (
        safe_float(candle.get("open")),
        safe_float(candle.get("high")),
        safe_float(candle.get("low")),
        safe_float(candle.get("close")),
    )


def candle_body(candle):
    o, h, l, c = candle_values(candle)
    if None in (o, h, l, c):
        return 0.0
    return abs(c - o)


def upper_wick(candle):
    o, h, l, c = candle_values(candle)
    if None in (o, h, l, c):
        return 0.0
    return h - max(o, c)


def lower_wick(candle):
    o, h, l, c = candle_values(candle)
    if None in (o, h, l, c):
        return 0.0
    return min(o, c) - l


def ema(values, period):
    if not values or len(values) < period:
        return None

    values = [
        safe_float(x)
        for x in values
        if safe_float(x) is not None
    ]

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period

    for price in values[period:]:
        result = ((price - result) * multiplier) + result

    return result


# ============================================================
# RSI
# ============================================================

def calculate_rsi(candles, period=14):
    if not candles or len(candles) < period + 1:
        return None

    closes = [
        safe_float(c.get("close"))
        for c in candles
        if safe_float(c.get("close")) is not None
    ]

    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        return 100.0

    for i in range(period, len(gains)):
        avg_gain = (
            (avg_gain * (period - 1)) + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return round(
        100 - (100 / (1 + rs)),
        2
    )


# ============================================================
# ADX
# ============================================================

def calculate_adx(candles, period=14):
    if not candles or len(candles) < period * 2:
        return None

    trs = []
    plus_dm = []
    minus_dm = []

    for i in range(1, len(candles)):
        h = safe_float(candles[i].get("high"))
        l = safe_float(candles[i].get("low"))
        ph = safe_float(candles[i - 1].get("high"))
        pl = safe_float(candles[i - 1].get("low"))
        pc = safe_float(candles[i - 1].get("close"))

        if None in (h, l, ph, pl, pc):
            continue

        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)

        up_move = h - ph
        down_move = pl - l

        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
        else:
            plus_dm.append(0)

        if down_move > up_move and down_move > 0:
            minus_dm.append(down_move)
        else:
            minus_dm.append(0)

    if len(trs) < period:
        return None

    atr = sum(trs[:period]) / period
    plus_di = sum(plus_dm[:period]) / period
    minus_di = sum(minus_dm[:period]) / period

    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        plus_di = (plus_di * (period - 1) + plus_dm[i]) / period
        minus_di = (minus_di * (period - 1) + minus_dm[i]) / period

    if atr == 0:
        return None

    plus_di = (plus_di / atr) * 100
    minus_di = (minus_di / atr) * 100

    di_sum = plus_di + minus_di
    if di_sum == 0:
        return None

    dx = abs(plus_di - minus_di) / di_sum * 100

    return round(dx, 2)


# ============================================================
# VOLUME
# ============================================================

def volume_spike(candles, lookback=20, multiplier=1.4):
    if not candles or len(candles) < lookback + 1:
        return False

    volumes = [
        safe_float(c.get("volume"))
        for c in candles
        if safe_float(c.get("volume")) is not None
    ]

    if len(volumes) < lookback + 1:
        return False

    current = volumes[-1]
    previous = volumes[-lookback - 1:-1]

    if not previous:
        return False

    return current > mean(previous) * multiplier


# ============================================================
# SWINGS
# ============================================================

def find_swing_highs(candles, strength=2):
    if len(candles) < (strength * 2 + 1):
        return []

    result = []

    for i in range(strength, len(candles) - strength):
        high = safe_float(candles[i].get("high"))
        if high is None:
            continue

        valid = True

        for j in range(1, strength + 1):
            left = safe_float(candles[i - j].get("high"))
            right = safe_float(candles[i + j].get("high"))

            if left is None or right is None:
                valid = False
                break

            if high <= left or high <= right:
                valid = False
                break

        if valid:
            result.append({"index": i, "price": high})

    return result


def find_swing_lows(candles, strength=2):
    if len(candles) < (strength * 2 + 1):
        return []

    result = []

    for i in range(strength, len(candles) - strength):
        low = safe_float(candles[i].get("low"))
        if low is None:
            continue

        valid = True

        for j in range(1, strength + 1):
            left = safe_float(candles[i - j].get("low"))
            right = safe_float(candles[i + j].get("low"))

            if left is None or right is None:
                valid = False
                break

            if low >= left or low >= right:
                valid = False
                break

        if valid:
            result.append({"index": i, "price": low})

    return result


# ============================================================
# MARKET STRUCTURE
# ============================================================

def market_structure(candles):
    if not candles or len(candles) < 30:
        return "RANGE"

    highs = find_swing_highs(candles, 2)
    lows = find_swing_lows(candles, 2)

    if len(highs) < 2 or len(lows) < 2:
        return "RANGE"

    previous_high = highs[-2]["price"]
    current_high = highs[-1]["price"]

    previous_low = lows[-2]["price"]
    current_low = lows[-1]["price"]

    if current_high > previous_high and current_low > previous_low:
        return "BULLISH"

    if current_high < previous_high and current_low < previous_low:
        return "BEARISH"

    return "RANGE"


# ============================================================
# EMA DIRECTION
# ============================================================

def ema_direction(candles):
    if not candles:
        return "RANGE"

    closes = [
        safe_float(c.get("close"))
        for c in candles
        if safe_float(c.get("close")) is not None
    ]

    if len(closes) < 200:
        return "RANGE"

    e50 = ema(closes, 50)
    e200 = ema(closes, 200)

    if e50 is None or e200 is None:
        return "RANGE"

    price = closes[-1]

    if price > e50 > e200:
        return "BULLISH"

    if price < e50 < e200:
        return "BEARISH"

    return "RANGE"


# ============================================================
# 15M MTF CONFIRMATION
# ============================================================

def mtf_confirmation(m15, direction):
    if not m15 or len(m15) < 30:
        return False

    closes = [
        safe_float(c.get("close"))
        for c in m15[-50:]
        if safe_float(c.get("close")) is not None
    ]

    if len(closes) < 21:
        return False

    ema_fast = ema(closes, 9)
    ema_slow = ema(closes, 21)

    if ema_fast is None or ema_slow is None:
        return False

    price = closes[-1]

    if direction == "LONG":
        return price > ema_fast > ema_slow

    if direction == "SHORT":
        return price < ema_fast < ema_slow

    return False


# ============================================================
# FAKE BREAKOUT FILTER (NEW in v8.2)
# ============================================================

def is_breakout_valid(candles, break_index, direction, tolerance=0.01):
    """
    بررسی می‌کند که شکست قبلی، واقعی بوده یا جعلی (fake breakout).

    اگر در 20 کندل بعد از شکست، قیمت بیش از tolerance به سطح شکست
    برگردد، یعنی شکست جعلی بوده.

    tolerance=0.01 یعنی 1% برگشت مجاز است.
    """
    if break_index is None:
        return False

    if break_index < 0 or break_index >= len(candles):
        return False

    break_candle = candles[break_index]
    _, _, _, break_close = candle_values(break_candle)

    if break_close is None or break_close <= 0:
        return False

    end = min(break_index + 20, len(candles))

    if direction == "LONG":
        # برای شکست صعودی: قیمت نباید خیلی زیر سطح شکست برگردد
        min_allowed = break_close * (1 - tolerance)

        for i in range(break_index + 1, end):
            _, _, low, _ = candle_values(candles[i])
            if low is not None and low < min_allowed:
                return False

    else:  # SHORT
        # برای شکست نزولی: قیمت نباید خیلی بالای سطح شکست برگردد
        max_allowed = break_close * (1 + tolerance)

        for i in range(break_index + 1, end):
            _, high, _, _ = candle_values(candles[i])
            if high is not None and high > max_allowed:
                return False

    return True


# ============================================================
# STOP HUNT
# ============================================================

def detect_stop_hunt(candles, lookback=15):
    if not candles or len(candles) < lookback + 2:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INSUFFICIENT_DATA"
        }

    current = candles[-1]
    previous = candles[-lookback - 1:-1]

    highs = [
        safe_float(c.get("high"))
        for c in previous
        if safe_float(c.get("high")) is not None
    ]

    lows = [
        safe_float(c.get("low"))
        for c in previous
        if safe_float(c.get("low")) is not None
    ]

    if not highs or not lows:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "NO_LEVEL"
        }

    high_level = max(highs)
    low_level = min(lows)

    o, h, l, c = candle_values(current)

    if None in (o, h, l, c):
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INVALID_CANDLE"
        }

    body = candle_body(current)
    if body <= 0:
        body = max(abs(h - l) * 0.15, 0.00000001)

    if h > high_level and c < high_level:
        if upper_wick(current) >= body * 0.45:
            return {
                "matched": True,
                "direction": "SHORT",
                "level": high_level,
                "reason": "HIGH_SWEEP_RECLAIM"
            }

    if l < low_level and c > low_level:
        if lower_wick(current) >= body * 0.45:
            return {
                "matched": True,
                "direction": "LONG",
                "level": low_level,
                "reason": "LOW_SWEEP_RECLAIM"
            }

    return {
        "matched": False,
        "direction": None,
        "level": None,
        "reason": "NO_STOP_HUNT"
    }


# ============================================================
# THREE TAP
# ============================================================

def detect_three_tap(candles, tolerance=0.006):
    if not candles or len(candles) < 35:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INSUFFICIENT_DATA"
        }

    recent = candles[-80:]
    highs = find_swing_highs(recent, 2)
    lows = find_swing_lows(recent, 2)

    current = candles[-1]
    o, h, l, c = candle_values(current)

    if None in (o, h, l, c):
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INVALID_CANDLE"
        }

    body = candle_body(current)
    upper = upper_wick(current)
    lower = lower_wick(current)

    if len(highs) >= 3:
        taps = highs[-3:]
        levels = [x["price"] for x in taps]
        level = mean(levels)

        if level > 0:
            deviation = max(abs(x - level) / level for x in levels)

            if deviation <= tolerance:
                touched = h >= level * (1 - tolerance)
                rejected = c < level
                body_ok = body >= max((h - l) * 0.20, 0.00000001)
                wick_ok = upper >= body * 0.40

                if touched and rejected and body_ok and wick_ok:
                    return {
                        "matched": True,
                        "direction": "SHORT",
                        "level": level,
                        "reason": "THREE_HIGH_TAPS_REJECTION"
                    }

    if len(lows) >= 3:
        taps = lows[-3:]
        levels = [x["price"] for x in taps]
        level = mean(levels)

        if level > 0:
            deviation = max(abs(x - level) / level for x in levels)

            if deviation <= tolerance:
                touched = l <= level * (1 + tolerance)
                reclaimed = c > level
                body_ok = body >= max((h - l) * 0.20, 0.00000001)
                wick_ok = lower >= body * 0.40

                if touched and reclaimed and body_ok and wick_ok:
                    return {
                        "matched": True,
                        "direction": "LONG",
                        "level": level,
                        "reason": "THREE_LOW_TAPS_REJECTION"
                    }

    return {
        "matched": False,
        "direction": None,
        "level": None,
        "reason": "NO_THREE_TAP"
    }


# ============================================================
# LIQUIDITY ZONE
# ============================================================

def detect_liquidity_zone(candles, tolerance=0.006):
    if not candles or len(candles) < 35:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INSUFFICIENT_DATA"
        }

    recent = candles[-80:]
    highs = find_swing_highs(recent, 2)
    lows = find_swing_lows(recent, 2)

    current = candles[-1]
    o, h, l, c = candle_values(current)

    if None in (o, h, l, c):
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INVALID_CANDLE"
        }

    body = candle_body(current)
    upper = upper_wick(current)
    lower = lower_wick(current)

    if len(highs) >= 3:
        candidates = [x["price"] for x in highs[-6:]]

        for base in candidates:
            cluster = [
                x for x in candidates
                if abs(x - base) / base <= tolerance
            ]

            if len(cluster) >= 3:
                zone = mean(cluster)
                swept = h > zone
                reclaimed = c < zone
                body_ok = body >= max((h - l) * 0.20, 0.00000001)
                wick_ok = upper >= body * 0.40

                if swept and reclaimed and body_ok and wick_ok:
                    return {
                        "matched": True,
                        "direction": "SHORT",
                        "level": zone,
                        "reason": "HIGH_LIQUIDITY_SWEEP_REJECTION"
                    }

    if len(lows) >= 3:
        candidates = [x["price"] for x in lows[-6:]]

        for base in candidates:
            cluster = [
                x for x in candidates
                if abs(x - base) / base <= tolerance
            ]

            if len(cluster) >= 3:
                zone = mean(cluster)
                swept = l < zone
                reclaimed = c > zone
                body_ok = body >= max((h - l) * 0.20, 0.00000001)
                wick_ok = lower >= body * 0.40

                if swept and reclaimed and body_ok and wick_ok:
                    return {
                        "matched": True,
                        "direction": "LONG",
                        "level": zone,
                        "reason": "LOW_LIQUIDITY_SWEEP_REJECTION"
                    }

    return {
        "matched": False,
        "direction": None,
        "level": None,
        "reason": "NO_LIQUIDITY_ZONE"
    }


# ============================================================
# BREAKER BLOCK (v8.2 - with fake breakout filter)
# ============================================================

def detect_breaker_block(candles, lookback=40, tolerance=0.004):
    if not candles or len(candles) < lookback + 5:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INSUFFICIENT_DATA"
        }

    recent = candles[-lookback:]
    current = candles[-1]

    o, h, l, c = candle_values(current)
    if None in (o, h, l, c):
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INVALID_CANDLE"
        }

    body = candle_body(current)
    upper = upper_wick(current)
    lower = lower_wick(current)

    # ---- SHORT: Bullish OB broken ----
    for i in range(2, len(recent) - 3):
        ob = recent[i]
        ob_o, ob_h, ob_l, ob_c = candle_values(ob)

        if None in (ob_o, ob_h, ob_l, ob_c):
            continue

        if ob_c >= ob_o:
            continue

        ob_high = max(ob_o, ob_c)
        ob_low = ob_l

        broken = False
        break_index = None

        for j in range(i + 1, min(i + 8, len(recent))):
            nxt = recent[j]
            nxt_o, nxt_h, nxt_l, nxt_c = candle_values(nxt)

            if None in (nxt_o, nxt_h, nxt_l, nxt_c):
                continue

            if nxt_c < ob_low and nxt_c < nxt_o:
                broken = True
                break_index = j
                break

        if not broken:
            continue

        # NEW: بررسی fake breakout
        if not is_breakout_valid(recent, break_index, "SHORT"):
            continue

        fvg_present = False
        if break_index is not None and break_index + 2 < len(recent):
            k1 = recent[break_index]
            k3 = recent[break_index + 2]

            _, k1_h, _, _ = candle_values(k1)
            _, _, k3_l, _ = candle_values(k3)

            if k1_h is not None and k3_l is not None:
                if k1_h < k3_l:
                    fvg_present = True

        zone_top = ob_high
        zone_bottom = ob_low

        touched = h >= zone_bottom and l <= zone_top

        if not touched:
            continue

        bearish_rejection = (
            c < o
            and c < zone_top
            and upper >= body * 0.35
        )

        body_ok = body >= max((h - l) * 0.20, 0.00000001)

        if bearish_rejection and body_ok:
            return {
                "matched": True,
                "direction": "SHORT",
                "level": zone_top,
                "reason": (
                    "BREAKER_BLOCK_SHORT"
                    + ("_FVG" if fvg_present else "")
                )
            }

    # ---- LONG: Bearish OB broken ----
    for i in range(2, len(recent) - 3):
        ob = recent[i]
        ob_o, ob_h, ob_l, ob_c = candle_values(ob)

        if None in (ob_o, ob_h, ob_l, ob_c):
            continue

        if ob_c <= ob_o:
            continue

        ob_high = ob_h
        ob_low = min(ob_o, ob_c)

        broken = False
        break_index = None

        for j in range(i + 1, min(i + 8, len(recent))):
            nxt = recent[j]
            nxt_o, nxt_h, nxt_l, nxt_c = candle_values(nxt)

            if None in (nxt_o, nxt_h, nxt_l, nxt_c):
                continue

            if nxt_c > ob_high and nxt_c > nxt_o:
                broken = True
                break_index = j
                break

        if not broken:
            continue

        # NEW: بررسی fake breakout
        if not is_breakout_valid(recent, break_index, "LONG"):
            continue

        fvg_present = False
        if break_index is not None and break_index + 2 < len(recent):
            k1 = recent[break_index]
            k3 = recent[break_index + 2]

            _, _, k1_l, _ = candle_values(k1)
            _, k3_h, _, _ = candle_values(k3)

            if k1_l is not None and k3_h is not None:
                if k1_l > k3_h:
                    fvg_present = True

        zone_top = ob_high
        zone_bottom = ob_low

        touched = h >= zone_bottom and l <= zone_top

        if not touched:
            continue

        bullish_rejection = (
            c > o
            and c > zone_bottom
            and lower >= body * 0.35
        )

        body_ok = body >= max((h - l) * 0.20, 0.00000001)

        if bullish_rejection and body_ok:
            return {
                "matched": True,
                "direction": "LONG",
                "level": zone_bottom,
                "reason": (
                    "BREAKER_BLOCK_LONG"
                    + ("_FVG" if fvg_present else "")
                )
            }

    return {
        "matched": False,
        "direction": None,
        "level": None,
        "reason": "NO_BREAKER_BLOCK"
    }


# ============================================================
# FVG FILL
# ============================================================

def find_fvgs(candles, lookback=50):
    fvgs = []

    if not candles or len(candles) < 5:
        return fvgs

    recent = candles[-lookback:]

    for i in range(1, len(recent) - 1):
        k1 = recent[i - 1]
        k2 = recent[i]
        k3 = recent[i + 1]

        _, k1_h, k1_l, _ = candle_values(k1)
        _, _, _, _ = candle_values(k2)
        _, k3_h, k3_l, _ = candle_values(k3)

        if None in (k1_h, k1_l, k3_h, k3_l):
            continue

        if k1_h < k3_l:
            fvgs.append({
                "index": i,
                "top": k3_l,
                "bottom": k1_h,
                "direction": "LONG",
                "ce": (k3_l + k1_h) / 2,
                "filled": False,
                "touch_count": 0,
            })

        if k1_l > k3_h:
            fvgs.append({
                "index": i,
                "top": k1_l,
                "bottom": k3_h,
                "direction": "SHORT",
                "ce": (k1_l + k3_h) / 2,
                "filled": False,
                "touch_count": 0,
            })

    return fvgs


def detect_fvg_fill(candles, lookback=50):
    if not candles or len(candles) < 10:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INSUFFICIENT_DATA"
        }

    fvgs = find_fvgs(candles, lookback)

    if not fvgs:
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "NO_FVG"
        }

    current = candles[-1]
    o, h, l, c = candle_values(current)

    if None in (o, h, l, c):
        return {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "INVALID_CANDLE"
        }

    body = candle_body(current)
    upper = upper_wick(current)
    lower = lower_wick(current)

    for fvg in reversed(fvgs[-15:]):
        top = fvg["top"]
        bottom = fvg["bottom"]
        ce = fvg["ce"]
        direction = fvg["direction"]

        touch_count = 0
        for k in candles[-30:]:
            _, kh, kl, _ = candle_values(k)
            if kh is None or kl is None:
                continue
            if kh >= bottom and kl <= top:
                touch_count += 1

        if touch_count > 2:
            continue

        if direction == "LONG":
            reached_ce = l <= ce <= h or l <= bottom

            if not reached_ce:
                continue

            bullish_rejection = (
                c > o
                and c > bottom
                and lower >= body * 0.30
            )

            body_ok = body >= max((h - l) * 0.20, 0.00000001)

            if bullish_rejection and body_ok:
                return {
                    "matched": True,
                    "direction": "LONG",
                    "level": ce,
                    "reason": f"FVG_FILL_LONG_TOUCH{touch_count}"
                }

        if direction == "SHORT":
            reached_ce = l <= ce <= h or h >= top

            if not reached_ce:
                continue

            bearish_rejection = (
                c < o
                and c < top
                and upper >= body * 0.30
            )

            body_ok = body >= max((h - l) * 0.20, 0.00000001)

            if bearish_rejection and body_ok:
                return {
                    "matched": True,
                    "direction": "SHORT",
                    "level": ce,
                    "reason": f"FVG_FILL_SHORT_TOUCH{touch_count}"
                }

    return {
        "matched": False,
        "direction": None,
        "level": None,
        "reason": "NO_FVG_FILL"
    }


# ============================================================
# 5M ENTRY TRIGGER
# ============================================================

def entry_trigger(candles, direction):
    if not candles or len(candles) < 3:
        return False

    current = candles[-1]
    previous = candles[-2]

    o, h, l, c = candle_values(current)
    po, ph, pl, pc = candle_values(previous)

    if None in (o, h, l, c, po, ph, pl, pc):
        return False

    body = candle_body(current)
    candle_range = h - l

    if candle_range <= 0:
        return False

    upper = upper_wick(current)
    lower = lower_wick(current)

    if direction == "LONG":

        bullish = c > o
        body_ok = body >= candle_range * 0.45

        close_position = (c - l) / candle_range
        close_strong = close_position >= 0.70

        momentum = (
            c > ph
            or c > pc
        )

        rejection_ok = upper <= body * 1.20

        return (
            bullish
            and body_ok
            and close_strong
            and momentum
            and rejection_ok
        )

    if direction == "SHORT":

        bearish = c < o
        body_ok = body >= candle_range * 0.45

        close_position = (h - c) / candle_range
        close_strong = close_position >= 0.70

        momentum = (
            c < pl
            or c < pc
        )

        rejection_ok = lower <= body * 1.20

        return (
            bearish
            and body_ok
            and close_strong
            and momentum
            and rejection_ok
        )

    return False


# ============================================================
# TRADE LEVELS (v8.2 - min SL 0.6%)
# ============================================================

def calculate_trade_levels(candles, direction, strategy_level=None):
    if not candles or len(candles) < 10:
        return None

    entry = safe_float(candles[-1].get("close"))

    if entry is None or entry <= 0:
        return None

    recent = candles[-15:]

    highs = [
        safe_float(c.get("high"))
        for c in recent
        if safe_float(c.get("high")) is not None
    ]

    lows = [
        safe_float(c.get("low"))
        for c in recent
        if safe_float(c.get("low")) is not None
    ]

    if not highs or not lows:
        return None

    if direction == "LONG":
        candidates = [x for x in lows if x < entry]

        if strategy_level is not None and strategy_level < entry:
            candidates.append(strategy_level)

        if not candidates:
            return None

        support = max(candidates)
        raw_risk = entry - support

        if raw_risk <= 0:
            return None

        minimum_risk = entry * 0.006  # 0.6%

        risk_distance = max(raw_risk, minimum_risk)

        sl = entry - risk_distance

        tp1 = entry + risk_distance * 1.5
        tp2 = entry + risk_distance * 2.5
        tp3 = entry + risk_distance * 3.0

    elif direction == "SHORT":
        candidates = [x for x in highs if x > entry]

        if strategy_level is not None and strategy_level > entry:
            candidates.append(strategy_level)

        if not candidates:
            return None

        resistance = min(candidates)
        raw_risk = resistance - entry

        if raw_risk <= 0:
            return None

        minimum_risk = entry * 0.006  # 0.6%

        risk_distance = max(raw_risk, minimum_risk)

        sl = entry + risk_distance

        tp1 = entry - risk_distance * 1.5
        tp2 = entry - risk_distance * 2.5
        tp3 = entry - risk_distance * 3.0

    else:
        return None

    return {
        "entry": round(entry, 8),
        "sl": round(sl, 8),
        "tp1": round(tp1, 8),
        "tp2": round(tp2, 8),
        "tp3": round(tp3, 8),
        "risk": round(risk_distance, 8),
        "rr": "1:1.5 / 1:2.5 / 1:3"
    }


# ============================================================
# NO TRADE
# ============================================================

def no_trade(
    reason,
    daily="RANGE",
    h4="RANGE",
    h1="RANGE",
    rsi_15m=None,
    strategy_details=None,
    score=0,
    adx_1h=None,
    adx_15m=None,
    mtf_confirmed=False,
):
    if strategy_details is None:
        strategy_details = {
            "STOP_HUNT": {"matched": False, "direction": None, "reason": "NOT_CHECKED"},
            "THREE_TAP": {"matched": False, "direction": None, "reason": "NOT_CHECKED"},
            "LIQUIDITY_ZONE": {"matched": False, "direction": None, "reason": "NOT_CHECKED"},
            "BREAKER_BLOCK": {"matched": False, "direction": None, "reason": "NOT_CHECKED"},
            "FVG_FILL": {"matched": False, "direction": None, "reason": "NOT_CHECKED"},
        }

    return {
        "signal": "NO_TRADE",
        "direction": None,
        "quality": "LOW",
        "score": score,

        "daily": daily,
        "4h": h4,
        "1h": h1,

        "rsi_15m": rsi_15m,
        "adx_1h": adx_1h,
        "adx_15m": adx_15m,
        "mtf_confirmed": mtf_confirmed,

        "volume_spike": False,
        "confirmation": False,

        "strategies": [],
        "strategy": None,
        "strategy_matches": [],

        "strategy_details": strategy_details,

        "stop_hunt": False,
        "three_tap": False,
        "liquidity_zone": False,
        "breaker_block": False,
        "fvg_fill": False,

        "entry": None,
        "sl": None,
        "tp1": None,
        "tp2": None,
        "tp3": None,

        "risk": None,
        "rr": None,

        "reason": reason
    }


# ============================================================
# MAIN ENGINE
# ============================================================

def generate_signal(daily, h4, h1, m15, m5):

    if not all([daily, h4, h1, m15, m5]):
        return no_trade("INSUFFICIENT_MARKET_DATA")

    # MARKET CONTEXT
    daily_direction = market_structure(daily)
    h4_direction = market_structure(h4)
    h1_direction = market_structure(h1)

    # FILTERS
    daily_ema = ema_direction(daily)
    h4_ema = ema_direction(h4)
    h1_ema = ema_direction(h1)

    rsi_15m = calculate_rsi(m15)
    volume_is_spike = volume_spike(m5)

    # ADX
    adx_1h = calculate_adx(h1)
    adx_15m = calculate_adx(m15)

    # --------------------------------------------------------
    # ADX_15M FILTER FOR SWEEP STRATEGIES
    # --------------------------------------------------------
    if adx_15m is not None and adx_15m < 30:
        stop_hunt = {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "ADX_15M_LOW_RANGE",
        }
        three_tap = {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "ADX_15M_LOW_RANGE",
        }
        liquidity_zone = {
            "matched": False,
            "direction": None,
            "level": None,
            "reason": "ADX_15M_LOW_RANGE",
        }
    else:
        stop_hunt = detect_stop_hunt(m5)
        three_tap = detect_three_tap(m5)
        liquidity_zone = detect_liquidity_zone(m5)

    # --------------------------------------------------------
    # BREAKER_BLOCK and FVG_FILL on 15M (v8.2)
    # --------------------------------------------------------
    breaker_block = detect_breaker_block(m15)
    fvg_fill = detect_fvg_fill(m15)

    strategy_details = {
        "STOP_HUNT": stop_hunt,
        "THREE_TAP": three_tap,
        "LIQUIDITY_ZONE": liquidity_zone,
        "BREAKER_BLOCK": breaker_block,
        "FVG_FILL": fvg_fill,
    }

    # VALID SETUPS
    valid_setups = []

    for name, data in strategy_details.items():
        if not isinstance(data, dict):
            continue

        if data.get("matched") and data.get("direction") in ("LONG", "SHORT"):
            valid_setups.append(name)

    if not valid_setups:
        return no_trade(
            "NO_MAIN_SETUP",
            daily_direction,
            h4_direction,
            h1_direction,
            rsi_15m,
            strategy_details,
            adx_1h=adx_1h,
            adx_15m=adx_15m,
        )

    # DIRECTION
    if h1_direction == "BULLISH":
        direction = "LONG"

    elif h1_direction == "BEARISH":
        direction = "SHORT"

    else:
        setup_directions = []

        for name in valid_setups:
            setup_direction = strategy_details[name].get("direction")

            if setup_direction in ("LONG", "SHORT"):
                setup_directions.append(setup_direction)

        unique_directions = list(set(setup_directions))

        if not unique_directions:
            return no_trade(
                "1H_RANGE_NO_DIRECTION",
                daily_direction, h4_direction, h1_direction,
                rsi_15m, strategy_details,
                adx_1h=adx_1h, adx_15m=adx_15m,
            )

        if len(unique_directions) > 1:
            return no_trade(
                "1H_RANGE_CONFLICTING_SETUPS",
                daily_direction, h4_direction, h1_direction,
                rsi_15m, strategy_details,
                adx_1h=adx_1h, adx_15m=adx_15m,
            )

        direction = unique_directions[0]

    # MATCHING STRATEGIES
    matching_strategies = []

    for name, data in strategy_details.items():
        if not isinstance(data, dict):
            continue
        if not data.get("matched"):
            continue
        if data.get("direction") == direction:
            matching_strategies.append(name)

    if not matching_strategies:
        opposite_strategies = []

        for name, data in strategy_details.items():
            if not isinstance(data, dict):
                continue
            if not data.get("matched"):
                continue
            strategy_direction = data.get("direction")
            if strategy_direction:
                opposite_strategies.append(f"{name}_{strategy_direction}")

        if opposite_strategies:
            reason = "STRATEGY_OPPOSITE_DIRECTION:" + ",".join(opposite_strategies)
        else:
            reason = "NO_MATCHING_SETUP"

        return no_trade(
            reason,
            daily_direction, h4_direction, h1_direction,
            rsi_15m, strategy_details,
            adx_1h=adx_1h, adx_15m=adx_15m,
        )

    # 5M ENTRY TRIGGER
    confirmation = entry_trigger(m5, direction)

    if not confirmation:
        return no_trade(
            "5M_ENTRY_TRIGGER_MISSING",
            daily_direction, h4_direction, h1_direction,
            rsi_15m, strategy_details,
            adx_1h=adx_1h, adx_15m=adx_15m,
        )

    # 15M MTF CONFIRMATION
    mtf_confirmed = mtf_confirmation(m15, direction)

    if not mtf_confirmed:
        return no_trade(
            "MTF_15M_NOT_CONFIRMED",
            daily_direction, h4_direction, h1_direction,
            rsi_15m, strategy_details,
            adx_1h=adx_1h, adx_15m=adx_15m,
            mtf_confirmed=False,
        )

    # SCORE
    score = 0

    # CORE SETUP
    score += 2
    score += 2

    # 1H CONTEXT
    if h1_direction in ("BULLISH", "BEARISH"):
        score += 2
    else:
        score += 1

    # MULTIPLE STRATEGIES
    if len(matching_strategies) >= 2:
        score += 1
    if len(matching_strategies) >= 3:
        score += 1

    # DAILY + 4H ALIGNMENT
    if (
        (direction == "LONG" and daily_direction == "BULLISH")
        or (direction == "SHORT" and daily_direction == "BEARISH")
    ):
        score += 1

    if (
        (direction == "LONG" and h4_direction == "BULLISH")
        or (direction == "SHORT" and h4_direction == "BEARISH")
    ):
        score += 1

    # RSI
    if rsi_15m is not None:
        if direction == "LONG":
            if 40 <= rsi_15m < 68:
                score += 1
            elif rsi_15m >= 68:
                score -= 1
        elif direction == "SHORT":
            if 32 < rsi_15m <= 60:
                score += 1
            elif rsi_15m <= 32:
                score -= 1

    # VOLUME
    if volume_is_spike:
        score += 1

    # MTF BONUS
    if mtf_confirmed:
        score += 1

    # ADX REGIME
    regime_ok = True

    if adx_1h is not None:
        if adx_1h < 18:
            regime_ok = False
            score -= 3
        elif adx_1h < 25:
            score -= 1
        elif adx_1h > 40:
            score += 1

    # RANGE PENALTY
    if h1_direction == "RANGE":
        if len(matching_strategies) == 1:
            score -= 1
        elif len(matching_strategies) >= 2:
            score += 1

    # QUALITY GATE
    if score < 10 or not regime_ok:
        return no_trade(
            "SIGNAL_QUALITY_TOO_LOW",
            daily_direction, h4_direction, h1_direction,
            rsi_15m, strategy_details, score,
            adx_1h=adx_1h, adx_15m=adx_15m,
            mtf_confirmed=mtf_confirmed,
        )

    # STRATEGY PRIORITY
    priority = [
        "BREAKER_BLOCK",
        "STOP_HUNT",
        "LIQUIDITY_ZONE",
        "FVG_FILL",
        "THREE_TAP",
    ]

    selected_strategy = None
    strategy_level = None

    for name in priority:
        if name in matching_strategies:
            selected_strategy = name
            strategy_level = strategy_details[name].get("level")
            break

    # TRADE LEVELS
    levels = calculate_trade_levels(m5, direction, strategy_level)

    if levels is None:
        return no_trade(
            "LEVEL_CALCULATION_FAILED",
            daily_direction, h4_direction, h1_direction,
            rsi_15m, strategy_details, score,
            adx_1h=adx_1h, adx_15m=adx_15m,
            mtf_confirmed=mtf_confirmed,
        )

    # FINAL HIGH SIGNAL
    return {
        "signal": direction,
        "direction": direction,

        "quality": "HIGH",
        "score": score,

        "daily": daily_direction,
        "4h": h4_direction,
        "1h": h1_direction,

        "daily_ema": daily_ema,
        "4h_ema": h4_ema,
        "1h_ema": h1_ema,

        "rsi_15m": rsi_15m,
        "adx_1h": adx_1h,
        "adx_15m": adx_15m,
        "mtf_confirmed": mtf_confirmed,

        "volume_spike": volume_is_spike,
        "confirmation": confirmation,

        "strategies": matching_strategies,
        "strategy_matches": matching_strategies,
        "strategy": selected_strategy,
        "strategy_details": strategy_details,

        "stop_hunt": "STOP_HUNT" in matching_strategies,
        "three_tap": "THREE_TAP" in matching_strategies,
        "liquidity_zone": "LIQUIDITY_ZONE" in matching_strategies,
        "breaker_block": "BREAKER_BLOCK" in matching_strategies,
        "fvg_fill": "FVG_FILL" in matching_strategies,

        "entry": levels["entry"],
        "sl": levels["sl"],
        "tp1": levels["tp1"],
        "tp2": levels["tp2"],
        "tp3": levels["tp3"],

        "risk": levels["risk"],
        "rr": levels["rr"],

        "reason": (
            "1H_RANGE_SETUP + "
            if h1_direction == "RANGE"
            else "1H_DIRECTION + "
        )
        + selected_strategy
        + " + 5M_ENTRY + MTF_15M"
    }
