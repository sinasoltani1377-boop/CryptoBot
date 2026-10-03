import json
import os
import threading
from datetime import datetime, timezone, timedelta


# ============================================================
# CryptoBot Tracker
#
# Purpose:
# - Track HIGH signals
# - Track TP1 / TP2 / TP3 / SL
# - Daily statistics
# - 7-day test statistics
# - Strategy performance
# - Symbol performance
#
# Target for test:
# ~7 signals/day
# TP3 performance will be measured, NOT guaranteed.
# ============================================================


TRADES_FILE = os.getenv(
    "TRADES_FILE",
    "/tmp/cryptobot_trades.json"
)

_lock = threading.Lock()


# ============================================================
# FILE FUNCTIONS
# ============================================================

def _load_trades():
    with _lock:
        if not os.path.exists(TRADES_FILE):
            return []

        try:
            with open(TRADES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                return data

        except Exception:
            pass

        return []


def _save_trades(trades):
    with _lock:
        temp_file = TRADES_FILE + ".tmp"

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(
                trades,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(temp_file, TRADES_FILE)


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    """
    Convert ISO timestamp to timezone-aware datetime.
    """

    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


# ============================================================
# REGISTER SIGNAL
# ============================================================

def register_signal(symbol, signal):
    """
    Register a new HIGH signal.
    """

    if not isinstance(signal, dict):
        return None

    # --------------------------------------------------------
    # HIGH ONLY
    # --------------------------------------------------------

    if signal.get("quality") != "HIGH":
        return None

    direction = signal.get("direction")

    if direction not in ("LONG", "SHORT"):
        return None

    entry = signal.get("entry")
    sl = signal.get("sl")
    tp1 = signal.get("tp1")
    tp2 = signal.get("tp2")
    tp3 = signal.get("tp3")

    if None in (entry, sl, tp1, tp2, tp3):
        return None

    try:
        entry = float(entry)
        sl = float(sl)
        tp1 = float(tp1)
        tp2 = float(tp2)
        tp3 = float(tp3)
    except (TypeError, ValueError):
        return None

    trades = _load_trades()

    created_at = utc_now()

    trade_id = (
        f"{symbol}_"
        f"{direction}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    )

    # --------------------------------------------------------
    # STRATEGIES
    # --------------------------------------------------------

    strategy = signal.get("strategy")

    strategies = signal.get("strategies", [])

    if isinstance(strategies, str):
        strategies = [strategies]

    if not isinstance(strategies, list):
        strategies = []

    strategies = [
        str(x)
        for x in strategies
        if x
    ]

    # If no list exists, use primary strategy.
    if not strategies and strategy:
        strategies = [str(strategy)]

    # --------------------------------------------------------
    # TRADE
    # --------------------------------------------------------

    trade = {
        "id": trade_id,

        "symbol": symbol,
        "direction": direction,

        "quality": signal.get("quality"),
        "score": signal.get("score"),

        # Primary strategy
        "strategy": strategy,

        # All matching strategies
        "strategies": strategies,

        # Strategy details if supplied
        "strategy_details": signal.get(
            "strategy_details",
            {}
        ),

        "entry": entry,
        "sl": sl,

        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,

        "risk": signal.get("risk"),
        "rr": signal.get("rr"),

        # ----------------------------------------------------
        # MARKET CONTEXT
        # ----------------------------------------------------

        "daily": signal.get("daily"),
        "4h": signal.get("4h"),
        "1h": signal.get("1h"),

        "daily_ema": signal.get("daily_ema"),
        "4h_ema": signal.get("4h_ema"),
        "1h_ema": signal.get("1h_ema"),

        "rsi_15m": signal.get("rsi_15m"),
        "adx_1h": signal.get("adx_1h"),
        "adx_15m": signal.get("adx_15m"),

        "mtf_confirmed": signal.get(
            "mtf_confirmed"
        ),

        "volume_spike": signal.get(
            "volume_spike"
        ),

        "confirmation": signal.get(
            "confirmation"
        ),

        "reason": signal.get(
            "reason"
        ),

        # ----------------------------------------------------
        # TIME
        # ----------------------------------------------------

        "created_at": created_at,

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        "status": "OPEN",

        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "sl_hit": False,

        "tp1_time": None,
        "tp2_time": None,
        "tp3_time": None,
        "sl_time": None,

        "result": None,
        "closed_at": None,

        # Last checked price
        "last_price": entry,
        "last_update": created_at,
    }

    trades.append(trade)

    _save_trades(trades)

    return trade


# ============================================================
# UPDATE ONE TRADE
# ============================================================

def update_trade(trade, price):
    """
    Update one OPEN trade using current market price.

    Returns:
        (changed, event)
    """

    if trade.get("status") != "OPEN":
        return False, None

    try:
        price = float(price)
    except (TypeError, ValueError):
        return False, None

    direction = trade.get("direction")

    try:
        entry = float(trade["entry"])
        sl = float(trade["sl"])
        tp1 = float(trade["tp1"])
        tp2 = float(trade["tp2"])
        tp3 = float(trade["tp3"])
    except (KeyError, TypeError, ValueError):
        return False, None

    now = utc_now()

    trade["last_price"] = price
    trade["last_update"] = now

    # ========================================================
    # LONG
    # ========================================================

    if direction == "LONG":

        # SL priority
        if price <= sl:

            trade["sl_hit"] = True
            trade["sl_time"] = now

            trade["status"] = "CLOSED"
            trade["result"] = "SL"
            trade["closed_at"] = now

            return True, "SL"

        # TP1
        if (
            not trade.get("tp1_hit", False)
            and price >= tp1
        ):

            trade["tp1_hit"] = True
            trade["tp1_time"] = now

            return True, "TP1"

        # TP2
        if (
            not trade.get("tp2_hit", False)
            and price >= tp2
        ):

            trade["tp2_hit"] = True
            trade["tp2_time"] = now

            return True, "TP2"

        # TP3
        if (
            not trade.get("tp3_hit", False)
            and price >= tp3
        ):

            trade["tp3_hit"] = True
            trade["tp3_time"] = now

            trade["status"] = "CLOSED"
            trade["result"] = "TP3"
            trade["closed_at"] = now

            return True, "TP3"

    # ========================================================
    # SHORT
    # ========================================================

    elif direction == "SHORT":

        # SL priority
        if price >= sl:

            trade["sl_hit"] = True
            trade["sl_time"] = now

            trade["status"] = "CLOSED"
            trade["result"] = "SL"
            trade["closed_at"] = now

            return True, "SL"

        # TP1
        if (
            not trade.get("tp1_hit", False)
            and price <= tp1
        ):

            trade["tp1_hit"] = True
            trade["tp1_time"] = now

            return True, "TP1"

        # TP2
        if (
            not trade.get("tp2_hit", False)
            and price <= tp2
        ):

            trade["tp2_hit"] = True
            trade["tp2_time"] = now

            return True, "TP2"

        # TP3
        if (
            not trade.get("tp3_hit", False)
            and price <= tp3
        ):

            trade["tp3_hit"] = True
            trade["tp3_time"] = now

            trade["status"] = "CLOSED"
            trade["result"] = "TP3"
            trade["closed_at"] = now

            return True, "TP3"

    return False, None


# ============================================================
# CHECK ALL OPEN TRADES
# ============================================================

def check_all_trades(price_getter):
    """
    Check every open trade.

    price_getter(symbol) must return current price.
    """

    trades = _load_trades()

    events = []

    changed_any = False

    for trade in trades:

        if trade.get("status") != "OPEN":
            continue

        symbol = trade.get("symbol")

        if not symbol:
            continue

        try:
            price = price_getter(symbol)
        except Exception:
            continue

        if price is None:
            continue

        changed, event = update_trade(
            trade,
            price
        )

        if changed:
            changed_any = True

            events.append({
                "trade": trade.copy(),
                "event": event,
                "price": float(price),
            })

    # Save even if only last_price changed
    # so tracker knows latest checked price.
    if trades:
        _save_trades(trades)

    return events


# ============================================================
# OPEN TRADES
# ============================================================

def get_open_trades():
    trades = _load_trades()

    return [
        trade
        for trade in trades
        if trade.get("status") == "OPEN"
    ]


# ============================================================
# BASIC STATS
# ============================================================

def get_stats():
    trades = _load_trades()

    total = len(trades)

    open_count = 0

    sl_count = 0
    tp1_count = 0
    tp2_count = 0
    tp3_count = 0

    strategy_stats = {}
    symbol_stats = {}

    for trade in trades:

        if trade.get("status") == "OPEN":
            open_count += 1

        if trade.get("sl_hit"):
            sl_count += 1

        if trade.get("tp1_hit"):
            tp1_count += 1

        if trade.get("tp2_hit"):
            tp2_count += 1

        if trade.get("tp3_hit"):
            tp3_count += 1

        # ====================================================
        # STRATEGY STATISTICS
        #
        # Use PRIMARY strategy here.
        # This prevents one signal with multiple strategies
        # from being counted several times.
        # ====================================================

        strategy = trade.get("strategy")

        if not strategy:
            strategies = trade.get("strategies", [])

            if isinstance(strategies, list) and strategies:
                strategy = strategies[0]

        if not strategy:
            strategy = "UNKNOWN"

        if strategy not in strategy_stats:

            strategy_stats[strategy] = {
                "signals": 0,
                "sl": 0,
                "tp1": 0,
                "tp2": 0,
                "tp3": 0,
                "open": 0,
            }

        strategy_stats[strategy]["signals"] += 1

        if trade.get("sl_hit"):
            strategy_stats[strategy]["sl"] += 1

        if trade.get("tp1_hit"):
            strategy_stats[strategy]["tp1"] += 1

        if trade.get("tp2_hit"):
            strategy_stats[strategy]["tp2"] += 1

        if trade.get("tp3_hit"):
            strategy_stats[strategy]["tp3"] += 1

        if trade.get("status") == "OPEN":
            strategy_stats[strategy]["open"] += 1

        # ====================================================
        # SYMBOL STATISTICS
        # ====================================================

        symbol = trade.get(
            "symbol",
            "UNKNOWN"
        )

        if symbol not in symbol_stats:

            symbol_stats[symbol] = {
                "signals": 0,
                "sl": 0,
                "tp1": 0,
                "tp2": 0,
                "tp3": 0,
                "open": 0,
            }

        symbol_stats[symbol]["signals"] += 1

        if trade.get("sl_hit"):
            symbol_stats[symbol]["sl"] += 1

        if trade.get("tp1_hit"):
            symbol_stats[symbol]["tp1"] += 1

        if trade.get("tp2_hit"):
            symbol_stats[symbol]["tp2"] += 1

        if trade.get("tp3_hit"):
            symbol_stats[symbol]["tp3"] += 1

        if trade.get("status") == "OPEN":
            symbol_stats[symbol]["open"] += 1

    closed = total - open_count

    tp3_rate = (
        (tp3_count / total) * 100
        if total > 0
        else 0
    )

    return {
        "total": total,
        "open": open_count,
        "closed": closed,

        "sl": sl_count,
        "tp1": tp1_count,
        "tp2": tp2_count,
        "tp3": tp3_count,

        "tp3_rate": round(tp3_rate, 2),

        "strategies": strategy_stats,
        "symbols": symbol_stats,
    }


# ============================================================
# DAILY STATISTICS
# ============================================================

def get_daily_stats(days=7):
    """
    Return statistics for each UTC day.

    Example:
        {
            "2026-10-01": {...},
            "2026-10-02": {...}
        }
    """

    trades = _load_trades()

    now = datetime.now(timezone.utc)

    start_date = (
        now.date()
        - timedelta(days=days - 1)
    )

    daily = {}

    # Create all days even if there were zero signals.
    for i in range(days):

        day = start_date + timedelta(days=i)

        daily[str(day)] = {
            "signals": 0,
            "open": 0,
            "sl": 0,
            "tp1": 0,
            "tp2": 0,
            "tp3": 0,
            "tp3_rate": 0.0,
        }

    for trade in trades:

        created = parse_time(
            trade.get("created_at")
        )

        if created is None:
            continue

        day = str(created.date())

        if day not in daily:
            continue

        stats = daily[day]

        stats["signals"] += 1

        if trade.get("status") == "OPEN":
            stats["open"] += 1

        if trade.get("sl_hit"):
            stats["sl"] += 1

        if trade.get("tp1_hit"):
            stats["tp1"] += 1

        if trade.get("tp2_hit"):
            stats["tp2"] += 1

        if trade.get("tp3_hit"):
            stats["tp3"] += 1

    for day, stats in daily.items():

        if stats["signals"] > 0:

            stats["tp3_rate"] = round(
                (
                    stats["tp3"]
                    / stats["signals"]
                ) * 100,
                2
            )

    return daily


# ============================================================
# 7 DAY TEST
# ============================================================

def get_7day_report():
    """
    Generate the complete 7-day test statistics.

    Target:
        approximately 7 signals/day

    This is only a measurement target.
    It does NOT force the bot to create signals.
    """

    trades = _load_trades()

    now = datetime.now(timezone.utc)

    start = now - timedelta(days=7)

    period_trades = []

    for trade in trades:

        created = parse_time(
            trade.get("created_at")
        )

        if created is None:
            continue

        if start <= created <= now:
            period_trades.append(trade)

    total = len(period_trades)

    open_count = 0

    sl_count = 0
    tp1_count = 0
    tp2_count = 0
    tp3_count = 0

    # --------------------------------------------------------
    # Strategy performance
    # PRIMARY strategy only
    # --------------------------------------------------------

    strategy_stats = {}

    # --------------------------------------------------------
    # Symbol performance
    # --------------------------------------------------------

    symbol_stats = {}

    for trade in period_trades:

        if trade.get("status") == "OPEN":
            open_count += 1

        if trade.get("sl_hit"):
            sl_count += 1

        if trade.get("tp1_hit"):
            tp1_count += 1

        if trade.get("tp2_hit"):
            tp2_count += 1

        if trade.get("tp3_hit"):
            tp3_count += 1

        # ====================================================
        # PRIMARY STRATEGY
        # ====================================================

        strategy = trade.get("strategy")

        if not strategy:

            strategies = trade.get(
                "strategies",
                []
            )

            if isinstance(strategies, list) and strategies:
                strategy = strategies[0]

        if not strategy:
            strategy = "UNKNOWN"

        if strategy not in strategy_stats:

            strategy_stats[strategy] = {
                "signals": 0,
                "sl": 0,
                "tp1": 0,
                "tp2": 0,
                "tp3": 0,
                "tp3_rate": 0.0,
                "open": 0,
            }

        s = strategy_stats[strategy]

        s["signals"] += 1

        if trade.get("sl_hit"):
            s["sl"] += 1

        if trade.get("tp1_hit"):
            s["tp1"] += 1

        if trade.get("tp2_hit"):
            s["tp2"] += 1

        if trade.get("tp3_hit"):
            s["tp3"] += 1

        if trade.get("status") == "OPEN":
            s["open"] += 1

        # ====================================================
        # SYMBOL
        # ====================================================

        symbol = trade.get(
            "symbol",
            "UNKNOWN"
        )

        if symbol not in symbol_stats:

            symbol_stats[symbol] = {
                "signals": 0,
                "sl": 0,
                "tp1": 0,
                "tp2": 0,
                "tp3": 0,
                "tp3_rate": 0.0,
                "open": 0,
            }

        ss = symbol_stats[symbol]

        ss["signals"] += 1

        if trade.get("sl_hit"):
            ss["sl"] += 1

        if trade.get("tp1_hit"):
            ss["tp1"] += 1

        if trade.get("tp2_hit"):
            ss["tp2"] += 1

        if trade.get("tp3_hit"):
            ss["tp3"] += 1

        if trade.get("status") == "OPEN":
            ss["open"] += 1

    # ========================================================
    # RATES
    # ========================================================

    tp3_rate = (
        (tp3_count / total) * 100
        if total > 0
        else 0
    )

    sl_rate = (
        (sl_count / total) * 100
        if total > 0
        else 0
    )

    average_daily_signals = (
        total / 7
    )

    # --------------------------------------------------------
    # Strategy TP3 rates
    # --------------------------------------------------------

    for stats in strategy_stats.values():

        signals = stats["signals"]

        if signals > 0:

            stats["tp3_rate"] = round(
                (
                    stats["tp3"]
                    / signals
                ) * 100,
                2
            )

    # --------------------------------------------------------
    # Symbol TP3 rates
    # --------------------------------------------------------

    for stats in symbol_stats.values():

        signals = stats["signals"]

        if signals > 0:

            stats["tp3_rate"] = round(
                (
                    stats["tp3"]
                    / signals
                ) * 100,
                2
            )

    return {
        "period_days": 7,

        "start": start.isoformat(),
        "end": now.isoformat(),

        "total": total,
        "open": open_count,

        "sl": sl_count,
        "tp1": tp1_count,
        "tp2": tp2_count,
        "tp3": tp3_count,

        "tp3_rate": round(
            tp3_rate,
            2
        ),

        "sl_rate": round(
            sl_rate,
            2
        ),

        "average_daily_signals": round(
            average_daily_signals,
            2
        ),

        "target_daily_signals": 7,

        "strategy_target": {
            "trend_following": True,
            "pullback": True,
            "breakout": True,
            "reversal": True,
            "range_trading": True,
        },

        "strategies": strategy_stats,

        "symbols": symbol_stats,
    }


# ============================================================
# DAILY REPORT TEXT
# ============================================================

def format_daily_report(day=None):
    """
    Create human-readable daily report.

    If day is None, use today's UTC date.
    """

    daily = get_daily_stats(7)

    if day is None:
        day = str(
            datetime.now(
                timezone.utc
            ).date()
        )

    stats = daily.get(day)

    if not stats:
        return (
            "📊 DAILY REPORT\n\n"
            f"Date: {day}\n"
            "No data."
        )

    return (
        "📊 DAILY TEST REPORT\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Date: {day}\n\n"

        f"📡 Signals: {stats['signals']}\n"
        f"🎯 Target: ~7/day\n"
        f"⏳ Open: {stats['open']}\n\n"

        f"🎯 TP1: {stats['tp1']}\n"
        f"🎯 TP2: {stats['tp2']}\n"
        f"🎯 TP3: {stats['tp3']}\n"
        f"🛑 SL: {stats['sl']}\n\n"

        f"📈 TP3 Rate: "
        f"{stats['tp3_rate']}%\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )


# ============================================================
# 7 DAY REPORT TEXT
# ============================================================

def format_7day_report():
    """
    Create human-readable 7-day report.
    """

    report = get_7day_report()

    lines = [
        "📊 7 DAY TEST REPORT",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📡 Total Signals: {report['total']}",
        f"📊 Average/Day: "
        f"{report['average_daily_signals']}",
        f"🎯 Target: ~7/day",
        "",
        f"🎯 TP1: {report['tp1']}",
        f"🎯 TP2: {report['tp2']}",
        f"🎯 TP3: {report['tp3']}",
        f"🛑 SL: {report['sl']}",
        "",
        f"📈 TP3 Rate: "
        f"{report['tp3_rate']}%",
        f"🛑 SL Rate: "
        f"{report['sl_rate']}%",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "📚 STRATEGY PERFORMANCE",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    # Fixed order: exactly five strategies
    strategy_order = [
        "Trend Following",
        "Pullback",
        "Breakout",
        "Reversal",
        "Range Trading",
    ]

    for strategy in strategy_order:

        stats = report["strategies"].get(
            strategy
        )

        if not stats:
            lines.append(
                f"\n{strategy}\n"
                "Signals: 0"
            )
            continue

        lines.append(
            f"\n{strategy}\n"
            f"Signals: {stats['signals']}\n"
            f"TP3: {stats['tp3']}\n"
            f"SL: {stats['sl']}\n"
            f"TP3 Rate: {stats['tp3_rate']}%"
        )

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "📅 DAILY BREAKDOWN",
        "━━━━━━━━━━━━━━━━━━━━",
    ])

    daily = get_daily_stats(7)

    for day, stats in daily.items():

        lines.append(
            f"{day} | "
            f"Signals={stats['signals']} | "
            f"TP3={stats['tp3']} | "
            f"SL={stats['sl']} | "
            f"TP3 Rate={stats['tp3_rate']}%"
        )

    lines.append(
        "━━━━━━━━━━━━━━━━━━━━"
    )

    return "\n".join(lines)
