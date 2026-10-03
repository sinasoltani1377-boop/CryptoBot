# ============================================================
# CryptoBot - Analysis Engine v9
#
# Main Timeframes:
#   Daily = Macro Trend
#   4H    = Higher Timeframe Confirmation
#   1H    = Main Trading Structure
#   15M   = Setup Confirmation
#   5M    = Entry Trigger
#
# STRATEGIES:
#   1. TREND_FOLLOWING
#   2. PULLBACK
#   3. BREAKOUT
#   4. REVERSAL
#   5. RANGE_TRADING
#
# SL:
#   Dynamic Swing + ATR Buffer
#
# TP:
#   TP1 = 1.5R
#   TP2 = 2.5R
#   TP3 = 3.0R
#
# Only HIGH quality signals are returned as active trades.
# ============================================================

import math
import logging

logger = logging.getLogger(__name__)


# ============================================================
# BASIC HELPERS
# ============================================================

def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace(",", "").strip()

        return float(value)

    except Exception:
        return default


def candle_values(candle):
    """
    Supports common Toobit candle formats.

    Expected:
        [time, open, high, low, close, volume]

    Also attempts dict formats.
    """

    try:

        if isinstance(candle, dict):

            o = candle.get("open", candle.get("o", 0))
            h = candle.get("high", candle.get("h", 0))
            l = candle.get("low", candle.get("l", 0))
            c = candle.get("close", candle.get("c", 0))
            v = candle.get("volume", candle.get("v", 0))

            return (
                safe_float(o),
                safe_float(h),
                safe_float(l),
                safe_float(c),
                safe_float(v),
            )

        if isinstance(candle, (list, tuple)):

            if len(candle) >= 6:

                return (
                    safe_float(candle[1]),
                    safe_float(candle[2]),
                    safe_float(candle[3]),
                    safe_float(candle[4]),
                    safe_float(candle[5]),
                )

    except Exception:
        pass

    return 0.0, 0.0, 0.0, 0.0, 0.0


def normalize_candles(candles):
    result = []

    if not candles:
        return result

    for c in candles:

        try:

            o, h, l, cl, v = candle_values(c)

            if (
                o > 0
                and h > 0
                and l > 0
                and cl > 0
            ):

                result.append({
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": cl,
                    "volume": v
                })

        except Exception:
            continue

    return result


def candle_body(c):
    return abs(
        safe_float(c.get("close"))
        - safe_float(c.get("open"))
    )


def upper_wick(c):
    return (
        safe_float(c.get("high"))
        - max(
            safe_float(c.get("open")),
            safe_float(c.get("close"))
        )
    )


def lower_wick(c):
    return (
        min(
            safe_float(c.get("open")),
            safe_float(c.get("close"))
        )
        - safe_float(c.get("low"))
    )


# ============================================================
# EMA
# ============================================================

def ema(values, period):
    values = [
        safe_float(x)
        for x in values
        if safe_float(x) > 0
    ]

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (
            (price - result) * multiplier
        ) + result

    return result


def ema_direction(candles):

    candles = normalize_candles(candles)

    if len(candles) < 60:
        return "RANGE"

    closes = [
        x["close"]
        for x in candles
    ]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    if e20 is None or e50 is None:
        return "RANGE"

    price = closes[-1]

    if (
        price > e20
        and e20 > e50
    ):
        return "BULLISH"

    if (
        price < e20
        and e20 < e50
    ):
        return "BEARISH"

    return "RANGE"


# ============================================================
# RSI
# ============================================================

