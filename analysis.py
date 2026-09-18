# ============================================================
# CryptoBot - Professional Analysis Engine v5
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
    تبدیل انواع مختلف کندل به ساختار استاندارد.
    """

    if isinstance(candle, dict):

        open_price = safe_float(
            candle.get("open", candle.get("o"))
        )

        high_price = safe_float(
            candle.get("high", candle.get("h"))
        )

        low_price = safe_float(
            candle.get("low", candle.get("l"))
        )

        close_price = safe_float(
            candle.get("close", candle.get("c"))
        )

        volume = safe_float(
            candle.get("volume", candle.get("v"))
        )

        timestamp = candle.get(
            "timestamp",
            candle.get("time", candle.get("t"))
        )

        if (
            open_price <= 0
            or high_price <= 0
            or low_price <= 0
            or close_price <= 0
        ):
            return None

        if high_price < low_price:
            return None

        return {
            "timestamp": timestamp,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
        }

    if isinstance(candle, (list, tuple)):

        if len(candle) < 5:
            return None

        open_price = safe_float(candle[1])
        high_price = safe_float(candle[2])
        low_price = safe_float(candle[3])
        close_price = safe_float(candle[4])

        if (
            open_price <= 0
            or high_price <= 0
            or low_price <= 0
            or close_price <= 0
        ):
            return None

        if high_price < low_price:
            return None

        volume = 0.0

        if len(candle) > 5:
            volume = safe_float(candle[5])

        return {
            "timestamp": candle[0],
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
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

        cleaned.append(normalized)

    return cleaned


def get_closes(candles):

    return [
        safe_float(candle.get("close"))
        for candle in candles
        if isinstance(candle, dict)
    ]


def get_highs(candles):

    return [
        safe_float(candle.get("high"))
        for candle in candles
        if isinstance(candle, dict)
    ]


def get_lows(candles):

    return [
        safe_float(candle.get("low"))
        for candle in candles
        if isinstance(candle, dict)
    ]


def get_opens(candles):

    return [
        safe_float(candle.get("open"))
        for candle in candles
        if isinstance(candle, dict)
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
        ema = (
            (price - ema) * multiplier
            + ema
        )

    return ema


def ema_trend(candles):

    candles = clean_candles(candles)

    if len(candles) < 200:
        return "UNKNOWN"

    ema20 = calculate_ema(candles, 20)
    ema50 = calculate_ema(candles, 50)
    ema200 = calculate_ema(candles, 200)

    price = safe_float(
        candles[-1].get("close")
    )

    if (
        ema20 is None
        or ema50 is None
        or ema200 is None
    ):
        return "UNKNOWN"

    if (
        price > ema200
        and ema20 > ema50
        and ema50 > ema200
    ):
        return "BULLISH"

    if (
        price < ema200
        and ema20 < ema50
        and ema50 < ema200
    ):
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
            safe_float(
                candles[j].get("high")
            )
            for j in range(
                i - strength,
                i
            )
        ]

        right_highs = [
            safe_float(
                candles[j].get("high")
            )
            for j in range(
                i + 1,
                i + strength + 1
            )
        ]

        left_lows = [
            safe_float(
                candles[j].get("low")
            )
            for j in range(
                i - strength,
                i
            )
        ]

        right_lows = [
            safe_float(
                candles[j].get("low")
            )
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

    swing_highs, swing_lows = find_swings(
        candles
    )

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

    swing_highs, swing_lows = find_swings(
        candles
    )

    return {
        "direction": get_structure_direction(
            candles
        ),
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

    daily_trend = get_structure_direction(
        daily
    )

    h4_trend = get_structure_direction(
        h4
    )

    h1_trend = get_structure_direction(
        h1
    )

    if (
        daily_trend == "BULLISH"
        and h4_trend == "BULLISH"
    ):
        return "BULLISH"

    if (
        daily_trend == "BEARISH"
        and h4_trend == "BEARISH"
    ):
        return "BEARISH"

    if (
        daily_trend == "BULLISH"
        and h4_trend == "RANGE"
    ):
        return "BULLISH_WEAK"

    if (
        daily_trend == "BEARISH"
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

    previous_candles = candles[:-1]

    swing_highs, swing_lows = find_swings(
        previous_candles
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

    total_range = (
        recent_high - recent_low
    )

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

    swing_highs, swing_lows = find_swings(
        candles
    )

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

    if len(candles) < 4:
        return False

    base_candles = candles[:-3]

    sr = find_support_resistance(
        base_candles
    )

    support = sr.get("support")
    resistance = sr.get("resistance")

    recent = candles[-3:]

    previous_close = safe_float(
        recent[0].get("close")
    )

    breakout_close = safe_float(
        recent[1].get("close")
    )

    current_close = safe_float(
        recent[2].get("close")
    )

    current_low = safe_float(
        recent[2].get("low")
    )

    current_high = safe_float(
        recent[2].get("high")
    )

    if (
        direction == "LONG"
        and resistance is not None
    ):

        breakout = (
            breakout_close > resistance
        )

        retest = (
            current_low <= resistance
            and current_close > resistance
        )

        if breakout and retest:
            return True

    if (
        direction == "SHORT"
        and support is not None
    ):

        breakout = (
            breakout_close < support
        )

        retest = (
            current_high >= support
            and current_close < support
        )

        if breakout and retest:
            return True

    return False


# ============================================================
# CONFIRMATION CANDLE
# ============================================================

def confirmation_candle(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 2:
        return False

    previous = candles[-2]
    current = candles[-1]

    previous_open = safe_float(
        previous.get("open")
    )

    previous_close = safe_float(
        previous.get("close")
    )

    current_open = safe_float(
        current.get("open")
    )

    current_close = safe_float(
        current.get("close")
    )

    previous_body = abs(
        previous_close - previous_open
    )

    current_body = abs(
        current_close - current_open
    )

    if previous_body <= 0:
        return False

    if current_body < previous_body * 1.05:
        return False

    if direction == "LONG":

        return (
            current_close > current_open
            and current_close > previous_close
        )

    if direction == "SHORT":

        return (
            current_close < current_open
            and current_close < previous_close
        )

    return False


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def detect_liquidity_sweep(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 10:
        return False

    swing_highs, swing_lows = find_swings(
        candles[:-1]
    )

    current = candles[-1]

    current_low = safe_float(
        current.get("low")
    )

    current_high = safe_float(
        current.get("high")
    )

    current_close = safe_float(
        current.get("close")
    )

    if direction == "LONG":

        if not swing_lows:
            return False

        last_low = swing_lows[-1]["price"]

        return (
            current_low < last_low
            and current_close > last_low
        )

    if direction == "SHORT":

        if not swing_highs:
            return False

        last_high = swing_highs[-1]["price"]

        return (
            current_high > last_high
            and current_close < last_high
        )

    return False


# ============================================================
# ORDER BLOCK
# ============================================================

def detect_order_block(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 6:
        return False

    for i in range(
        len(candles) - 4,
        len(candles) - 1
    ):

        candle = candles[i]

        open_price = safe_float(
            candle.get("open")
        )

        close_price = safe_float(
            candle.get("close")
        )

        body = abs(
            close_price - open_price
        )

        if body <= 0:
            continue

        next_candles = candles[i + 1:]

        for next_candle in next_candles:

            next_open = safe_float(
                next_candle.get("open")
            )

            next_close = safe_float(
                next_candle.get("close")
            )

            next_body = abs(
                next_close - next_open
            )

            if direction == "LONG":

                bearish = (
                    close_price < open_price
                )

                strong_bullish = (
                    next_close > next_open
                    and next_body >= body * 1.3
                )

                if bearish and strong_bullish:
                    return True

            if direction == "SHORT":

                bullish = (
                    close_price > open_price
                )

                strong_bearish = (
                    next_close < next_open
                    and next_body >= body * 1.3
                )

                if bullish and strong_bearish:
                    return True

    return False


# ============================================================
# RANGE DETECTION
# ============================================================

def detect_range(candles):

    candles = clean_candles(candles)

    if len(candles) < 20:
        return False

    recent = candles[-20:]

    highs = get_highs(recent)
    lows = get_lows(recent)

    if not highs or not lows:
        return False

    highest = max(highs)
    lowest = min(lows)

    if lowest <= 0:
        return False

    range_percent = (
        (highest - lowest)
        / lowest
    ) * 100

    return range_percent <= 5.0


def range_signal(
    candles
):

    candles = clean_candles(candles)

    if len(candles) < 20:
        return None

    recent = candles[-20:]

    highs = get_highs(recent)
    lows = get_lows(recent)

    if not highs or not lows:
        return None

    highest = max(highs)
    lowest = min(lows)

    current_close = safe_float(
        candles[-1].get("close")
    )

    total_range = highest - lowest

    if total_range <= 0:
        return None

    position = (
        current_close - lowest
    ) / total_range

    if position <= 0.35:
        return "LONG"

    if position >= 0.65:
        return "SHORT"

    return None


# ============================================================
# TREND PULLBACK
# ============================================================

def trend_pullback_signal(
    candles,
    direction
):

    candles = clean_candles(candles)

    structure = get_structure_direction(
        candles
    )

    if structure == "RANGE":
        return False

    if direction == "LONG":

        if structure != "BULLISH":
            return False

    if direction == "SHORT":

        if structure != "BEARISH":
            return False

    return detect_pullback(
        candles,
        direction
    )


# ============================================================
# SUPPORT / RESISTANCE REVERSAL
# ============================================================

def sr_reversal_signal(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 10:
        return False

    sr = find_support_resistance(
        candles[:-1]
    )

    support = sr.get("support")
    resistance = sr.get("resistance")

    current = candles[-1]

    current_low = safe_float(
        current.get("low")
    )

    current_high = safe_float(
        current.get("high")
    )

    current_close = safe_float(
        current.get("close")
    )

    if direction == "LONG":

        if support is None:
            return False

        tolerance = support * 0.003

        touched = (
            current_low
            <= support + tolerance
        )

        recovered = (
            current_close > support
        )

        return touched and recovered

    if direction == "SHORT":

        if resistance is None:
            return False

        tolerance = resistance * 0.003

        touched = (
            current_high
            >= resistance - tolerance
        )

        rejected = (
            current_close < resistance
        )

        return touched and rejected

    return False


# ============================================================
# TREND STRENGTH
# ============================================================

def trend_strength(candles):

    candles = clean_candles(candles)

    structure = get_structure_direction(
        candles
    )

    ema = ema_trend(candles)

    score = 0

    if structure in (
        "BULLISH",
        "BEARISH"
    ):
        score += 1

    if structure == "BULLISH":
        score += 1

    if structure == "BEARISH":
        score += 1

    if (
        ema == structure
        and structure in (
            "BULLISH",
            "BEARISH"
        )
    ):
        score += 1

    return {
        "structure": structure,
        "ema": ema,
        "score": score,
    }


# ============================================================
# QUALITY FILTER
# ============================================================

def quality_filter(score):

    if score >= 8:
        return "HIGH"

    if score >= 6:
        return "MEDIUM"

    return "LOW"


# ============================================================
# DIRECTION
# ============================================================

def determine_direction(
    daily,
    h4,
    h1
):

    d = get_structure_direction(daily)
    h4_trend = get_structure_direction(h4)
    h1_trend = get_structure_direction(h1)

    if (
        d == "BULLISH"
        and h4_trend != "BEARISH"
        and h1_trend != "BEARISH"
    ):
        return "LONG"

    if (
        d == "BEARISH"
        and h4_trend != "BULLISH"
        and h1_trend != "BULLISH"
    ):
        return "SHORT"

    return None


# ============================================================
# SIGNAL SCORE
# ============================================================

def calculate_signal_score(
    daily_trend,
    h4_trend,
    h1_trend,
    ema_trend_value,
    main_setup,
    bos,
    confirmation
):

    score = 0

    if daily_trend in (
        "BULLISH",
        "BEARISH"
    ):
        score += 2

    if h4_trend == daily_trend:
        score += 2

    if h1_trend == daily_trend:
        score += 1

    if ema_trend_value == daily_trend:
        score += 1

    if main_setup:
        score += 2

    if bos:
        score += 1

    if confirmation:
        score += 1

    return min(score, 10)


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_trade_levels(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 10:
        return None

    entry = safe_float(
        candles[-1].get("close")
    )

    if entry <= 0:
        return None

    recent = candles[-8:]

    highs = get_highs(recent)
    lows = get_lows(recent)

    if not highs or not lows:
        return None

    if direction == "LONG":

        recent_low = min(lows)

        risk = entry - recent_low

        if risk <= 0:
            return None

        sl = recent_low

        tp1 = entry + risk
        tp2 = entry + risk * 2
        tp3 = entry + risk * 3

    elif direction == "SHORT":

        recent_high = max(highs)

        risk = recent_high - entry

        if risk <= 0:
            return None

        sl = recent_high

        tp1 = entry - risk
        tp2 = entry - risk * 2
        tp3 = entry - risk * 3

    else:
        return None

    if (
        sl <= 0
        or tp1 <= 0
        or tp2 <= 0
        or tp3 <= 0
    ):
        return None

    return {
        "entry": round(entry, 8),
        "sl": round(sl, 8),
        "tp1": round(tp1, 8),
        "tp2": round(tp2, 8),
        "tp3": round(tp3, 8),
        "risk": round(risk, 8),
        "rr": 3.0,
    }


# ============================================================
# NO TRADE RESULT
# ============================================================

def no_trade_result(
    daily_trend="UNKNOWN",
    h4_trend="UNKNOWN",
    h1_trend="UNKNOWN",
    reason="NO_TRADE"
):

    return {
        "signal": "NO_TRADE",
        "direction": None,
        "quality": "LOW",
        "score": 0,
        "reason": reason,

        "daily": daily_trend,
        "4h": h4_trend,
        "1h": h1_trend,

        "entry": None,
        "sl": None,

        "tp1": None,
        "tp2": None,
        "tp3": None,

        "risk": None,
        "rr": None,

        "strategies": [],
        "strategy_matches": [],

        "bos": None,
        "pullback": False,
        "confirmation": False,
        "liquidity_sweep": False,
        "order_block": False,
        "breakout_retest": False,
        "sr_reversal": False,

        "ema": None,
    }


# ============================================================
# MAIN SIGNAL ENGINE
# ============================================================

def generate_signal(
    daily,
    h4,
    h1
):

    # --------------------------------------------------------
    # CLEAN DATA
    # --------------------------------------------------------

    daily = clean_candles(daily)
    h4 = clean_candles(h4)
    h1 = clean_candles(h1)

    # --------------------------------------------------------
    # BASIC DATA VALIDATION
    # --------------------------------------------------------

    if not daily or not h4 or not h1:

        return no_trade_result(
            reason="MISSING_MARKET_DATA"
        )

    if len(h1) < 50:

        return no_trade_result(
            reason="INSUFFICIENT_1H_DATA"
        )

    # --------------------------------------------------------
    # MARKET STRUCTURE
    # --------------------------------------------------------

    daily_trend = get_structure_direction(
        daily
    )

    h4_trend = get_structure_direction(
        h4
    )

    h1_trend = get_structure_direction(
        h1
    )

    # --------------------------------------------------------
    # DAILY MUST HAVE A CLEAR TREND
    # --------------------------------------------------------

    if daily_trend not in (
        "BULLISH",
        "BEARISH"
    ):

        return no_trade_result(
            daily_trend,
            h4_trend,
            h1_trend,
            "DAILY_NO_CLEAR_TREND"
        )

    # --------------------------------------------------------
    # MAIN DIRECTION
    # --------------------------------------------------------

    if daily_trend == "BULLISH":
        direction = "LONG"
    else:
        direction = "SHORT"

    # --------------------------------------------------------
    # HIGHER TIMEFRAME FILTER
    # --------------------------------------------------------

    if direction == "LONG":

        if h4_trend == "BEARISH":

            return no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "4H_OPPOSITE_TREND"
            )

        if h1_trend == "BEARISH":

            return no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "1H_OPPOSITE_TREND"
            )

    if direction == "SHORT":

        if h4_trend == "BULLISH":

            return no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "4H_OPPOSITE_TREND"
            )

        if h1_trend == "BULLISH":

            return no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "1H_OPPOSITE_TREND"
            )

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    ema = ema_details(h1)

    ema_trend_value = ema.get(
        "trend"
    )

    # --------------------------------------------------------
    # STRATEGIES
    # --------------------------------------------------------

    bos = detect_bos(h1)

    pullback = detect_pullback(
        h1,
        direction
    )

    confirmation = confirmation_candle(
        h1,
        direction
    )

    liquidity_sweep = detect_liquidity_sweep(
        h1,
        direction
    )

    order_block = detect_order_block(
        h1,
        direction
    )

    breakout_retest = detect_breakout_retest(
        h1,
        direction
    )

    sr_reversal = sr_reversal_signal(
        h1,
        direction
    )

    # --------------------------------------------------------
    # STRATEGY MATCHES
    # --------------------------------------------------------

    strategies = []

    if daily_trend == "BULLISH":
        strategies.append("DAILY_BULLISH")

    if daily_trend == "BEARISH":
        strategies.append("DAILY_BEARISH")

    if h4_trend == "BULLISH":
        strategies.append("4H_BULLISH")

    if h4_trend == "BEARISH":
        strategies.append("4H_BEARISH")

    if h1_trend == "BULLISH":
        strategies.append("1H_BULLISH")

    if h1_trend == "BEARISH":
        strategies.append("1H_BEARISH")

    if ema_trend_value == daily_trend:
        strategies.append("EMA_ALIGNMENT")

    if pullback:
        strategies.append("TREND_PULLBACK")

    if bos == direction:
        strategies.append("BOS")

    if liquidity_sweep:
        strategies.append("LIQUIDITY_SWEEP")

    if order_block:
        strategies.append("ORDER_BLOCK")

    if breakout_retest:
        strategies.append("BREAKOUT_RETEST")

    if sr_reversal:
        strategies.append("SR_REVERSAL")

    # --------------------------------------------------------
    # MAIN SETUP
    # --------------------------------------------------------

    main_setup = (
        pullback
        or bos == direction
        or liquidity_sweep
        or order_block
        or breakout_retest
        or sr_reversal
    )

    if not main_setup:

        return {
            **no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "NO_MAIN_SETUP"
            ),
            "ema": ema,
            "strategies": strategies,
            "strategy_matches": strategies,
        }

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = calculate_signal_score(
        daily_trend,
        h4_trend,
        h1_trend,
        ema_trend_value,
        main_setup,
        bos == direction,
        confirmation
    )

    quality = quality_filter(score)

    # --------------------------------------------------------
    # QUALITY FILTER
    # --------------------------------------------------------

    if quality != "HIGH":

        return {
            **no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "SIGNAL_QUALITY_TOO_LOW"
            ),
            "score": score,
            "quality": quality,
            "ema": ema,
            "strategies": strategies,
            "strategy_matches": strategies,

            "bos": bos,
            "pullback": pullback,
            "confirmation": confirmation,
            "liquidity_sweep": liquidity_sweep,
            "order_block": order_block,
            "breakout_retest": breakout_retest,
            "sr_reversal": sr_reversal,
        }

    # --------------------------------------------------------
    # CONFIRMATION FILTER
    # --------------------------------------------------------

    if not confirmation:

        return {
            **no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "NO_CONFIRMATION_CANDLE"
            ),
            "score": score,
            "quality": quality,
            "ema": ema,
            "strategies": strategies,
            "strategy_matches": strategies,

            "bos": bos,
            "pullback": pullback,
            "confirmation": confirmation,
            "liquidity_sweep": liquidity_sweep,
            "order_block": order_block,
            "breakout_retest": breakout_retest,
            "sr_reversal": sr_reversal,
        }

    # --------------------------------------------------------
    # TRADE LEVELS
    # --------------------------------------------------------

    levels = calculate_trade_levels(
        h1,
        direction
    )

    if levels is None:

        return {
            **no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "INVALID_TRADE_LEVELS"
            ),
            "score": score,
            "quality": quality,
            "ema": ema,
            "strategies": strategies,
            "strategy_matches": strategies,

            "bos": bos,
            "pullback": pullback,
            "confirmation": confirmation,
            "liquidity_sweep": liquidity_sweep,
            "order_block": order_block,
            "breakout_retest": breakout_retest,
            "sr_reversal": sr_reversal,
        }

    # --------------------------------------------------------
    # FINAL SIGNAL
    # --------------------------------------------------------

    return {

        "signal": direction,

        "direction": direction,

        "quality": quality,

        "score": score,

        "reason": "HIGH_QUALITY_SETUP",

        "daily": daily_trend,

        "4h": h4_trend,

        "1h": h1_trend,

        "entry": levels["entry"],

        "sl": levels["sl"],

        "tp1": levels["tp1"],

        "tp2": levels["tp2"],

        "tp3": levels["tp3"],

        "risk": levels["risk"],

        "rr": levels["rr"],

        "strategies": strategies,

        "strategy_matches": strategies,

        "bos": bos,

        "pullback": pullback,

        "confirmation": confirmation,

        "liquidity_sweep": liquidity_sweep,

        "order_block": order_block,

        "breakout_retest": breakout_retest,

        "sr_reversal": sr_reversal,

        "ema": ema,
    }
