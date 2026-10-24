import os
import json
import logging
import threading

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# CONFIG
# ============================================================

TRADES_FILE = os.getenv(
    "TRADES_FILE",
    "/tmp/cryptobot_trades.json"
)

DEFAULT_MARGIN = 10.0
DEFAULT_LEVERAGE = 20.0

# Only HIGH signals with score 10, 11 or 12 are accepted.
MIN_SIGNAL_SCORE = 10
MAX_SIGNAL_SCORE = 12

LOCK = threading.RLock()

logger = logging.getLogger(__name__)


# ============================================================
# TIME HELPERS
# ============================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None

    try:
        result = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)

        return result.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


# ============================================================
# FILE STORAGE
# ============================================================

def _load_trades() -> List[Dict[str, Any]]:
    if not os.path.exists(TRADES_FILE):
        return []

    try:
        with open(TRADES_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            logger.error("Invalid tracker file format.")
            return []

        return [
            item for item in data
            if isinstance(item, dict)
        ]

    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Could not load trades: %s", exc)
        return []


def _save_trades(trades: List[Dict[str, Any]]) -> bool:
    try:
        directory = os.path.dirname(TRADES_FILE)

        if directory:
            os.makedirs(directory, exist_ok=True)

        temp_file = TRADES_FILE + ".tmp"

        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(
                trades,
                file,
                ensure_ascii=False,
                indent=2
            )

        os.replace(temp_file, TRADES_FILE)
        return True

    except (OSError, TypeError, ValueError) as exc:
        logger.error("Could not save trades: %s", exc)
        return False


def get_all_trades() -> List[Dict[str, Any]]:
    with LOCK:
        return _load_trades()


# ============================================================
# NUMBER HELPERS
# ============================================================

def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)

        if result != result:
            return None

        if result in (float("inf"), float("-inf")):
            return None

        return result

    except (TypeError, ValueError):
        return None


def _positive(value: Any) -> Optional[float]:
    result = _number(value)

    if result is None or result <= 0:
        return None

    return result


def _normalise_direction(value: Any) -> str:
    return str(value or "").strip().upper()


def _valid_levels(
    direction: str,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    tp3: float,
    breakeven_active: bool = False,
    tp2_hit: bool = False,
) -> bool:
    """
    Validate trade levels taking into account stop movement.

    States:
    - Initial:     sl < entry < tp1 < tp2 < tp3  (LONG)
    - After TP1:   sl == entry  (breakeven_active = True)
    - After TP2:   sl == tp1    (tp2_hit = True)
    """
    if min(entry, sl, tp1, tp2, tp3) <= 0:
        return False

    tol = entry * 0.0001

    if direction == "LONG":
        if not (entry < tp1 < tp2 < tp3):
            return False
        if tp2_hit and abs(sl - tp1) < tol:
            return True
        if breakeven_active and abs(sl - entry) < tol:
            return True
        return sl < entry

    if direction == "SHORT":
        if not (tp3 < tp2 < tp1 < entry):
            return False
        if tp2_hit and abs(sl - tp1) < tol:
            return True
        if breakeven_active and abs(sl - entry) < tol:
            return True
        return sl > entry

    return False


# ============================================================
# PNL CALCULATIONS
# ============================================================

def _price_return(
    direction: str,
    entry: float,
    exit_price: float,
) -> float:
    if entry <= 0:
        return 0.0

    if direction == "LONG":
        return (exit_price - entry) / entry

    return (entry - exit_price) / entry


def _pnl_for_fraction(
    trade: Dict[str, Any],
    exit_price: float,
    fraction: float,
) -> float:
    entry = _positive(trade.get("entry"))
    leverage = _positive(trade.get("leverage"))
    margin = _positive(trade.get("margin"))
    direction = _normalise_direction(trade.get("direction"))

    if not entry or not leverage or not margin:
        return 0.0

    if direction not in ("LONG", "SHORT"):
        return 0.0

    price_return = _price_return(
        direction,
        entry,
        exit_price
    )

    original_notional = margin * leverage

    return original_notional * fraction * price_return


def _record_realized_pnl(
    trade: Dict[str, Any],
    exit_price: float,
    fraction: float,
) -> float:
    pnl = _pnl_for_fraction(
        trade,
        exit_price,
        fraction
    )

    trade["realized_pnl"] = round(
        float(trade.get("realized_pnl", 0.0)) + pnl,
        8
    )

    trade["realized_fraction"] = round(
        min(
            1.0,
            float(trade.get("realized_fraction", 0.0))
            + fraction
        ),
        8
    )

    return pnl


