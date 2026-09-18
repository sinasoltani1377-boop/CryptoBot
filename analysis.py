# ============================================================
# CryptoBot - Professional Analysis Engine v6
# 7 Strategy Engine
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

    if isinstance(candle, dict):

        o = safe_float(
            candle.get("open", candle.get("o"))
        )

        h = safe_float(
            candle.get("high", candle.get("h"))
        )

        l = safe_float(
            candle.get("low", candle.get("l"))
        )

        c = safe_float(
            candle.get("close", candle.get("c"))
        )

        v = safe_float(
            candle.get("volume", candle.get("v"))
        )

        t = candle.get(
            "timestamp",
            candle.get("time", candle.get("t"))
        )

        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            return None

        if h < l:
            return None

        return {
            "timestamp": t,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
        }

    if isinstance(candle, (list, tuple)):

        if len(candle) < 5:
            return None

        o = safe_float(candle[1])
        h = safe_float(candle[2])
        l = safe_float(candle[3])
        c = safe_float(candle[4])

        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            return None

        if h < l:
            return None

        v = 0.0

        if len(candle) > 5:
            v = safe_float(candle[5])

        return {
            "timestamp": candle[0],
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
        }

    return None


def clean_candles(candles):

    if not isinstance(candles, (list, tuple)):
        return []

    result = []

    for candle in candles:

        normalized = normalize_candle(candle)

        if normalized is not None:
            result.append(normalized)

    return result


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

    price = candles[-1]["close"]

    if None in (ema20, ema50, ema200):
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
# RSI
# ============================================================

def calculate_rsi(candles, period=14):

    candles = clean_candles(candles)

    closes = get_closes(candles)

    if len(closes) <= period:
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

    if len(gains) < period:
        return None

    avg_gain = sum(
        gains[:period]
    ) / period

    avg_loss = sum(
        losses[:period]
    ) / period

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# SWINGS
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

        current_high = candles[i]["high"]
        current_low = candles[i]["low"]

        left_highs = [
            candles[j]["high"]
            for j in range(
                i - strength,
                i
            )
        ]

        right_highs = [
            candles[j]["high"]
            for j in range(
                i + 1,
                i + strength + 1
            )
        ]

        left_lows = [
            candles[j]["low"]
            for j in range(
                i - strength,
                i
            )
        ]

        right_lows = [
            candles[j]["low"]
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
                "price": current_high
            })

        if current_low < min(
            left_lows + right_lows
        ):
            swing_lows.append({
                "index": i,
                "price": current_low
            })

    return swing_highs, swing_lows


# ============================================================
# MARKET STRUCTURE
# ============================================================

def get_structure_direction(candles):

    candles = clean_candles(candles)

    highs, lows = find_swings(candles)

    if len(highs) < 2 or len(lows) < 2:
        return "RANGE"

    last_high = highs[-1]["price"]
    prev_high = highs[-2]["price"]

    last_low = lows[-1]["price"]
    prev_low = lows[-2]["price"]

    if (
        last_high > prev_high
        and last_low > prev_low
    ):
        return "BULLISH"

    if (
        last_high < prev_high
        and last_low < prev_low
    ):
        return "BEARISH"

    return "RANGE"


