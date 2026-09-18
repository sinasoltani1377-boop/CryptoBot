import json
import os
import time
from datetime import datetime, timezone
import requests

TRADES_FILE = os.getenv("TRADES_FILE", "/tmp/cryptobot_trades.json")
COOLDOWN_SECONDS = 30 * 60

def now():
    return datetime.now(timezone.utc).isoformat()

def load_trades():
    if not os.path.exists(TRADES_FILE): return []
    try:
        with open(TRADES_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except Exception as e:
        print("TRACKER_LOAD_ERROR:", e); return []

def save_trades(trades):
    with open(TRADES_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)

def get_price(symbol):
    r = requests.get("https://api.toobit.com/quote/v1/contract/ticker/price", params={"symbol": symbol}, timeout=10)
    r.raise_for_status()
    return float(r.json()[0]["p"])

def has_open_trade(symbol, trades):
    return any(t.get("symbol") == symbol and t.get("status") == "OPEN" for t in trades)

def recently_closed(symbol, trades):
    for t in reversed(trades):
        if t.get("symbol") == symbol and t.get("status") == "CLOSED":
            try: return time.time() - float(t.get("closed_timestamp", 0)) < COOLDOWN_SECONDS
            except (TypeError, ValueError): return False
    return False

def register_signal(symbol, result):
    trades = load_trades()
    if has_open_trade(symbol, trades) or recently_closed(symbol, trades): return None, False
    required = ["entry", "sl", "tp1", "tp2", "tp3"]
    if any(result.get(k) is None for k in required): return None, False
    trade = {
        "id": f"{symbol}-{int(time.time()*1000)}", "symbol": symbol,
        "direction": result.get("signal"), "entry": float(result["entry"]),
        "sl": float(result["sl"]), "tp1": float(result["tp1"]),
        "tp2": float(result["tp2"]), "tp3": float(result["tp3"]),
        "risk": float(result.get("risk", 0)), "rr": float(result.get("rr", 3)),
        "score": int(result.get("score", 0)), "quality": result.get("quality", "UNKNOWN"),
        "strategies": result.get("strategy_matches", []), "daily": result.get("daily"),
        "4h": result.get("4h"), "1h": result.get("1h"), "status": "OPEN",
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False, "sl_hit": False,
        "created_at": now(), "updated_at": now(), "closed_at": None,
        "closed_timestamp": None, "result": None, "close_price": None
    }
    trades.append(trade); save_trades(trades); return trade, True

def mark_tp(t, n):
    k = f"tp{n}_hit"
    if not t.get(k): t[k] = True; return True
    return False

def update_trade(t, price):
    d = t.get("direction")
    if d == "LONG":
        if price <= t["sl"]:
            t.update(sl_hit=True, status="CLOSED", result="SL", close_price=price); return "SL"
        if price >= t["tp3"]:
            t.update(tp1_hit=True, tp2_hit=True, tp3_hit=True, status="CLOSED", result="TP3", close_price=price); return "TP3"
        if price >= t["tp2"]:
            mark_tp(t,1); mark_tp(t,2); return "TP2" if not t.get("tp2_notified") else None
        if price >= t["tp1"]:
            if mark_tp(t,1): return "TP1"
    elif d == "SHORT":
        if price >= t["sl"]:
            t.update(sl_hit=True, status="CLOSED", result="SL", close_price=price); return "SL"
        if price <= t["tp3"]:
            t.update(tp1_hit=True, tp2_hit=True, tp3_hit=True, status="CLOSED", result="TP3", close_price=price); return "TP3"
        if price <= t["tp2"]:
            mark_tp(t,1); mark_tp(t,2); return "TP2" if not t.get("tp2_notified") else None
        if price <= t["tp1"]:
            if mark_tp(t,1): return "TP1"
    return None

def check_open_trades():
    trades = load_trades(); events=[]; changed=False
    for t in trades:
        if t.get("status") != "OPEN": continue
        try:
            p=get_price(t["symbol"]); event=update_trade(t,p); t["updated_at"]=now(); changed=True
            if event:
                if event == "TP2": t["tp2_notified"] = True
                events.append({"trade": dict(t), "event": event, "price": p})
            if t.get("status") == "CLOSED":
                t["closed_at"]=now(); t["closed_timestamp"]=time.time()
        except Exception as e: print(f"TRACKER_PRICE_ERROR {t.get('symbol')}: {e}")
    if changed: save_trades(trades)
    return events

def get_stats():
    trades=load_trades(); closed=[t for t in trades if t.get("status")=="CLOSED"]
    s={"total":len(trades),"open":len(trades)-len(closed),"closed":len(closed),"tp1":0,"tp2":0,"tp3":0,"sl":0,"strategies":{}}
    for t in closed:
        r=t.get("result");
        if r in ("TP1","TP2","TP3"): s[r.lower()] += 1
        elif r=="SL": s["sl"] += 1
        for name in t.get("strategies",[]):
            x=s["strategies"].setdefault(name,{"trades":0,"tp1":0,"tp2":0,"tp3":0,"sl":0})
            x["trades"] += 1
            if r in ("TP1","TP2","TP3"): x[r.lower()] += 1
            elif r=="SL": x["sl"] += 1
    return s

def format_stats():
    s=get_stats(); out=["📊 CryptoBot Tracker","",f"📌 Total: {s['total']}",f"🟢 Open: {s['open']}",f"🔴 Closed: {s['closed']}",f"🎯 TP1: {s['tp1']}",f"🎯 TP2: {s['tp2']}",f"🎯 TP3: {s['tp3']}",f"🛑 SL: {s['sl']}"]
    if s["strategies"]:
        out += ["","🧠 Strategy performance:"]
        for n,x in sorted(s["strategies"].items(), key=lambda z:z[1]["trades"], reverse=True):
            out.append(f"\n{n}\nTrades: {x['trades']} | TP1: {x['tp1']} | TP2: {x['tp2']} | TP3: {x['tp3']} | SL: {x['sl']}")
    return "\n".join(out)