def _roi_percent(trade: Dict[str, Any]) -> float:
    margin = _positive(trade.get("margin"))

    if not margin:
        return 0.0

    pnl = float(trade.get("realized_pnl", 0.0))

    return (pnl / margin) * 100.0


# ============================================================
# SIGNAL REGISTRATION
# ============================================================

def register_signal(
    signal: Dict[str, Any],
) -> bool:
    if not isinstance(signal, dict):
        return False

    quality = str(
        signal.get("quality", "")
    ).strip().upper()

    direction = _normalise_direction(
        signal.get("direction") or signal.get("signal")
    )

    score = _number(signal.get("score"))

    if quality != "HIGH":
        logger.info("Rejected signal: quality is not HIGH.")
        return False

    if score is None or not (
        MIN_SIGNAL_SCORE <= score <= MAX_SIGNAL_SCORE
    ):
        logger.info(
            "Rejected signal: score must be 10-12; received %s",
            score
        )
        return False

    if direction not in ("LONG", "SHORT"):
        logger.info("Rejected signal: invalid direction.")
        return False

    symbol = str(
        signal.get("symbol", "")
    ).strip().upper()

    if not symbol:
        logger.info("Rejected signal: missing symbol.")
        return False

    entry = _positive(signal.get("entry"))
    sl = _positive(signal.get("sl"))
    tp1 = _positive(signal.get("tp1"))
    tp2 = _positive(signal.get("tp2"))
    tp3 = _positive(signal.get("tp3"))

    if None in (entry, sl, tp1, tp2, tp3):
        logger.info(
            "Rejected signal: one or more trade levels are missing."
        )
        return False

    if not _valid_levels(
        direction,
        entry,
        sl,
        tp1,
        tp2,
        tp3,
    ):
        logger.info(
            "Rejected signal: invalid entry, SL or TP ordering."
        )
        return False

    margin = _positive(
        signal.get("margin")
    ) or DEFAULT_MARGIN

    leverage = _positive(
        signal.get("leverage")
    ) or DEFAULT_LEVERAGE

    with LOCK:
        trades = _load_trades()

        for existing in trades:
            if (
                str(existing.get("symbol", "")).upper() == symbol
                and _normalise_direction(
                    existing.get("direction")
                ) == direction
                and str(existing.get("status", "")).upper() == "OPEN"
            ):
                logger.info(
                    "Duplicate open trade rejected: %s %s",
                    symbol,
                    direction
                )
                return False

        trade = {
            "id": (
                f"{symbol}_{direction}_"
                f"{datetime.now(timezone.utc).timestamp()}"
            ),

            "symbol": symbol,
            "direction": direction,

            "quality": quality,
            "score": int(score),

            "strategy": str(
                signal.get("strategy")
                or signal.get("strategies")
                or "UNKNOWN"
            ),

            "entry": entry,
            "original_sl": sl,
            "sl": sl,

            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,

            "margin": margin,
            "leverage": leverage,

            "position_notional": margin * leverage,

            "status": "OPEN",

            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,

            "breakeven_active": False,
            "sl_hit": False,
            "breakeven_hit": False,
            "tp1_protected_hit": False,

            "tp1_pnl": 0.0,
            "tp2_pnl": 0.0,
            "tp3_pnl": 0.0,

            "realized_pnl": 0.0,
            "realized_fraction": 0.0,

            "last_price": entry,

            "created_at": utc_now(),
            "updated_at": utc_now(),
            "closed_at": None,

            "close_reason": None,
            "events": [],
        }

        trades.append(trade)

        if not _save_trades(trades):
            return False

    logger.info(
        "TRACKER REGISTERED | %s | %s | Score=%s",
        symbol,
        direction,
        score
    )

    return True


# ============================================================
# TRADE EVENT HELPERS
# ============================================================

def _add_event(
    trade: Dict[str, Any],
    event: str,
    price: float,
    pnl: float = 0.0,
) -> None:
    events = trade.get("events")

    if not isinstance(events, list):
        events = []

    events.append({
        "event": event,
        "price": price,
        "pnl": round(pnl, 8),
        "time": utc_now(),
    })

    trade["events"] = events