def structure_details(candles):

    candles = clean_candles(candles)

    highs, lows = find_swings(candles)

    return {
        "direction": get_structure_direction(candles),
        "swing_highs": highs[-5:],
        "swing_lows": lows[-5:],
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

    if d == "BULLISH" and h4_trend == "BULLISH":
        return "BULLISH"

    if d == "BEARISH" and h4_trend == "BEARISH":
        return "BEARISH"

    if d == "BULLISH" and h4_trend == "RANGE":
        return "BULLISH_WEAK"

    if d == "BEARISH" and h4_trend == "RANGE":
        return "BEARISH_WEAK"

    return "NO_ALIGNMENT"


# ============================================================
# STRATEGY 1
# TREND FOLLOWING
# ============================================================

def trend_following_signal(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 200:
        return False

    structure = get_structure_direction(candles)
    ema = ema_trend(candles)

    if direction == "LONG":

        return (
            structure == "BULLISH"
            and ema == "BULLISH"
        )

    if direction == "SHORT":

        return (
            structure == "BEARISH"
            and ema == "BEARISH"
        )

    return False


# ============================================================
# STRATEGY 2
# SUPPORT / RESISTANCE + BREAKOUT / PULLBACK
# ============================================================

def find_support_resistance(candles):

    candles = clean_candles(candles)

    highs, lows = find_swings(candles)

    support = None
    resistance = None

    if lows:
        support = lows[-1]["price"]

    if highs:
        resistance = highs[-1]["price"]

    return {
        "support": support,
        "resistance": resistance
    }


def detect_pullback(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 8:
        return False

    recent = candles[-6:]

    highest = max(get_highs(recent))
    lowest = min(get_lows(recent))

    close = candles[-1]["close"]

    total_range = highest - lowest

    if total_range <= 0:
        return False

    position = (
        (close - lowest)
        / total_range
    )

    if direction == "LONG":
        return position < 0.70

    if direction == "SHORT":
        return position > 0.30

    return False


def detect_breakout_retest(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 15:
        return False

    base = candles[:-3]

    sr = find_support_resistance(base)

    support = sr["support"]
    resistance = sr["resistance"]

    if support is None and resistance is None:
        return False

    c1 = candles[-3]
    c2 = candles[-2]
    c3 = candles[-1]

    if direction == "LONG":

        if resistance is None:
            return False

        breakout = (
            c2["close"] > resistance
        )

        retest = (
            c3["low"] <= resistance
            and c3["close"] > resistance
        )

        return breakout and retest

    if direction == "SHORT":

        if support is None:
            return False

        breakout = (
            c2["close"] < support
        )

        retest = (
            c3["high"] >= support
            and c3["close"] < support
        )

        return breakout and retest

    return False


def sr_breakout_pullback_signal(
    candles,
    direction
):

    return (
        detect_breakout_retest(
            candles,
            direction
        )
        or detect_pullback(
            candles,
            direction
        )
    )


# ============================================================
# STRATEGY 3
# PRICE ACTION
# ============================================================

def price_action_signal(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 3:
        return False

    current = candles[-1]
    previous = candles[-2]

    o = current["open"]
    h = current["high"]
    l = current["low"]
    c = current["close"]

    body = abs(c - o)

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if body <= 0:
        body = 0.00000001

    # Bullish engulfing
    bullish_engulfing = (
        direction == "LONG"
        and previous["close"] < previous["open"]
        and c > o
        and c >= previous["open"]
        and o <= previous["close"]
    )

    # Bearish engulfing
    bearish_engulfing = (
        direction == "SHORT"
        and previous["close"] > previous["open"]
        and c < o
        and c <= previous["open"]
        and o >= previous["close"]
    )

    # Bullish rejection
    bullish_rejection = (
        direction == "LONG"
        and lower_wick >= body * 1.5
        and c > o
    )

    # Bearish rejection
    bearish_rejection = (
        direction == "SHORT"
        and upper_wick >= body * 1.5
        and c < o
    )

    # Strong directional candle
    strong_bullish = (
        direction == "LONG"
        and c > o
        and body >= (
            (h - l) * 0.60
        )
    )

    strong_bearish = (
        direction == "SHORT"
        and c < o
        and body >= (
            (h - l) * 0.60
        )
    )

    return (
        bullish_engulfing
        or bearish_engulfing
        or bullish_rejection
        or bearish_rejection
        or strong_bullish
        or strong_bearish
    )


# ============================================================
# STRATEGY 4
# LIQUIDITY SWEEP / SMC
# ============================================================

def detect_liquidity_sweep(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 12:
        return False

    highs, lows = find_swings(
        candles[:-1]
    )

    current = candles[-1]

    if direction == "LONG":

        if not lows:
            return False

        level = lows[-1]["price"]

        return (
            current["low"] < level
            and current["close"] > level
        )

    if direction == "SHORT":

        if not highs:
            return False

        level = highs[-1]["price"]

        return (
            current["high"] > level
            and current["close"] < level
        )

    return False


def detect_order_block(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 8:
        return False

    start = max(
        0,
        len(candles) - 5
    )

    for i in range(
        start,
        len(candles) - 1
    ):

        current = candles[i]
        following = candles[i + 1]

        current_body = abs(
            current["close"]
            - current["open"]
        )

        following_body = abs(
            following["close"]
            - following["open"]
        )

        if current_body <= 0:
            continue

        if direction == "LONG":

            bearish_candle = (
                current["close"]
                < current["open"]
            )

            strong_bullish = (
                following["close"]
                > following["open"]
                and following_body
                >= current_body * 1.3
            )

            if (
                bearish_candle
                and strong_bullish
            ):
                return True

        if direction == "SHORT":

            bullish_candle = (
                current["close"]
                > current["open"]
            )

            strong_bearish = (
                following["close"]
                < following["open"]
                and following_body
                >= current_body * 1.3
            )

            if (
                bullish_candle
                and strong_bearish
            ):
                return True

    return False


def smc_signal(
    candles,
    direction
):

    return (
        detect_liquidity_sweep(
            candles,
            direction
        )
        or detect_order_block(
            candles,
            direction
        )
    )


# ============================================================
# STRATEGY 5
# EMA TREND
# ============================================================

def ema_strategy_signal(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 200:
        return False

    ema20 = calculate_ema(candles, 20)
    ema50 = calculate_ema(candles, 50)
    ema200 = calculate_ema(candles, 200)

    close = candles[-1]["close"]

    if None in (
        ema20,
        ema50,
        ema200
    ):
        return False

    if direction == "LONG":

        return (
            close > ema200
            and ema20 > ema50
            and ema50 > ema200
        )

    if direction == "SHORT":

        return (
            close < ema200
            and ema20 < ema50
            and ema50 < ema200
        )

    return False


# ============================================================
# STRATEGY 6
# RANGE TRADING
# ============================================================

def detect_range(candles):

    candles = clean_candles(candles)

    if len(candles) < 20:
        return False

    recent = candles[-20:]

    highest = max(
        get_highs(recent)
    )

    lowest = min(
        get_lows(recent)
    )

    if lowest <= 0:
        return False

    percentage = (
        (highest - lowest)
        / lowest
    ) * 100

    return percentage <= 5.0


def range_strategy_signal(
    candles,
    direction
):

    if not detect_range(candles):
        return False

    candles = clean_candles(candles)

    recent = candles[-20:]

    highest = max(
        get_highs(recent)
    )

    lowest = min(
        get_lows(recent)
    )

    close = candles[-1]["close"]

    total_range = highest - lowest

    if total_range <= 0:
        return False

    position = (
        close - lowest
    ) / total_range

    if direction == "LONG":
        return position <= 0.35

    if direction == "SHORT":
        return position >= 0.65

    return False


# ============================================================
# STRATEGY 7
# MEAN REVERSION
# ============================================================

def mean_reversion_signal(
    candles,
    direction
):

    candles = clean_candles(candles)

    if len(candles) < 50:
        return False

    ema20 = calculate_ema(
        candles,
        20
    )

    ema50 = calculate_ema(
        candles,
        50
    )

    rsi = calculate_rsi(
        candles,
        14
    )

    if (
        ema20 is None
        or ema50 is None
        or rsi is None
    ):
        return False

    close = candles[-1]["close"]

    distance = (
        (close - ema20)
        / ema20
    ) * 100

    if direction == "LONG":

        return (
            rsi <= 35
            and distance <= -1.0
            and close < ema20
            and close >= ema50 * 0.97
        )

    if direction == "SHORT":

        return (
            rsi >= 65
            and distance >= 1.0
            and close > ema20
            and close <= ema50 * 1.03
        )

    return False


# ============================================================
# CONFIRMATION
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

    previous_body = abs(
        previous["close"]
        - previous["open"]
    )

    current_body = abs(
        current["close"]
        - current["open"]
    )

    if previous_body <= 0:
        return False

    if current_body < previous_body * 1.05:
        return False

    if direction == "LONG":

        return (
            current["close"]
            > current["open"]
            and current["close"]
            > previous["close"]
        )

    if direction == "SHORT":

        return (
            current["close"]
            < current["open"]
            and current["close"]
            < previous["close"]
        )

    return False


# ============================================================
# BOS
# ============================================================

def detect_bos(candles):

    candles = clean_candles(candles)

    if len(candles) < 10:
        return None

    highs, lows = find_swings(
        candles[:-1]
    )

    close = candles[-1]["close"]

    if highs:

        if close > highs[-1]["price"]:
            return "LONG"

    if lows:

        if close < lows[-1]["price"]:
            return "SHORT"

    return None


# ============================================================
# STRATEGY ENGINE
# ============================================================

def evaluate_strategies(
    daily,
    h4,
    h1,
    direction
):

    strategies = []

    details = {}

    # 1 Trend Following
    trend_following = (
        trend_following_signal(
            h1,
            direction
        )
    )

    details["Trend Following"] = trend_following

    if trend_following:
        strategies.append(
            "TREND_FOLLOWING"
        )

    # 2 S/R Breakout + Pullback
    sr_strategy = (
        sr_breakout_pullback_signal(
            h1,
            direction
        )
    )

    details[
        "Support Resistance Breakout Pullback"
    ] = sr_strategy

    if sr_strategy:
        strategies.append(
            "SUPPORT_RESISTANCE_BREAKOUT_PULLBACK"
        )

    # 3 Price Action
    price_action = (
        price_action_signal(
            h1,
            direction
        )
    )

    details["Price Action"] = price_action

    if price_action:
        strategies.append(
            "PRICE_ACTION"
        )

    # 4 Liquidity / SMC
    smc = smc_signal(
        h1,
        direction
    )

    details["Liquidity Sweep SMC"] = smc

    if smc:
        strategies.append(
            "LIQUIDITY_SWEEP_SMC"
        )

    # 5 EMA
    ema_strategy = (
        ema_strategy_signal(
            h1,
            direction
        )
    )

    details["EMA Trend"] = ema_strategy

    if ema_strategy:
        strategies.append(
            "EMA_TREND"
        )

    # 6 Range
    range_strategy = (
        range_strategy_signal(
            h1,
            direction
        )
    )

    details["Range Trading"] = range_strategy

    if range_strategy:
        strategies.append(
            "RANGE_TRADING"
        )

    # 7 Mean Reversion
    mean_reversion = (
        mean_reversion_signal(
            h1,
            direction
        )
    )

    details["Mean Reversion"] = mean_reversion

    if mean_reversion:
        strategies.append(
            "MEAN_REVERSION"
        )

    return strategies, details


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

    entry = candles[-1]["close"]

    recent = candles[-8:]

    highs = get_highs(recent)
    lows = get_lows(recent)

    if not highs or not lows:
        return None

    if direction == "LONG":

        sl = min(lows)

        risk = entry - sl

        if risk <= 0:
            return None

        tp1 = entry + risk
        tp2 = entry + risk * 2
        tp3 = entry + risk * 3

    elif direction == "SHORT":

        sl = max(highs)

        risk = sl - entry

        if risk <= 0:
            return None

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
# QUALITY
# ============================================================

def quality_filter(score):

    if score >= 8:
        return "HIGH"

    if score >= 6:
        return "MEDIUM"

    return "LOW"


# ============================================================
# NO TRADE
# ============================================================

def no_trade_result(
    daily="UNKNOWN",
    h4="UNKNOWN",
    h1="UNKNOWN",
    reason="NO_TRADE"
):

    return {
        "signal": "NO_TRADE",
        "direction": None,

        "quality": "LOW",
        "score": 0,

        "reason": reason,

        "daily": daily,
        "4h": h4,
        "1h": h1,

        "entry": None,
        "sl": None,

        "tp1": None,
        "tp2": None,
        "tp3": None,

        "risk": None,
        "rr": None,

        "strategies": [],
        "strategy_matches": [],

        "strategy_details": {},

        "bos": None,
        "confirmation": False,

        "ema": None,
        "rsi": None,
    }


# ============================================================
# MAIN GENERATE SIGNAL
# ============================================================

def generate_signal(
    daily,
    h4,
    h1
):

    # --------------------------------------------------------
    # CLEAN ALL DATA
    # --------------------------------------------------------

    daily = clean_candles(daily)
    h4 = clean_candles(h4)
    h1 = clean_candles(h1)

    # --------------------------------------------------------
    # VALIDATION
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
    # TIMEFRAME STRUCTURE
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
    # DAILY TREND REQUIRED
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
    # DIRECTION
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
    # EMA / RSI
    # --------------------------------------------------------

    ema = ema_details(h1)

    rsi = calculate_rsi(
        h1,
        14
    )

    # --------------------------------------------------------
    # 7 STRATEGIES
    # --------------------------------------------------------

    strategies, strategy_details = (
        evaluate_strategies(
            daily,
            h4,
            h1,
            direction
        )
    )

    # --------------------------------------------------------
    # BOS
    # --------------------------------------------------------

    bos = detect_bos(h1)

    # --------------------------------------------------------
    # CONFIRMATION
    # --------------------------------------------------------

    confirmation = confirmation_candle(
        h1,
        direction
    )

    # --------------------------------------------------------
    # STRATEGY SCORE
    # --------------------------------------------------------

    strategy_score = len(strategies)

    # Maximum strategy contribution = 3
    strategy_points = min(
        strategy_score,
        3
    )

    # --------------------------------------------------------
    # TIMEFRAME SCORE
    # --------------------------------------------------------

    score = 0

    if daily_trend == direction_to_trend(
        direction
    ):
        score += 2

    if h4_trend == daily_trend:
        score += 2

    if h1_trend == daily_trend:
        score += 1

    # --------------------------------------------------------
    # EMA SCORE
    # --------------------------------------------------------

    if ema["trend"] == daily_trend:
        score += 1

    # --------------------------------------------------------
    # STRATEGY SCORE
    # --------------------------------------------------------

    score += strategy_points

    # --------------------------------------------------------
    # BOS
    # --------------------------------------------------------

    if bos == direction:
        score += 1

    # --------------------------------------------------------
    # CONFIRMATION
    # --------------------------------------------------------

    if confirmation:
        score += 1

    score = min(
        score,
        10
    )

    quality = quality_filter(
        score
    )

    # --------------------------------------------------------
    # NO STRATEGY
    # --------------------------------------------------------

    if not strategies:

        return {
            **no_trade_result(
                daily_trend,
                h4_trend,
                h1_trend,
                "NO_STRATEGY_MATCH"
            ),

            "score": score,
            "quality": quality,

            "ema": ema,
            "rsi": rsi,

            "strategies": [],
            "strategy_matches": [],

            "strategy_details":
                strategy_details,

            "bos": bos,
            "confirmation": confirmation,
        }

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
            "rsi": rsi,

            "strategies": strategies,
            "strategy_matches": strategies,

            "strategy_details":
                strategy_details,

            "bos": bos,
            "confirmation": confirmation,
        }

    # --------------------------------------------------------
    # CONFIRMATION REQUIRED
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
            "rsi": rsi,

            "strategies": strategies,
            "strategy_matches": strategies,

            "strategy_details":
                strategy_details,

            "bos": bos,
            "confirmation": False,
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
            "rsi": rsi,

            "strategies": strategies,
            "strategy_matches": strategies,

            "strategy_details":
                strategy_details,

            "bos": bos,
            "confirmation": confirmation,
        }

    # --------------------------------------------------------
    # FINAL HIGH QUALITY SIGNAL
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

        "strategy_details":
            strategy_details,

        "bos": bos,

        "confirmation": confirmation,

        "ema": ema,

        "rsi": rsi,
    }


# ============================================================
# DIRECTION HELPER
# ============================================================

def direction_to_trend(direction):

    if direction == "LONG":
        return "BULLISH"

    if direction == "SHORT":
        return "BEARISH"

    return "RANGE"
