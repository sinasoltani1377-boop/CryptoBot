import json
import os
import threading
from datetime import datetime, timezone

TRADES_FILE = os.getenv(
    "TRADES_FILE",
    "/tmp/cryptobot_trades.json"
)
_lock = threading.Lock()


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


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def register_signal(symbol, signal):
    """
    Register a new HIGH signal.
    """

    if not isinstance(signal, dict):
        return None

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

    trades = _load_trades()

    trade_id = (
        f"{symbol}_"
        f"{direction}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    )

    trade = {
        "id": trade_id,
        "symbol": symbol,
        "direction": direction,

        "quality": signal.get("quality"),
        "score": signal.get("score"),

        "strategy": signal.get("strategy"),
        "strategies": signal.get("strategies", []),

        "entry": float(entry),
        "sl": float(sl),

        "tp1": float(tp1),
        "tp2": float(tp2),
        "tp3": float(tp3),

        "risk": signal.get("risk"),
        "rr": signal.get("rr"),

        "created_at": utc_now(),

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
    }

    trades.append(trade)
    _save_trades(trades)

    return trade


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

    entry = float(trade["entry"])
    sl = float(trade["sl"])
    tp1 = float(trade["tp1"])
    tp2 = float(trade["tp2"])
    tp3 = float(trade["tp3"])

    now = utc_now()

    # --------------------------------------------------
    # LONG
    # --------------------------------------------------
    if direction == "LONG":

        # SL has priority if price reaches it
        if price <= sl:
            trade["sl_hit"] = True
            trade["sl_time"] = now
            trade["status"] = "CLOSED"
            trade["result"] = "SL"
            trade["closed_at"] = now

            return True, "SL"

        if not trade["tp1_hit"] and price >= tp1:
            trade["tp1_hit"] = True
            trade["tp1_time"] = now
            return True, "TP1"

        if not trade["tp2_hit"] and price >= tp2:
            trade["tp2_hit"] = True
            trade["tp2_time"] = now
            return True, "TP2"

        if not trade["tp3_hit"] and price >= tp3:
            trade["tp3_hit"] = True
            trade["tp3_time"] = now

            trade["status"] = "CLOSED"
            trade["result"] = "TP3"
            trade["closed_at"] = now

            return True, "TP3"

    # --------------------------------------------------
    # SHORT
    # --------------------------------------------------
    elif direction == "SHORT":

        if price >= sl:
            trade["sl_hit"] = True
            trade["sl_time"] = now
            trade["status"] = "CLOSED"
            trade["result"] = "SL"
            trade["closed_at"] = now

            return True, "SL"

        if not trade["tp1_hit"] and price <= tp1:
            trade["tp1_hit"] = True
            trade["tp1_time"] = now
            return True, "TP1"

        if not trade["tp2_hit"] and price <= tp2:
            trade["tp2_hit"] = True
            trade["tp2_time"] = now
            return True, "TP2"

        if not trade["tp3_hit"] and price <= tp3:
            trade["tp3_hit"] = True
            trade["tp3_time"] = now

            trade["status"] = "CLOSED"
            trade["result"] = "TP3"
            trade["closed_at"] = now

            return True, "TP3"

    return False, None


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

        try:
            price = price_getter(symbol)
        except Exception:
            continue

        if price is None:
            continue

        changed, event = update_trade(trade, price)

        if changed:
            changed_any = True

            events.append({
                "trade": trade.copy(),
                "event": event,
                "price": float(price)
            })

    if changed_any:
        _save_trades(trades)

    return events


def get_open_trades():
    trades = _load_trades()

    return [
        trade
        for trade in trades
        if trade.get("status") == "OPEN"
    ]


def get_all_trades():
    return _load_trades()


def get_stats():
    trades = _load_trades()

    total = len(trades)

    open_count = 0
    sl_count = 0
    tp1_count = 0
    tp2_count = 0
    tp3_count = 0

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

    closed = total - open_count

    return {
        "total": total,
        "open": open_count,
        "closed": closed,
        "sl": sl_count,
        "tp1": tp1_count,
        "tp2": tp2_count,
        "tp3": tp3_count,
    }