def _close_trade(
    trade: Dict[str, Any],
    reason: str,
    price: float,
) -> None:
    trade["status"] = "CLOSED"
    trade["close_reason"] = reason
    trade["closed_at"] = utc_now()
    trade["updated_at"] = utc_now()
    trade["last_price"] = price


# ============================================================
# UPDATE ONE TRADE (TRAILING STOP LOGIC)
# ============================================================

def update_trade(
    trade: Dict[str, Any],
    price: float,
) -> Tuple[bool, Optional[str]]:
    """
    Update one trade using the latest available price.

    Trailing Stop Logic:
      - After TP1: SL moves to Entry (Breakeven)
      - After TP2: SL moves to TP1 (Profit Locked)
      - After TP3: Close remaining position

    Stop-Loss categorization:
      - Before any TP hit: SL (Real Loss)
      - After TP1 hit only: BREAKEVEN (No Loss)
      - After TP2 hit: TP1_PROTECTED (TP1 Profit Locked)
    """
    if not isinstance(trade, dict):
        return False, None

    current_price = _positive(price)

    if not current_price:
        return False, None

    if str(trade.get("status", "")).upper() != "OPEN":
        return False, None

    direction = _normalise_direction(trade.get("direction"))

    entry = _positive(trade.get("entry"))
    sl = _positive(trade.get("sl"))
    tp1 = _positive(trade.get("tp1"))
    tp2 = _positive(trade.get("tp2"))
    tp3 = _positive(trade.get("tp3"))

    if None in (entry, sl, tp1, tp2, tp3):
        logger.error(
            "Invalid trade levels for %s",
            trade.get("symbol")
        )
        return False, None

    breakeven_active = bool(trade.get("breakeven_active", False))
    tp2_hit_flag = bool(trade.get("tp2_hit", False))

    if not _valid_levels(
        direction,
        entry,
        sl,
        tp1,
        tp2,
        tp3,
        breakeven_active=breakeven_active,
        tp2_hit=tp2_hit_flag,
    ):
        logger.error(
            "Invalid trade level ordering for %s",
            trade.get("symbol")
        )
        return False, None

    trade["last_price"] = current_price
    trade["updated_at"] = utc_now()

    # --------------------------------------------------------
    # STOP LOSS / BREAK-EVEN CHECK
    # --------------------------------------------------------

    if direction == "LONG":
        stop_touched = current_price <= sl
    else:
        stop_touched = current_price >= sl

    if stop_touched:
        tp1_hit_flag = bool(trade.get("tp1_hit", False))
        
        # Fraction of the position that is still open
        remaining_fraction = max(
            0.0, 
            1.0 - float(trade.get("realized_fraction", 0.0))
        )

        # Execute at SL price
        exit_price = sl
        pnl = _record_realized_pnl(trade, exit_price, remaining_fraction) if remaining_fraction > 0 else 0.0

        # Categorize the exit
        if tp2_hit_flag:
            # After TP2: SL was at TP1 → profit locked
            trade["tp1_protected_hit"] = True
            _add_event(trade, "TP1_PROTECTED", exit_price, pnl)
            _close_trade(trade, "TP1_PROTECTED", exit_price)
            return True, "TP1_PROTECTED"

        if tp1_hit_flag:
            # After TP1: SL was at Entry → breakeven
            trade["breakeven_hit"] = True
            _add_event(trade, "BREAKEVEN", exit_price, pnl)
            _close_trade(trade, "BREAKEVEN", exit_price)
            return True, "BREAKEVEN"

        # No TP hit → real stop loss
        trade["sl_hit"] = True
        _add_event(trade, "SL", exit_price, pnl)
        _close_trade(trade, "SL", exit_price)
        return True, "SL"

    # --------------------------------------------------------
    # TARGET CHECKS
    # --------------------------------------------------------

    events = []

    if direction == "LONG":
        tp1_touched = current_price >= tp1
        tp2_touched = current_price >= tp2
        tp3_touched = current_price >= tp3
    else:
        tp1_touched = current_price <= tp1
        tp2_touched = current_price <= tp2
        tp3_touched = current_price <= tp3

    # --- TP1: close 50%, SL -> Entry ---
    if tp1_touched and not trade.get("tp1_hit", False):
        pnl = _record_realized_pnl(trade, tp1, 0.50)
        
        trade["tp1_hit"] = True
        trade["tp1_pnl"] = round(pnl, 8)
        
        trade["sl"] = entry
        trade["breakeven_active"] = True
        
        _add_event(trade, "TP1", tp1, pnl)
        events.append("TP1")

    # --- TP2: SL -> TP1 (NEW) ---
    if tp2_touched and not trade.get("tp2_hit", False):
        trade["tp2_hit"] = True
        trade["sl"] = tp1
        
        _add_event(trade, "TP2", tp2, 0.0)
        events.append("TP2")

    # --- TP3: close remaining ---
    if tp3_touched and not trade.get("tp3_hit", False):
        trade["tp3_hit"] = True
        trade["sl"] = tp2

        remaining_fraction = max(
            0.0, 
            1.0 - float(trade.get("realized_fraction", 0.0))
        )
        
        pnl = _record_realized_pnl(trade, tp3, remaining_fraction) if remaining_fraction > 0 else 0.0

        _add_event(trade, "TP3", tp3, pnl)
        _close_trade(trade, "TP3", tp3)
        events.append("TP3")

    if events:
        return True, "+".join(events)

    return False, None