def calculate_rsi(candles, period=14):

    candles = normalize_candles(candles)

    if len(candles) < period + 2:
        return 50.0

    closes = [
        x["close"]
        for x in candles
    ]

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

    avg_gain = (
        sum(gains[-period:]) / period
    )

    avg_loss = (
        sum(losses[-period:]) / period
    )

    if avg_loss == 0:

        if avg_gain == 0:
            return 50.0

        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):

    candles = normalize_candles(candles)

    if len(candles) < period + 2:
        return 0.0

    trs = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        high = current["high"]
        low = current["low"]
        prev_close = previous["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        trs.append(tr)

    if len(trs) < period:
        return 0.0

    return sum(
        trs[-period:]
    ) / period


# ============================================================
# ADX
# ============================================================

def calculate_adx(candles, period=14):

    candles = normalize_candles(candles)

    if len(candles) < period * 2:
        return 0.0

    trs = []
    plus_dm = []
    minus_dm = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        high = current["high"]
        low = current["low"]

        prev_high = previous["high"]
        prev_low = previous["low"]
        prev_close = previous["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        up_move = high - prev_high
        down_move = prev_low - low

        plus = (
            up_move
            if up_move > down_move and up_move > 0
            else 0
        )

        minus = (
            down_move
            if down_move > up_move and down_move > 0
            else 0
        )

        trs.append(tr)
        plus_dm.append(plus)
        minus_dm.append(minus)

    if len(trs) < period:
        return 0.0

    atr = sum(
        trs[-period:]
    ) / period

    if atr == 0:
        return 0.0

    plus_di = (
        sum(plus_dm[-period:])
        / atr
        / period
        * 100
    )

    minus_di = (
        sum(minus_dm[-period:])
        / atr
        / period
        * 100
    )

    denominator = (
        plus_di + minus_di
    )

    if denominator == 0:
        return 0.0

    dx = (
        abs(plus_di - minus_di)
        / denominator
        * 100
    )

    return dx


# ============================================================
# VOLUME SPIKE
# ============================================================

def volume_spike(candles, multiplier=1.5):

    candles = normalize_candles(candles)

    if len(candles) < 25:
        return False

    volumes = [
        x["volume"]
        for x in candles
    ]

    recent = volumes[-1]

    previous = volumes[-21:-1]

    if not previous:
        return False

    average = (
        sum(previous)
        / len(previous)
    )

    if average <= 0:
        return False

    return recent >= (
        average * multiplier
    )


# ============================================================
# MARKET STRUCTURE
# ============================================================

def find_swing_highs(candles, strength=2):

    candles = normalize_candles(candles)

    highs = []

    for i in range(
        strength,
        len(candles) - strength
    ):

        current = candles[i]["high"]

        is_swing = True

        for j in range(
            1,
            strength + 1
        ):

            if (
                current
                <= candles[i - j]["high"]
                or current
                <= candles[i + j]["high"]
            ):

                is_swing = False
                break

        if is_swing:
            highs.append({
                "index": i,
                "price": current
            })

    return highs


def find_swing_lows(candles, strength=2):

    candles = normalize_candles(candles)

    lows = []

    for i in range(
        strength,
        len(candles) - strength
    ):

        current = candles[i]["low"]

        is_swing = True

        for j in range(
            1,
            strength + 1
        ):

            if (
                current
                >= candles[i - j]["low"]
                or current
                >= candles[i + j]["low"]
            ):

                is_swing = False
                break

        if is_swing:
            lows.append({
                "index": i,
                "price": current
            })

    return lows


def market_structure(candles):

    candles = normalize_candles(candles)

    if len(candles) < 30:
        return "RANGE"

    highs = find_swing_highs(
        candles,
        strength=2
    )

    lows = find_swing_lows(
        candles,
        strength=2
    )

    if len(highs) < 2 or len(lows) < 2:
        return "RANGE"

    h1 = highs[-2]["price"]
    h2 = highs[-1]["price"]

    l1 = lows[-2]["price"]
    l2 = lows[-1]["price"]

    if (
        h2 > h1
        and l2 > l1
    ):
        return "BULLISH"

    if (
        h2 < h1
        and l2 < l1
    ):
        return "BEARISH"

    return "RANGE"


# ============================================================
# TREND STRENGTH
# ============================================================

def trend_strength(candles):

    candles = normalize_candles(candles)

    if len(candles) < 60:
        return 0.0

    closes = [
        x["close"]
        for x in candles
    ]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    if e20 is None or e50 is None:
        return 0.0

    if e50 == 0:
        return 0.0

    return abs(
        e20 - e50
    ) / e50 * 100


# ============================================================
# 15M CONFIRMATION
# ============================================================

def mtf_confirmation(candles, direction):

    candles = normalize_candles(candles)

    if len(candles) < 40:
        return False

    closes = [
        x["close"]
        for x in candles
    ]

    e9 = ema(closes, 9)
    e21 = ema(closes, 21)

    if e9 is None or e21 is None:
        return False

    last = closes[-1]

    if direction == "LONG":

        return (
            e9 > e21
            and last > e9
        )

    if direction == "SHORT":

        return (
            e9 < e21
            and last < e9
        )

    return False


# ============================================================
# 5M ENTRY TRIGGER
# ============================================================

def entry_trigger(candles, direction):

    candles = normalize_candles(candles)

    if len(candles) < 10:
        return False

    last = candles[-1]
    previous = candles[-2]

    body = candle_body(last)

    if body <= 0:
        return False

    if direction == "LONG":

        bullish = (
            last["close"]
            > last["open"]
        )

        stronger = (
            body
            >= candle_body(previous) * 0.8
        )

        close_near_high = (
            (last["high"] - last["close"])
            <= body * 0.35
        )

        return (
            bullish
            and stronger
            and close_near_high
        )

    if direction == "SHORT":

        bearish = (
            last["close"]
            < last["open"]
        )

        stronger = (
            body
            >= candle_body(previous) * 0.8
        )

        close_near_low = (
            (last["close"] - last["low"])
            <= body * 0.35
        )

        return (
            bearish
            and stronger
            and close_near_low
        )

    return False


# ============================================================
# STRATEGY 1
# TREND FOLLOWING
# ============================================================

def strategy_trend_following(
    daily,
    h4,
    h1,
    m15,
    m5,
    direction
):

    if direction not in (
        "LONG",
        "SHORT"
    ):
        return False, "NO_DIRECTION"

    structure = market_structure(h1)
    ema_dir = ema_direction(h1)

    if direction == "LONG":

        if structure != "BULLISH":
            return False, "1H_NOT_BULLISH"

        if ema_dir != "BULLISH":
            return False, "1H_EMA_NOT_BULLISH"

        if (
            market_structure(h4)
            == "BEARISH"
        ):
            return False, "4H_OPPOSITE"

        if (
            market_structure(daily)
            == "BEARISH"
        ):
            return False, "DAILY_OPPOSITE"

    else:

        if structure != "BEARISH":
            return False, "1H_NOT_BEARISH"

        if ema_dir != "BEARISH":
            return False, "1H_EMA_NOT_BEARISH"

        if (
            market_structure(h4)
            == "BULLISH"
        ):
            return False, "4H_OPPOSITE"

        if (
            market_structure(daily)
            == "BULLISH"
        ):
            return False, "DAILY_OPPOSITE"

    if not mtf_confirmation(
        m15,
        direction
    ):
        return False, "15M_NO_CONFIRMATION"

    if not entry_trigger(
        m5,
        direction
    ):
        return False, "5M_NO_TRIGGER"

    return True, "TREND_CONFIRMED"


# ============================================================
# STRATEGY 2
# PULLBACK
# ============================================================

def strategy_pullback(
    h1,
    m15,
    m5,
    direction
):

    candles = normalize_candles(h1)

    if len(candles) < 60:
        return False, "NOT_ENOUGH_DATA"

    structure = market_structure(h1)
    ema_dir = ema_direction(h1)

    if direction == "LONG":

        if structure != "BULLISH":
            return False, "NO_BULLISH_STRUCTURE"

        if ema_dir != "BULLISH":
            return False, "NO_BULLISH_EMA"

    elif direction == "SHORT":

        if structure != "BEARISH":
            return False, "NO_BEARISH_STRUCTURE"

        if ema_dir != "BEARISH":
            return False, "NO_BEARISH_EMA"

    else:
        return False, "NO_DIRECTION"

    closes = [
        x["close"]
        for x in candles
    ]

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    if e20 is None or e50 is None:
        return False, "NO_EMA"

    recent = candles[-5:]

    recent_low = min(
        x["low"]
        for x in recent
    )

    recent_high = max(
        x["high"]
        for x in recent
    )

    last = candles[-1]

    # --------------------------------------------------------
    # LONG PULLBACK
    # --------------------------------------------------------

    if direction == "LONG":

        touched_zone = (
            recent_low <= e20 * 1.003
            or recent_low <= e50 * 1.003
        )

        rejection = (
            last["close"]
            > last["open"]
            and lower_wick(last)
            > candle_body(last) * 0.3
        )

        if not touched_zone:
            return False, "NO_PULLBACK_ZONE"

        if not rejection:
            return False, "NO_BULLISH_REJECTION"

    # --------------------------------------------------------
    # SHORT PULLBACK
    # --------------------------------------------------------

    else:

        touched_zone = (
            recent_high >= e20 * 0.997
            or recent_high >= e50 * 0.997
        )

        rejection = (
            last["close"]
            < last["open"]
            and upper_wick(last)
            > candle_body(last) * 0.3
        )

        if not touched_zone:
            return False, "NO_PULLBACK_ZONE"

        if not rejection:
            return False, "NO_BEARISH_REJECTION"

    if not mtf_confirmation(
        m15,
        direction
    ):
        return False, "15M_NOT_CONFIRMED"

    if not entry_trigger(
        m5,
        direction
    ):
        return False, "5M_NO_TRIGGER"

    return True, "PULLBACK_CONFIRMED"


# ============================================================
# STRATEGY 3
# BREAKOUT
# ============================================================

def strategy_breakout(
    h1,
    m15,
    m5,
    direction
):

    candles = normalize_candles(m15)

    if len(candles) < 30:
        return False, "NOT_ENOUGH_DATA"

    last = candles[-1]

    previous = candles[-21:-1]

    if not previous:
        return False, "NO_RANGE"

    resistance = max(
        x["high"]
        for x in previous
    )

    support = min(
        x["low"]
        for x in previous
    )

    volume_ok = volume_spike(
        m15,
        multiplier=1.3
    )

    if direction == "LONG":

        breakout = (
            last["close"]
            > resistance
        )

        strong_close = (
            last["close"]
            > last["open"]
            and (
                last["close"]
                - last["open"]
            )
            >= candle_body(last) * 0.7
        )

        if not breakout:
            return False, "NO_BULLISH_BREAKOUT"

        if not volume_ok:
            return False, "NO_BREAKOUT_VOLUME"

        if not strong_close:
            return False, "WEAK_BREAKOUT"

    elif direction == "SHORT":

        breakout = (
            last["close"]
            < support
        )

        strong_close = (
            last["close"]
            < last["open"]
            and (
                last["open"]
                - last["close"]
            )
            >= candle_body(last) * 0.7
        )

        if not breakout:
            return False, "NO_BEARISH_BREAKOUT"

        if not volume_ok:
            return False, "NO_BREAKOUT_VOLUME"

        if not strong_close:
            return False, "WEAK_BREAKOUT"

    else:
        return False, "NO_DIRECTION"

    if not entry_trigger(
        m5,
        direction
    ):
        return False, "5M_NO_TRIGGER"

    return True, "BREAKOUT_CONFIRMED"


# ============================================================
# STRATEGY 4
# REVERSAL
# ============================================================

def strategy_reversal(
    h1,
    m15,
    m5,
    direction
):

    candles = normalize_candles(m15)

    if len(candles) < 40:
        return False, "NOT_ENOUGH_DATA"

    highs = find_swing_highs(
        candles,
        strength=2
    )

    lows = find_swing_lows(
        candles,
        strength=2
    )

    if not highs or not lows:
        return False, "NO_SWINGS"

    last = candles[-1]

    recent_high = max(
        x["high"]
        for x in candles[-15:-1]
    )

    recent_low = min(
        x["low"]
        for x in candles[-15:-1]
    )

    previous = candles[-2]

    # --------------------------------------------------------
    # BULLISH REVERSAL
    # --------------------------------------------------------

    if direction == "LONG":

        sweep = (
            last["low"]
            < recent_low
            and last["close"]
            > recent_low
        )

        structure_shift = (
            last["close"]
            > previous["high"]
        )

        rejection = (
            lower_wick(last)
            > candle_body(last) * 0.5
        )

        if not sweep:
            return False, "NO_LOW_SWEEP"

        if not structure_shift:
            return False, "NO_BULLISH_SHIFT"

        if not rejection:
            return False, "NO_REJECTION"

    # --------------------------------------------------------
    # BEARISH REVERSAL
    # --------------------------------------------------------

    elif direction == "SHORT":

        sweep = (
            last["high"]
            > recent_high
            and last["close"]
            < recent_high
        )

        structure_shift = (
            last["close"]
            < previous["low"]
        )

        rejection = (
            upper_wick(last)
            > candle_body(last) * 0.5
        )

        if not sweep:
            return False, "NO_HIGH_SWEEP"

        if not structure_shift:
            return False, "NO_BEARISH_SHIFT"

        if not rejection:
            return False, "NO_REJECTION"

    else:
        return False, "NO_DIRECTION"

    if not entry_trigger(
        m5,
        direction
    ):
        return False, "5M_NO_TRIGGER"

    return True, "REVERSAL_CONFIRMED"


# ============================================================
# STRATEGY 5
# RANGE TRADING
# ============================================================

def strategy_range(
    h1,
    m15,
    m5,
    direction
):

    candles = normalize_candles(h1)

    if len(candles) < 50:
        return False, "NOT_ENOUGH_DATA"

    structure = market_structure(h1)

    adx = calculate_adx(h1)

    if structure != "RANGE":
        return False, "1H_NOT_RANGE"

    # Range should have weak trend
    if adx > 22:
        return False, "ADX_TOO_HIGH"

    recent = candles[-30:]

    resistance = max(
        x["high"]
        for x in recent
    )

    support = min(
        x["low"]
        for x in recent
    )

    current = candles[-1]["close"]

    range_size = (
        resistance - support
    )

    if range_size <= 0:
        return False, "INVALID_RANGE"

    position = (
        current - support
    ) / range_size

    last = candles[-1]

    # LONG near support
    if direction == "LONG":

        near_support = (
            position <= 0.30
        )

        rejection = (
            lower_wick(last)
            > candle_body(last) * 0.4
        )

        if not near_support:
            return False, "NOT_NEAR_SUPPORT"

        if not rejection:
            return False, "NO_SUPPORT_REJECTION"

    # SHORT near resistance
    elif direction == "SHORT":

        near_resistance = (
            position >= 0.70
        )

        rejection = (
            upper_wick(last)
            > candle_body(last) * 0.4
        )

        if not near_resistance:
            return False, "NOT_NEAR_RESISTANCE"

        if not rejection:
            return False, "NO_RESISTANCE_REJECTION"

    else:
        return False, "NO_DIRECTION"

    if not entry_trigger(
        m5,
        direction
    ):
        return False, "5M_NO_TRIGGER"

    return True, "RANGE_CONFIRMED"


# ============================================================
# DYNAMIC TRADE LEVELS
#
# SL = SWING + ATR BUFFER
#
# Minimum:
#   1.20 ATR
#
# Maximum:
#   3.00 ATR
#
# Maximum risk:
#   3.5%
# ============================================================

def calculate_trade_levels(
    direction,
    entry,
    candles
):

    try:

        entry = safe_float(entry)

        if entry <= 0:
            return None

        candles = normalize_candles(candles)

        if len(candles) < 30:
            return None

        atr = calculate_atr(
            candles,
            period=14
        )

        if atr <= 0:
            return None

        # ----------------------------------------------------
        # Swing detection
        # ----------------------------------------------------

        swing_highs = find_swing_highs(
            candles,
            strength=2
        )

        swing_lows = find_swing_lows(
            candles,
            strength=2
        )

        # ----------------------------------------------------
        # ATR BUFFER
        # ----------------------------------------------------

        buffer = atr * 0.35

        # ----------------------------------------------------
        # LONG
        # ----------------------------------------------------

        if direction == "LONG":

            valid_lows = [
                x["price"]
                for x in swing_lows
                if x["price"] < entry
            ]

            if valid_lows:

                swing_low = max(
                    valid_lows
                )

                sl = (
                    swing_low
                    - buffer
                )

            else:

                sl = (
                    entry
                    - atr * 1.5
                )

            risk = (
                entry - sl
            )

        # ----------------------------------------------------
        # SHORT
        # ----------------------------------------------------

        elif direction == "SHORT":

            valid_highs = [
                x["price"]
                for x in swing_highs
                if x["price"] > entry
            ]

            if valid_highs:

                swing_high = min(
                    valid_highs
                )

                sl = (
                    swing_high
                    + buffer
                )

            else:

                sl = (
                    entry
                    + atr * 1.5
                )

            risk = (
                sl - entry
            )

        else:
            return None

        # ----------------------------------------------------
        # Minimum SL
        # ----------------------------------------------------

        minimum_risk = (
            atr * 1.20
        )

        if risk < minimum_risk:

            if direction == "LONG":

                sl = (
                    entry
                    - minimum_risk
                )

            else:

                sl = (
                    entry
                    + minimum_risk
                )

            risk = minimum_risk

        # ----------------------------------------------------
        # Maximum SL
        # ----------------------------------------------------

        maximum_risk = (
            atr * 3.0
        )

        if risk > maximum_risk:
            return None

        # ----------------------------------------------------
        # Maximum percentage risk
        # ----------------------------------------------------

        risk_pct = (
            risk / entry
        )

        if risk_pct > 0.035:
            return None

        # ----------------------------------------------------
        # TP
        # ----------------------------------------------------

        if direction == "LONG":

            tp1 = (
                entry
                + risk * 1.5
            )

            tp2 = (
                entry
                + risk * 2.5
            )

            tp3 = (
                entry
                + risk * 3.0
            )

        else:

            tp1 = (
                entry
                - risk * 1.5
            )

            tp2 = (
                entry
                - risk * 2.5
            )

            tp3 = (
                entry
                - risk * 3.0
            )

        # ----------------------------------------------------
        # Validation
        # ----------------------------------------------------

        if direction == "LONG":

            if not (
                sl < entry
                < tp1
                < tp2
                < tp3
            ):
                return None

        else:

            if not (
                sl > entry
                > tp1
                > tp2
                > tp3
            ):
                return None

        return {

            "entry": round(
                entry,
                8
            ),

            "sl": round(
                sl,
                8
            ),

            "tp1": round(
                tp1,
                8
            ),

            "tp2": round(
                tp2,
                8
            ),

            "tp3": round(
                tp3,
                8
            ),

            "risk": round(
                risk,
                8
            ),

            "risk_pct": round(
                risk_pct * 100,
                3
            ),

            "rr": "1:3",

            "atr": round(
                atr,
                8
            ),

            "atr_pct": round(
                atr / entry * 100,
                3
            ),

            "sl_method":
                "SWING_ATR_BUFFER"
        }

    except Exception as e:

        logger.error(
            f"calculate_trade_levels error: {e}"
        )

        return None


# ============================================================
# NO TRADE
# ============================================================

def no_trade(
    reason,
    daily="RANGE",
    h4="RANGE",
    h1="RANGE",
    rsi_15m=50.0,
    adx_1h=0.0,
    adx_15m=0.0,
    volume=False,
    mtf=False,
    strategies=None
):

    if strategies is None:
        strategies = []

    return {

        "signal": "NO_TRADE",

        "direction": None,

        "quality": "LOW",

        "score": 0,

        "reason": reason,

        "daily": daily,

        "4h": h4,

        "1h": h1,

        "daily_ema": daily,

        "4h_ema": h4,

        "1h_ema": h1,

        "rsi_15m": round(
            rsi_15m,
            2
        ),

        "adx_1h": round(
            adx_1h,
            2
        ),

        "adx_15m": round(
            adx_15m,
            2
        ),

        "mtf_confirmed": mtf,

        "volume_spike": volume,

        "confirmation": False,

        "strategies": strategies,

        "strategy_matches": strategies,

        "strategy": (
            strategies[0]
            if strategies
            else "NONE"
        ),

        "strategy_details": {},

        "entry": None,

        "sl": None,

        "tp1": None,

        "tp2": None,

        "tp3": None,

        "risk": None,

        "rr": None,

        "trend_following": False,

        "pullback": False,

        "breakout": False,

        "reversal": False,

        "range_trading": False
    }


# ============================================================
# MAIN SIGNAL GENERATOR
# ============================================================

def generate_signal(
    daily,
    h4,
    h1,
    m15,
    m5
):

    try:

        # ====================================================
        # NORMALIZE
        # ====================================================

        daily_c = normalize_candles(
            daily
        )

        h4_c = normalize_candles(
            h4
        )

        h1_c = normalize_candles(
            h1
        )

        m15_c = normalize_candles(
            m15
        )

        m5_c = normalize_candles(
            m5
        )

        if (
            len(daily_c) < 50
            or len(h4_c) < 50
            or len(h1_c) < 50
            or len(m15_c) < 30
            or len(m5_c) < 20
        ):

            return no_trade(
                "NOT_ENOUGH_DATA"
            )

        # ====================================================
        # MARKET CONTEXT
        # ====================================================

        daily_structure = market_structure(
            daily_c
        )

        h4_structure = market_structure(
            h4_c
        )

        h1_structure = market_structure(
            h1_c
        )

        daily_ema = ema_direction(
            daily_c
        )

        h4_ema = ema_direction(
            h4_c
        )

        h1_ema = ema_direction(
            h1_c
        )

        rsi15 = calculate_rsi(
            m15_c
        )

        adx1 = calculate_adx(
            h1_c
        )

        adx15 = calculate_adx(
            m15_c
        )

        volume_ok = volume_spike(
            m5_c,
            multiplier=1.5
        )

        # ====================================================
        # DETERMINE DIRECTION
        # ====================================================

        direction = None

        # Strong 1H direction has priority
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

        # ----------------------------------------------------
        # If 1H is RANGE, allow RANGE / REVERSAL setups
        # ----------------------------------------------------

        else:

            direction = None

        # ====================================================
        # STRATEGY RESULTS
        # ====================================================

        matches = []

        details = {}

        # ====================================================
        # TREND FOLLOWING
        # ====================================================

        if direction:

            ok, reason = strategy_trend_following(
                daily_c,
                h4_c,
                h1_c,
                m15_c,
                m5_c,
                direction
            )

            details[
                "TREND_FOLLOWING"
            ] = reason

            if ok:
                matches.append(
                    "TREND_FOLLOWING"
                )

        # ====================================================
        # PULLBACK
        # ====================================================

        if direction:

            ok, reason = strategy_pullback(
                h1_c,
                m15_c,
                m5_c,
                direction
            )

            details[
                "PULLBACK"
            ] = reason

            if ok:
                matches.append(
                    "PULLBACK"
                )

        # ====================================================
        # BREAKOUT
        # ====================================================

        if direction:

            ok, reason = strategy_breakout(
                h1_c,
                m15_c,
                m5_c,
                direction
            )

            details[
                "BREAKOUT"
            ] = reason

            if ok:
                matches.append(
                    "BREAKOUT"
                )

        # ====================================================
        # REVERSAL
        # ====================================================

        reversal_directions = []

        if direction:
            reversal_directions.append(
                direction
            )
        else:

            # In a range, inspect 5M direction
            last5 = m5_c[-1]

            if (
                last5["close"]
                > last5["open"]
            ):
                reversal_directions.append(
                    "LONG"
                )

            elif (
                last5["close"]
                < last5["open"]
            ):
                reversal_directions.append(
                    "SHORT"
                )

        for rev_direction in reversal_directions:

            ok, reason = strategy_reversal(
                h1_c,
                m15_c,
                m5_c,
                rev_direction
            )

            details[
                "REVERSAL"
            ] = reason

            if ok:

                if direction is None:
                    direction = rev_direction

                matches.append(
                    "REVERSAL"
                )

                break

        # ====================================================
        # RANGE TRADING
        # ====================================================

        range_directions = []

        if direction:
            range_directions.append(
                direction
            )
        else:

            last5 = m5_c[-1]

            if (
                last5["close"]
                > last5["open"]
            ):
                range_directions.append(
                    "LONG"
                )

            else:
                range_directions.append(
                    "SHORT"
                )

        for range_direction in range_directions:

            ok, reason = strategy_range(
                h1_c,
                m15_c,
                m5_c,
                range_direction
            )

            details[
                "RANGE_TRADING"
            ] = reason

            if ok:

                if direction is None:
                    direction = range_direction

                matches.append(
                    "RANGE_TRADING"
                )

                break

        # ====================================================
        # NO VALID STRATEGY
        # ====================================================

        if not matches:

            return no_trade(
                "NO_VALID_STRATEGY",
                daily_structure,
                h4_structure,
                h1_structure,
                rsi15,
                adx1,
                adx15,
                volume_ok,
                False,
                []
            )

        # ====================================================
        # CONTEXT FILTER
        # ====================================================

        # Avoid strong opposite higher timeframe
        # unless reversal/range is explicitly active.

        if direction == "LONG":

            if (
                h4_structure == "BEARISH"
                and "REVERSAL" not in matches
                and "RANGE_TRADING" not in matches
            ):

                return no_trade(
                    "4H_OPPOSITE_TREND",
                    daily_structure,
                    h4_structure,
                    h1_structure,
                    rsi15,
                    adx1,
                    adx15,
                    volume_ok,
                    False,
                    matches
                )

        if direction == "SHORT":

            if (
                h4_structure == "BULLISH"
                and "REVERSAL" not in matches
                and "RANGE_TRADING" not in matches
            ):

                return no_trade(
                    "4H_OPPOSITE_TREND",
                    daily_structure,
                    h4_structure,
                    h1_structure,
                    rsi15,
                    adx1,
                    adx15,
                    volume_ok,
                    False,
                    matches
                )

        # ====================================================
        # 15M FILTER
        # ====================================================

        mtf_ok = mtf_confirmation(
            m15_c,
            direction
        )

        # For reversal/range we allow local confirmation,
        # but trend/pullback/breakout need MTF confirmation.

        strong_trend_strategies = {
            "TREND_FOLLOWING",
            "PULLBACK",
            "BREAKOUT"
        }

        if (
            strong_trend_strategies
            .intersection(matches)
            and not mtf_ok
        ):

            return no_trade(
                "15M_MTF_NOT_CONFIRMED",
                daily_structure,
                h4_structure,
                h1_structure,
                rsi15,
                adx1,
                adx15,
                volume_ok,
                False,
                matches
            )

        # ====================================================
        # 5M ENTRY CONFIRMATION
        # ====================================================

        confirmation = entry_trigger(
            m5_c,
            direction
        )

        if not confirmation:

            return no_trade(
                "5M_NO_CONFIRMATION",
                daily_structure,
                h4_structure,
                h1_structure,
                rsi15,
                adx1,
                adx15,
                volume_ok,
                mtf_ok,
                matches
            )

        # ====================================================
        # SCORE
        # ====================================================

        score = 0

        # ----------------------------------------------------
        # Strategy base
        # ----------------------------------------------------

        if "TREND_FOLLOWING" in matches:
            score += 3

        if "PULLBACK" in matches:
            score += 3

        if "BREAKOUT" in matches:
            score += 3

        if "REVERSAL" in matches:
            score += 3

        if "RANGE_TRADING" in matches:
            score += 3

        # Multiple strategy agreement
        if len(matches) >= 2:
            score += 2

        if len(matches) >= 3:
            score += 1

        # ----------------------------------------------------
        # 1H
        # ----------------------------------------------------

        if direction == "LONG":

            if h1_structure == "BULLISH":
                score += 1

            if h1_ema == "BULLISH":
                score += 1

        elif direction == "SHORT":

            if h1_structure == "BEARISH":
                score += 1

            if h1_ema == "BEARISH":
                score += 1

        # ----------------------------------------------------
        # 4H
        # ----------------------------------------------------

        if direction == "LONG":

            if h4_structure == "BULLISH":
                score += 1

        elif direction == "SHORT":

            if h4_structure == "BEARISH":
                score += 1

        # ----------------------------------------------------
        # Daily
        # ----------------------------------------------------

        if direction == "LONG":

            if daily_structure == "BULLISH":
                score += 1

        elif direction == "SHORT":

            if daily_structure == "BEARISH":
                score += 1

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        if direction == "LONG":

            if 50 <= rsi15 <= 68:
                score += 1

            elif rsi15 > 75:
                score -= 2

        elif direction == "SHORT":

            if 32 <= rsi15 <= 50:
                score += 1

            elif rsi15 < 25:
                score -= 2

        # ----------------------------------------------------
        # MTF
        # ----------------------------------------------------

        if mtf_ok:
            score += 1

        # ----------------------------------------------------
        # Volume
        # ----------------------------------------------------

        if volume_ok:
            score += 1

        # ----------------------------------------------------
        # ADX
        # ----------------------------------------------------

        if (
            adx1 >= 20
            and adx1 <= 45
        ):
            score += 1

        elif adx1 < 15:
            score -= 1

        # ----------------------------------------------------
        # 15M ADX
        # ----------------------------------------------------

        if adx15 >= 18:
            score += 1

        # ----------------------------------------------------
        # Range strategy should have low ADX
        # ----------------------------------------------------

        if (
            "RANGE_TRADING"
            in matches
        ):

            if adx1 <= 22:
                score += 2

            else:
                score -= 2

        # ====================================================
        # QUALITY
        # ====================================================

        # HIGH requires strong confluence
        if score >= 11:

            quality = "HIGH"

        elif score >= 8:

            quality = "MEDIUM"

        else:

            quality = "LOW"

        # ====================================================
        # ONLY HIGH
        # ====================================================

        if quality != "HIGH":

            return no_trade(
                "SIGNAL_QUALITY_TOO_LOW",
                daily_structure,
                h4_structure,
                h1_structure,
                rsi15,
                adx1,
                adx15,
                volume_ok,
                mtf_ok,
                matches
            )

        # ====================================================
        # ENTRY
        # ====================================================

        entry = (
            m5_c[-1]["close"]
        )

        # ====================================================
        # TRADE LEVELS
        # ====================================================

        levels = calculate_trade_levels(
            direction,
            entry,
            h1_c
        )

        if not levels:

            return no_trade(
                "SL_TOO_WIDE_OR_INVALID",
                daily_structure,
                h4_structure,
                h1_structure,
                rsi15,
                adx1,
                adx15,
                volume_ok,
                mtf_ok,
                matches
            )

        # ====================================================
        # FINAL RESULT
        # ====================================================

        primary_strategy = (
            matches[0]
            if matches
            else "NONE"
        )

        return {

            "signal": direction,

            "direction": direction,

            "quality": quality,

            "score": score,

            "reason": "HIGH_CONFLUENCE",

            "daily":
                daily_structure,

            "4h":
                h4_structure,

            "1h":
                h1_structure,

            "daily_ema":
                daily_ema,

            "4h_ema":
                h4_ema,

            "1h_ema":
                h1_ema,

            "rsi_15m":
                round(
                    rsi15,
                    2
                ),

            "adx_1h":
                round(
                    adx1,
                    2
                ),

            "adx_15m":
                round(
                    adx15,
                    2
                ),

            "mtf_confirmed":
                mtf_ok,

            "volume_spike":
                volume_ok,

            "confirmation":
                confirmation,

            "strategies":
                matches,

            "strategy_matches":
                matches,

            "strategy":
                primary_strategy,

            "strategy_details":
                details,

            "trend_following":
                "TREND_FOLLOWING"
                in matches,

            "pullback":
                "PULLBACK"
                in matches,

            "breakout":
                "BREAKOUT"
                in matches,

            "reversal":
                "REVERSAL"
                in matches,

            "range_trading":
                "RANGE_TRADING"
                in matches,

            "entry":
                levels["entry"],

            "sl":
                levels["sl"],

            "tp1":
                levels["tp1"],

            "tp2":
                levels["tp2"],

            "tp3":
                levels["tp3"],

            "risk":
                levels["risk"],

            "risk_pct":
                levels["risk_pct"],

            "rr":
                levels["rr"],

            "atr":
                levels["atr"],

            "atr_pct":
                levels["atr_pct"],

            "sl_method":
                levels["sl_method"]
        }

    except Exception as e:

        logger.exception(
            f"generate_signal error: {e}"
        )

        return no_trade(
            "ANALYSIS_ERROR"
                    )