# ============================================================
# CHECK ALL OPEN TRADES
# ============================================================

def check_all_trades(
    get_price,
) -> List[Dict[str, Any]]:
    emitted_events = []

    with LOCK:
        trades = _load_trades()
        changed_any = False

        for trade in trades:
            if str(trade.get("status", "")).upper() != "OPEN":
                continue

            symbol = str(trade.get("symbol", "")).strip().upper()
            if not symbol:
                continue

            try:
                price = get_price(symbol)
            except Exception as exc:
                logger.warning("Price lookup failed for %s: %s", symbol, exc)
                continue

            current_price = _positive(price)
            if not current_price:
                continue

            changed, event = update_trade(trade, current_price)
            if not changed:
                continue

            changed_any = True

            emitted_events.append({
                "symbol": symbol,
                "direction": trade.get("direction"),
                "strategy": trade.get("strategy"),
                "event": event,
                "price": trade.get("last_price"),
                "entry": trade.get("entry"),
                "sl": trade.get("sl"),
                "tp1": trade.get("tp1"),
                "tp2": trade.get("tp2"),
                "tp3": trade.get("tp3"),
                "tp1_hit": trade.get("tp1_hit", False),
                "tp2_hit": trade.get("tp2_hit", False),
                "tp3_hit": trade.get("tp3_hit", False),
                "status": trade.get("status"),
                "close_reason": trade.get("close_reason"),
                "tp1_pnl": trade.get("tp1_pnl", 0.0),
                "realized_pnl": trade.get("realized_pnl", 0.0),
                "roi_percent": _roi_percent(trade),
                "margin": trade.get("margin", DEFAULT_MARGIN),
                "leverage": trade.get("leverage", DEFAULT_LEVERAGE),
                "events": trade.get("events", []),
            })

        if changed_any:
            _save_trades(trades)

    return emitted_events


# ============================================================
# OPEN TRADES
# ============================================================

def get_open_trades() -> List[Dict[str, Any]]:
    with LOCK:
        return [
            trade for trade in _load_trades()
            if str(trade.get("status", "")).upper() == "OPEN"
        ]


# ============================================================
# STATISTICS
# ============================================================

def get_stats() -> Dict[str, Any]:
    with LOCK:
        trades = _load_trades()

    total = len(trades)
    open_trades = [t for t in trades if str(t.get("status", "")).upper() == "OPEN"]
    closed_trades = [t for t in trades if str(t.get("status", "")).upper() == "CLOSED"]

    tp1_count = sum(bool(t.get("tp1_hit")) for t in trades)
    tp2_count = sum(bool(t.get("tp2_hit")) for t in trades)
    tp3_count = sum(bool(t.get("tp3_hit")) for t in trades)

    sl_count = sum(
        str(t.get("close_reason", "")).upper() == "SL"
        for t in trades
    )
    breakeven_count = sum(
        str(t.get("close_reason", "")).upper() == "BREAKEVEN"
        for t in trades
    )
    tp1_protected_count = sum(
        str(t.get("close_reason", "")).upper() == "TP1_PROTECTED"
        for t in trades
    )

    realized_pnl = sum(float(t.get("realized_pnl", 0.0) or 0.0) for t in trades)
    total_margin = sum(float(t.get("margin", DEFAULT_MARGIN) or DEFAULT_MARGIN) for t in trades)
    closed_margin = sum(float(t.get("margin", DEFAULT_MARGIN) or DEFAULT_MARGIN) for t in closed_trades)

    realized_roi = (realized_pnl / total_margin * 100.0) if total_margin > 0 else 0.0
    closed_roi = (
        sum(float(t.get("realized_pnl", 0.0) or 0.0) for t in closed_trades)
        / closed_margin * 100.0
        if closed_margin > 0 else 0.0
    )

    strategies = {}
    for trade in trades:
        strategy = str(trade.get("strategy", "UNKNOWN"))
        strategies[strategy] = strategies.get(strategy, 0) + 1

    symbols = {}
    for trade in trades:
        symbol = str(trade.get("symbol", "UNKNOWN"))
        symbols[symbol] = symbols.get(symbol, 0) + 1

    return {
        "total": total,
        "open": len(open_trades),
        "closed": len(closed_trades),
        "tp1": tp1_count,
        "tp2": tp2_count,
        "tp3": tp3_count,
        "sl": sl_count,
        "breakeven": breakeven_count,
        "tp1_protected": tp1_protected_count,
        "tp3_rate": (tp3_count / total * 100.0) if total > 0 else 0.0,
        "realized_pnl": round(realized_pnl, 8),
        "realized_roi": round(realized_roi, 4),
        "closed_realized_pnl": round(
            sum(float(t.get("realized_pnl", 0.0) or 0.0) for t in closed_trades),
            8
        ),
        "closed_roi": round(closed_roi, 4),
        "strategies": strategies,
        "symbols": symbols,
    }


# ============================================================
# STATISTICS BY STRATEGY (Added for Daily Report)
# ============================================================

def get_stats_by_strategy() -> Dict[str, Dict[str, Any]]:
    """
    Return statistics grouped by strategy.
    Each strategy gets its own breakdown of signals, targets, and stops.
    """
    with LOCK:
        trades = _load_trades()

    stats: Dict[str, Dict[str, Any]] = {}

    for trade in trades:
        strategy = str(trade.get("strategy", "UNKNOWN")).strip() or "UNKNOWN"

        if strategy not in stats:
            stats[strategy] = {
                "total": 0,
                "open": 0,
                "closed": 0,
                "tp1": 0,
                "tp2": 0,
                "tp3": 0,
                "sl": 0,
                "breakeven": 0,
                "tp1_protected": 0,
                "realized_pnl": 0.0,
                "wins": 0,
                "losses": 0,
            }

        s = stats[strategy]
        s["total"] += 1

        status = str(trade.get("status", "")).upper()
        if status == "OPEN":
            s["open"] += 1
        elif status == "CLOSED":
            s["closed"] += 1

        if trade.get("tp1_hit"):
            s["tp1"] += 1
        if trade.get("tp2_hit"):
            s["tp2"] += 1
        if trade.get("tp3_hit"):
            s["tp3"] += 1

        reason = str(trade.get("close_reason", "")).upper()
        if reason == "SL":
            s["sl"] += 1
            s["losses"] += 1
        elif reason == "BREAKEVEN":
            s["breakeven"] += 1
        elif reason == "TP1_PROTECTED":
            s["tp1_protected"] += 1
            s["wins"] += 1
        elif reason == "TP3":
            s["wins"] += 1

        s["realized_pnl"] += float(trade.get("realized_pnl", 0.0) or 0.0)

    # Round pnl
    for s in stats.values():
        s["realized_pnl"] = round(s["realized_pnl"], 4)

    return stats


# ============================================================
# DAILY STATISTICS
# ============================================================

def get_daily_stats() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    start = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    with LOCK:
        trades = _load_trades()

    daily_trades = []

    for trade in trades:
        created = parse_time(
            trade.get("created_at")
        )

        if created and created >= start:
            daily_trades.append(trade)

    realized_pnl = sum(
        float(trade.get("realized_pnl", 0.0) or 0.0)
        for trade in daily_trades
    )

    return {
        "date": start.date().isoformat(),
        "total": len(daily_trades),

        "open": sum(
            str(trade.get("status", "")).upper() == "OPEN"
            for trade in daily_trades
        ),

        "closed": sum(
            str(trade.get("status", "")).upper() == "CLOSED"
            for trade in daily_trades
        ),

        "tp1": sum(
            bool(trade.get("tp1_hit"))
            for trade in daily_trades
        ),

        "tp2": sum(
            bool(trade.get("tp2_hit"))
            for trade in daily_trades
        ),

        "tp3": sum(
            bool(trade.get("tp3_hit"))
            for trade in daily_trades
        ),

        "sl": sum(
            str(trade.get("close_reason", "")).upper() == "SL"
            for trade in daily_trades
        ),

        "breakeven": sum(
            str(trade.get("close_reason", "")).upper() == "BREAKEVEN"
            for trade in daily_trades
        ),

        "tp1_protected": sum(
            str(trade.get("close_reason", "")).upper() == "TP1_PROTECTED"
            for trade in daily_trades
        ),

        "realized_pnl": round(realized_pnl, 8),
    }


# ============================================================
# SEVEN-DAY REPORT
# ============================================================

def get_7day_report() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)

    with LOCK:
        trades = _load_trades()

    recent_trades = []

    for trade in trades:
        created = parse_time(
            trade.get("created_at")
        )

        if created and created >= start:
            recent_trades.append(trade)

    realized_pnl = sum(
        float(trade.get("realized_pnl", 0.0) or 0.0)
        for trade in recent_trades
    )

    return {
        "total": len(recent_trades),

        "open": sum(
            str(trade.get("status", "")).upper() == "OPEN"
            for trade in recent_trades
        ),

        "closed": sum(
            str(trade.get("status", "")).upper() == "CLOSED"
            for trade in recent_trades
        ),

        "tp1": sum(
            bool(trade.get("tp1_hit"))
            for trade in recent_trades
        ),

        "tp2": sum(
            bool(trade.get("tp2_hit"))
            for trade in recent_trades
        ),

        "tp3": sum(
            bool(trade.get("tp3_hit"))
            for trade in recent_trades
        ),

        "sl": sum(
            str(trade.get("close_reason", "")).upper() == "SL"
            for trade in recent_trades
        ),

        "breakeven": sum(
            str(trade.get("close_reason", "")).upper() == "BREAKEVEN"
            for trade in recent_trades
        ),

        "tp1_protected": sum(
            str(trade.get("close_reason", "")).upper() == "TP1_PROTECTED"
            for trade in recent_trades
        ),

        "realized_pnl": round(realized_pnl, 8),
    }


# ============================================================
# REPORT FORMATTING
# ============================================================

def format_daily_report() -> str:
    stats = get_daily_stats()

    return (
        "📊 DAILY TRACKER REPORT\n\n"
        f"📅 Date: {stats['date']}\n"
        f"📌 Total Signals: {stats['total']}\n"
        f"⏳ Open: {stats['open']}\n"
        f"🔒 Closed: {stats['closed']}\n\n"
        f"🎯 TP1 Hit: {stats['tp1']}\n"
        f"🎯 TP2 Hit: {stats['tp2']}\n"
        f"🎯 TP3 Hit: {stats['tp3']}\n"
        f"🛑 SL Hit: {stats['sl']}\n"
        f"⚖️ Break-even: {stats['breakeven']}\n"
        f"✅ TP1 Protected: {stats['tp1_protected']}\n\n"
        f"💵 Realized PnL: ${stats['realized_pnl']:.4f}\n\n"
        "Simulation only; fees and funding excluded."
    )


def format_7day_report() -> str:
    stats = get_7day_report()

    return (
        "📊 7-DAY TRACKER REPORT\n\n"
        f"📌 Total Signals: {stats['total']}\n"
        f"⏳ Open: {stats['open']}\n"
        f"🔒 Closed: {stats['closed']}\n\n"
        f"🎯 TP1 Hit: {stats['tp1']}\n"
        f"🎯 TP2 Hit: {stats['tp2']}\n"
        f"🎯 TP3 Hit: {stats['tp3']}\n"
        f"🛑 SL Hit: {stats['sl']}\n"
        f"⚖️ Break-even: {stats['breakeven']}\n"
        f"✅ TP1 Protected: {stats['tp1_protected']}\n\n"
        f"💵 Realized PnL: ${stats['realized_pnl']:.4f}\n\n"
        "Simulation only; fees and funding excluded."
    )
