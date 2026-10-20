from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

# CryptoBot Analysis Engine v15
# Strategy model: TREND_FOLLOWING, PULLBACK, BREAKOUT, REVERSAL
# Closed candles only. Conservative multi-timeframe filters. No RANGE_TRADING.

STRATEGIES = ("TREND_FOLLOWING", "PULLBACK", "BREAKOUT", "REVERSAL")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError, OverflowError):
        return default


def candle_values(c: Any) -> Tuple[float, float, float, float, float]:
    if isinstance(c, dict):
        return (safe_float(c.get("open", c.get("o", c.get("Open", 0)))),
                safe_float(c.get("high", c.get("h", c.get("High", 0)))),
                safe_float(c.get("low", c.get("l", c.get("Low", 0)))),
                safe_float(c.get("close", c.get("c", c.get("Close", 0)))),
                safe_float(c.get("volume", c.get("v", c.get("Volume", 0)))))
    if isinstance(c, (list, tuple)):
        # Toobit-style kline: [timestamp, open, high, low, close, volume, ...]
        if len(c) >= 6:
            return safe_float(c[1]), safe_float(c[2]), safe_float(c[3]), safe_float(c[4]), safe_float(c[5])
        if len(c) >= 5:
            return safe_float(c[0]), safe_float(c[1]), safe_float(c[2]), safe_float(c[3]), safe_float(c[4])
    return 0.0, 0.0, 0.0, 0.0, 0.0


def normalize_candles(candles: Any) -> List[Any]:
    if isinstance(candles, dict):
        for key in ("data", "result", "rows", "klines", "candles"):
            if isinstance(candles.get(key), list):
                candles = candles[key]
                break
    if not isinstance(candles, list):
        return []
    out = []
    for c in candles:
        o, h, l, cl, _ = candle_values(c)
        if min(o, h, l, cl) <= 0 or h < l or not (l <= o <= h and l <= cl <= h):
            continue
        out.append(c)
    return out


def closed(candles: Any, count: int = 1) -> List[Any]:
    """Drop the newest candle (assumed to be still forming)."""
    arr = normalize_candles(candles)
    if len(arr) <= max(1, count):
        return []
    return arr[:-1]


def closes(cs: List[Any]) -> List[float]: return [candle_values(c)[3] for c in cs]
def highs(cs: List[Any]) -> List[float]: return [candle_values(c)[1] for c in cs]
def lows(cs: List[Any]) -> List[float]: return [candle_values(c)[2] for c in cs]
def volumes(cs: List[Any]) -> List[float]: return [candle_values(c)[4] for c in cs]
def body(c: Any) -> float:
    o, _, _, cl, _ = candle_values(c); return abs(cl-o)
def candle_range(c: Any) -> float:
    _, h, l, _, _ = candle_values(c); return max(0.0, h-l)
def body_ratio(c: Any) -> float:
    r = candle_range(c); return body(c)/r if r > 0 else 0.0
def bullish(c: Any) -> bool:
    o, _, _, cl, _ = candle_values(c); return cl > o
def bearish(c: Any) -> bool:
    o, _, _, cl, _ = candle_values(c); return cl < o
def upper_wick(c: Any) -> float:
    o,h,_,cl,_=candle_values(c); return max(0.0,h-max(o,cl))
def lower_wick(c: Any) -> float:
    o,_,l,cl,_=candle_values(c); return max(0.0,min(o,cl)-l)


def ema(values: List[float], period: int) -> Optional[float]:
    if period <= 0 or len(values) < period: return None
    k=2.0/(period+1.0); value=sum(values[:period])/period
    for x in values[period:]: value=x*k+value*(1-k)
    return value


def ema_values(values: List[float], period: int) -> List[float]:
    if period <= 0 or len(values) < period: return []
    k=2.0/(period+1.0); value=sum(values[:period])/period; out=[value]
    for x in values[period:]:
        value=x*k+value*(1-k); out.append(value)
    return out


def rsi(cs: List[Any], period: int=14) -> float:
    cls=closes(cs)
    if len(cls) <= period: return 50.0
    diffs=[cls[i]-cls[i-1] for i in range(1,len(cls))]
    ag=sum(max(x,0.0) for x in diffs[:period])/period
    al=sum(max(-x,0.0) for x in diffs[:period])/period
    for x in diffs[period:]:
        ag=(ag*(period-1)+max(x,0.0))/period
        al=(al*(period-1)+max(-x,0.0))/period
    if al <= 0: return 100.0 if ag > 0 else 50.0
    rs=ag/al; return 100.0-100.0/(1.0+rs)


def atr(cs: List[Any], period: int=14) -> float:
    if len(cs) < period+1: return 0.0
    trs=[]; prev=candle_values(cs[0])[3]
    for c in cs[1:]:
        _,h,l,cl,_=candle_values(c); trs.append(max(h-l,abs(h-prev),abs(l-prev))); prev=cl
    if len(trs)<period: return 0.0
    value=sum(trs[:period])/period
    for tr in trs[period:]: value=(value*(period-1)+tr)/period
    return value


def adx(cs: List[Any], period: int=14) -> float:
    if len(cs) < period*2+1: return 0.0
    trs=[]; plus=[]; minus=[]; prev_close=candle_values(cs[0])[3]
    for i in range(1,len(cs)):
        _,h,l,cl,_=candle_values(cs[i]); _,ph,pl,_,_=candle_values(cs[i-1])
        up=h-ph; down=pl-l
        plus.append(up if up>down and up>0 else 0.0)
        minus.append(down if down>up and down>0 else 0.0)
        trs.append(max(h-l,abs(h-prev_close),abs(l-prev_close))); prev_close=cl
    trn=sum(trs[:period]); pn=sum(plus[:period]); mn=sum(minus[:period]); dxs=[]
    for i in range(period,len(trs)):
        trn=trn-trn/period+trs[i]; pn=pn-pn/period+plus[i]; mn=mn-mn/period+minus[i]
        if trn<=0: continue
        pdi=100*pn/trn; mdi=100*mn/trn; denom=pdi+mdi
        dxs.append(100*abs(pdi-mdi)/denom if denom>0 else 0.0)
    if len(dxs)<period: return 0.0
    value=sum(dxs[:period])/period
    for dx in dxs[period:]: value=(value*(period-1)+dx)/period
    return value


def volume_spike(cs: List[Any], multiplier: float=1.15, lookback: int=20) -> bool:
    vs=volumes(cs)
    if len(vs)<lookback+1: return False
    avg=sum(vs[-lookback-1:-1])/lookback
    return avg>0 and vs[-1]>=avg*multiplier


def confirmed_swings(cs: List[Any], strength: int=2, lookback: int=80) -> Tuple[List[Tuple[int,float]],List[Tuple[int,float]]]:
    """Return confirmed pivot highs/lows; last `strength` candles cannot confirm a pivot."""
    arr=cs[-lookback:]
    hs,ls=highs(arr),lows(arr); ph=[]; pl=[]
    for i in range(strength, len(arr)-strength):
        h_ok=all(hs[i]>hs[i-j] for j in range(1,strength+1)) and all(hs[i]>=hs[i+j] for j in range(1,strength+1))
        l_ok=all(ls[i]<ls[i-j] for j in range(1,strength+1)) and all(ls[i]<=ls[i+j] for j in range(1,strength+1))
        if h_ok: ph.append((i,hs[i]))
        if l_ok: pl.append((i,ls[i]))
    return ph,pl


def market_structure(cs: List[Any], lookback: int=80) -> str:
    if len(cs)<30: return "RANGE"
    ph,pl=confirmed_swings(cs,2,lookback)
    if len(ph)<2 or len(pl)<2: return "RANGE"
    h1,h2=ph[-2][1],ph[-1][1]; l1,l2=pl[-2][1],pl[-1][1]
    # A structure trend requires both swing highs and swing lows to progress in the same direction.
    if h2>h1 and l2>l1: return "BULLISH"
    if h2<h1 and l2<l1: return "BEARISH"
    return "RANGE"


def ema_direction(cs: List[Any]) -> str:
    cls=closes(cs); e20=ema(cls,20); e50=ema(cls,50); e200=ema(cls,200) if len(cls)>=200 else None
    if e20 is None or e50 is None: return "RANGE"
    price=cls[-1]
    if e200 is not None:
        if price>e20>e50>e200: return "BULLISH"
        if price<e20<e50<e200: return "BEARISH"
    if price>e20>e50: return "BULLISH"
    if price<e20<e50: return "BEARISH"
    return "RANGE"


def direction_from_tf(cs: List[Any]) -> str:
    """Conservative trend classification: structure and EMA must agree."""
    if len(cs)<30: return "RANGE"
    structure=market_structure(cs); ema_dir=ema_direction(cs)
    return structure if structure==ema_dir and structure in ("BULLISH","BEARISH") else "RANGE"


def mtf_confirmation(m15: List[Any], direction: str) -> bool:
    if len(m15)<25: return False
    cls=closes(m15); e20=ema(cls,20); e50=ema(cls,50)
    if e20 is None or e50 is None: return False
    recent=m15[-3:]
    if direction=="LONG":
        return sum(bullish(c) for c in recent)>=2 and cls[-1]>e20 and cls[-1]>e50
    if direction=="SHORT":
        return sum(bearish(c) for c in recent)>=2 and cls[-1]<e20 and cls[-1]<e50
    return False


def entry_trigger_5m(m5: List[Any], direction: str) -> bool:
    if len(m5)<12: return False
    last=m5[-1]; prev=m5[-2]; prior=m5[-7:-1]
    close=candle_values(last)[3]
    if direction=="LONG":
        return bullish(last) and body_ratio(last)>=0.45 and close>max(highs(prior)) and (bullish(prev) or close>candle_values(prev)[1])
    if direction=="SHORT":
        return bearish(last) and body_ratio(last)>=0.45 and close<min(lows(prior)) and (bearish(prev) or close<candle_values(prev)[2])
    return False


def near_ema_zone(h1: List[Any], direction: str) -> bool:
    cls=closes(h1); e20=ema(cls,20); e50=ema(cls,50); a=atr(h1)
    if e20 is None or e50 is None or a<=0: return False
    price=cls[-1]; zone=max(a*0.45,price*0.0025)
    near=min(abs(price-e20),abs(price-e50))<=zone
    if direction=="LONG": return near and price>=min(e20,e50) and e20>e50
    if direction=="SHORT": return near and price<=max(e20,e50) and e20<e50
    return False


def rejection(c: Any, direction: str) -> bool:
    r=candle_range(c)
    if r<=0: return False
    o,_,_,cl,_=candle_values(c)
    if direction=="LONG": return lower_wick(c)>=body(c)*0.8 and lower_wick(c)/r>=0.30 and cl>o
    if direction=="SHORT": return upper_wick(c)>=body(c)*0.8 and upper_wick(c)/r>=0.30 and cl<o
    return False


def pullback_detected(h1: List[Any], direction: str) -> bool:
    if len(h1)<30: return False
    cls=closes(h1); e20=ema(cls,20); e50=ema(cls,50); a=atr(h1)
    if e20 is None or e50 is None or a<=0: return False
    recent=h1[-8:]; price=cls[-1]; zone=max(a*0.45,price*0.003)
    if direction=="LONG":
        touched=any(candle_values(c)[2] <= e20+zone for c in recent[:-1])
        return e20>e50 and touched and price>e20 and bullish(h1[-1])
    if direction=="SHORT":
        touched=any(candle_values(c)[1] >= e20-zone for c in recent[:-1])
        return e20<e50 and touched and price<e20 and bearish(h1[-1])
    return False


def local_breakout(m15: List[Any], direction: str, lookback: int=20) -> Tuple[bool,float]:
    if len(m15)<lookback+2: return False,0.0
    prev=m15[-lookback-1:-1]; last=m15[-1]; level=max(highs(prev)) if direction=="LONG" else min(lows(prev))
    close=candle_values(last)[3]
    return ((close>level if direction=="LONG" else close<level),level)


def breakout_retest(m15: List[Any], direction: str, level: float) -> bool:
    """Require the broken level to hold after a prior closed-candle break."""
    if len(m15)<4 or level<=0: return False
    last=m15[-1]; _,h,l,cl,_=candle_values(last)
    prior=m15[-4:-1]
    if direction=="LONG":
        had_break=any(candle_values(c)[3]>level for c in prior)
        return had_break and l<=level*1.002 and cl>level and bullish(last)
    if direction=="SHORT":
        had_break=any(candle_values(c)[3]<level for c in prior)
        return had_break and h>=level*0.998 and cl<level and bearish(last)
    return False


def sweep_reclaim_recent(m15: List[Any], direction: str, lookback: int=12) -> bool:
    if len(m15)<lookback+4: return False
    base=m15[-lookback-4:-4]
    if not base: return False
    bh=max(highs(base)); bl=min(lows(base))
    for c in m15[-4:]:
        _,h,l,cl,_=candle_values(c)
        if direction=="LONG" and l<bl and cl>bl and bullish(c): return True
        if direction=="SHORT" and h>bh and cl<bh and bearish(c): return True
    return False


def structure_shift_5m(m5: List[Any], direction: str) -> bool:
    if len(m5)<12: return False
    prior=m5[-8:-1]; last=m5[-1]; close=candle_values(last)[3]
    if direction=="LONG": return bullish(last) and body_ratio(last)>=0.5 and close>max(highs(prior))
    if direction=="SHORT": return bearish(last) and body_ratio(last)>=0.5 and close<min(lows(prior))
    return False


def detect_trend_following(h1: List[Any], m15: List[Any], m5: List[Any], direction: str) -> Dict[str,Any]:
    expected="BULLISH" if direction=="LONG" else "BEARISH"
    structure=market_structure(h1); ema_dir=ema_direction(h1); a=adx(h1)
    if structure!=expected or ema_dir!=expected: return {"valid":False,"reason":"STRUCTURE_EMA_DISAGREE"}
    if a<22: return {"valid":False,"reason":"ADX_BELOW_22"}
    if not mtf_confirmation(m15,direction): return {"valid":False,"reason":"15M_NOT_CONFIRMED"}
    if not entry_trigger_5m(m5,direction): return {"valid":False,"reason":"5M_TRIGGER"}
    score=6+(1 if a>=25 else 0)+(1 if pullback_detected(h1,direction) else 0)
    return {"valid":True,"reason":"VALID","score":score,"mtf":True}


def detect_pullback(h1: List[Any], m15: List[Any], m5: List[Any], direction: str) -> Dict[str,Any]:
    expected="BULLISH" if direction=="LONG" else "BEARISH"
    if market_structure(h1)!=expected or ema_direction(h1)!=expected: return {"valid":False,"reason":"STRUCTURE_EMA_DISAGREE"}
    if not pullback_detected(h1,direction): return {"valid":False,"reason":"NO_CONFIRMED_PULLBACK"}
    if not (near_ema_zone(h1,direction) or any(rejection(c,direction) for c in h1[-4:])): return {"valid":False,"reason":"NO_REJECTION_OR_EMA_ZONE"}
    if not mtf_confirmation(m15,direction): return {"valid":False,"reason":"15M_NOT_CONFIRMED"}
    if not entry_trigger_5m(m5,direction): return {"valid":False,"reason":"5M_TRIGGER"}
    return {"valid":True,"reason":"VALID","score":8,"mtf":True}


def detect_breakout(h1: List[Any], m15: List[Any], m5: List[Any], direction: str) -> Dict[str,Any]:
    if len(m15) < 26:
        return {"valid":False,"reason":"INSUFFICIENT_15M_BREAKOUT_DATA"}
    # Use a fixed pre-breakout range for both the immediate-break and retest cases.
    # The retest level must not be recalculated using the breakout candle itself.
    base = m15[-24:-4]
    level = max(highs(base)) if direction == "LONG" else min(lows(base))
    close = candle_values(m15[-1])[3]
    immediate = close > level if direction == "LONG" else close < level
    retest = breakout_retest(m15, direction, level)
    last=m15[-1]
    if not immediate and not retest: return {"valid":False,"reason":"NO_BREAKOUT_RETEST"}
    if body_ratio(last)<0.45: return {"valid":False,"reason":"WEAK_BREAKOUT_OR_RETEST"}
    if not volume_spike(m15,1.15,20): return {"valid":False,"reason":"NO_VOLUME_SPIKE"}
    if not mtf_confirmation(m15,direction): return {"valid":False,"reason":"15M_NOT_CONFIRMED"}
    if not entry_trigger_5m(m5,direction): return {"valid":False,"reason":"5M_TRIGGER"}
    return {"valid":True,"reason":"VALID","score":8 if retest else 7,"mtf":True,"level":level}


def detect_reversal(h1: List[Any], m15: List[Any], m5: List[Any], direction: str) -> Dict[str,Any]:
    if not sweep_reclaim_recent(m15,direction): return {"valid":False,"reason":"NO_SWEEP_RECLAIM"}
    if not structure_shift_5m(m5,direction): return {"valid":False,"reason":"NO_5M_STRUCTURE_SHIFT"}
    if body_ratio(m15[-1])<0.35: return {"valid":False,"reason":"WEAK_RECLAIM"}
    return {"valid":True,"reason":"VALID","score":8,"mtf":mtf_confirmation(m15,direction)}


def context_allows(strategy: str, daily: str, h4: str, direction: str, h4_adx: float) -> bool:
    expected="BULLISH" if direction=="LONG" else "BEARISH"
    continuation=strategy in ("TREND_FOLLOWING","PULLBACK","BREAKOUT")
    if continuation:
        # Continuation needs 4H confirmation. Do not trade continuation while 4H is neutral/opposite.
        if h4 != expected: return False
        # Daily opposition is allowed only when daily is neutral, not when clearly opposite.
        if daily not in (expected,"RANGE"): return False
    else:
        # Reversal must be supported by a 5M structure shift and M15 sweep/reclaim (checked in strategy).
        # Avoid calling a reversal when 4H has a strong opposing trend unless daily is neutral.
        if h4 in ("BULLISH","BEARISH") and h4!=expected and h4_adx>=35 and daily!= "RANGE": return False
    return True


def calculate_trade_levels(h1: List[Any], m5: List[Any], direction: str) -> Optional[Dict[str,float]]:
    if direction not in ("LONG","SHORT") or len(h1)<20 or not m5: return None
    entry=closes(m5)[-1]; a=atr(h1)
    if entry<=0 or a<=0: return None
    ph,pl=confirmed_swings(h1,2,80)
    if direction=="LONG":
        swing=pl[-1][1] if pl else entry-1.5*a
        sl=min(swing-0.25*a,entry-1.2*a)
        risk=entry-sl
        if risk<=0 or risk>3*a or risk/entry>0.035: return None
        tp1=entry+1.5*risk; tp2=entry+2.5*risk; tp3=entry+3*risk
        if not sl<entry<tp1<tp2<tp3: return None
    else:
        swing=ph[-1][1] if ph else entry+1.5*a
        sl=max(swing+0.25*a,entry+1.2*a)
        risk=sl-entry
        if risk<=0 or risk>3*a or risk/entry>0.035: return None
        tp1=entry-1.5*risk; tp2=entry-2.5*risk; tp3=entry-3*risk
        if not sl>entry>tp1>tp2>tp3: return None
    return {"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"risk":risk,"rr":"1:3"}


def target_reachable(levels: Dict[str,float], h1: List[Any], direction: str) -> bool:
    entry=safe_float(levels.get("entry")); tp1=safe_float(levels.get("tp1"))
    if entry<=0 or tp1<=0: return False
    ph,pl=confirmed_swings(h1,2,80)
    if direction=="LONG": return not any(entry<p<tp1 for _,p in ph)
    return not any(tp1<p<entry for _,p in pl)


def no_trade(reason: str, daily: str="RANGE", h4: str="RANGE", h1: str="RANGE", direction: Optional[str]=None, diagnostics: Optional[Dict[str,str]]=None, metrics: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    diagnostics=diagnostics or {}
    out={"signal":"NO_TRADE","direction":direction,"score":0,"quality":"LOW","reason":reason,
         "strategies":[n for n,s in diagnostics.items() if s=="VALID" or s.startswith("HIGH_FAIL:")],
         "strategy":None,"strategy_diagnostics":diagnostics,"daily":daily,"4h":h4,"1h":h1}
    if metrics: out.update(metrics)
    return out


def generate_signal(daily: Any, h4: Any, h1: Any, m15: Any, m5: Any) -> Dict[str,Any]:
    d=closed(daily); h4c=closed(h4); h1c=closed(h1); m15c=closed(m15); m5c=closed(m5)
    if min(len(d),len(h4c),len(h1c),len(m15c),len(m5c))<50:
        return no_trade("INSUFFICIENT_DATA")
    daily_dir=direction_from_tf(d); h4_dir=direction_from_tf(h4c); h1_dir=direction_from_tf(h1c)
    rsi15=round(rsi(m15c),2); adx1=round(adx(h1c),2); adx15=round(adx(m15c),2); h4adx=adx(h4c)
    volume=volume_spike(m15c,1.15,20)
    metrics={"15m_rsi":rsi15,"adx_1h":adx1,"adx_15m":adx15,"mtf_confirmation":False,"volume_spike":bool(volume),"confirmation":False}
    diagnostics: Dict[str,str]={}; valid=[]
    functions={"TREND_FOLLOWING":detect_trend_following,"PULLBACK":detect_pullback,"BREAKOUT":detect_breakout,"REVERSAL":detect_reversal}
    # Continuation strategies are considered only in the objectively classified 1H direction.
    # If 1H structure and EMA disagree, only a properly confirmed reversal can be considered.
    directions={"TREND_FOLLOWING":["LONG"] if h1_dir=="BULLISH" else (["SHORT"] if h1_dir=="BEARISH" else []),
                "PULLBACK":["LONG"] if h1_dir=="BULLISH" else (["SHORT"] if h1_dir=="BEARISH" else []),
                "BREAKOUT":["LONG","SHORT"],"REVERSAL":["LONG","SHORT"]}
    for name,fn in functions.items():
        options=[]; reasons=[]
        for direction in directions[name]:
            result=fn(h1c,m15c,m5c,direction)
            if not result.get("valid"):
                reasons.append(f"{direction}:{result.get('reason','UNKNOWN')}"); continue
            if not context_allows(name,daily_dir,h4_dir,direction,h4adx):
                reasons.append(f"{direction}:HTF_CONTEXT"); continue
            options.append((direction,result))
        if options:
            direction,result=max(options,key=lambda x:x[1].get("score",0))
            diagnostics[name]="VALID"
            valid.append((name,direction,result))
        else:
            diagnostics[name]="FAIL:"+"|".join(reasons or ["NO_DIRECTION_CANDIDATE"])
    # Only award confluence when independent strategy families agree on direction.
    candidates=[]; rejected=[]
    priority={"REVERSAL":4,"BREAKOUT":3,"PULLBACK":2,"TREND_FOLLOWING":1}
    for name,direction,result in valid:
        score=int(result.get("score",0))
        agreeing=sum(1 for other,odir,_ in valid if other!=name and odir==direction)
        # Confluence is a single point, not a substitute for mandatory filters.
        if agreeing: score+=1
        if name in ("TREND_FOLLOWING","PULLBACK","BREAKOUT"):
            if direction=="LONG" and rsi15>=75:
                diagnostics[name]="HIGH_FAIL:RSI_TOO_EXTENDED"; rejected.append("RSI_TOO_EXTENDED"); continue
            if direction=="SHORT" and rsi15<=25:
                diagnostics[name]="HIGH_FAIL:RSI_TOO_EXTENDED"; rejected.append("RSI_TOO_EXTENDED"); continue
        # Mandatory quality gates; a high numeric score cannot override these.
        if name=="TREND_FOLLOWING":
            high=score>=8 and adx1>=22 and result.get("mtf") and entry_trigger_5m(m5c,direction)
        elif name=="PULLBACK":
            high=score>=8 and result.get("mtf") and entry_trigger_5m(m5c,direction)
        elif name=="BREAKOUT":
            high=score>=8 and volume and result.get("mtf") and entry_trigger_5m(m5c,direction)
        else:
            high=score>=8 and structure_shift_5m(m5c,direction) and sweep_reclaim_recent(m15c,direction)
        if not high:
            diagnostics[name]="HIGH_FAIL:MANDATORY_FILTERS"; rejected.append("QUALITY_FILTER"); continue
        levels=calculate_trade_levels(h1c,m5c,direction)
        if not levels:
            diagnostics[name]="HIGH_FAIL:INVALID_TRADE_LEVELS"; rejected.append("INVALID_TRADE_LEVELS"); continue
        if not target_reachable(levels,h1c,direction):
            diagnostics[name]="HIGH_FAIL:TP1_BLOCKED"; rejected.append("TP1_BLOCKED"); continue
        candidates.append({"strategy":name,"direction":direction,"score":score,"levels":levels,"priority":priority[name],"mtf":bool(result.get("mtf"))})
    if not candidates:
        reason="TP1_BLOCKED" if "TP1_BLOCKED" in rejected else ("INVALID_TRADE_LEVELS" if "INVALID_TRADE_LEVELS" in rejected else ("RSI_TOO_EXTENDED" if rejected and all(x=="RSI_TOO_EXTENDED" for x in rejected) else "NO_VALID_HIGH_SETUP"))
        return no_trade(reason,daily_dir,h4_dir,h1_dir,None,diagnostics,metrics)
    candidates.sort(key=lambda x:(x["score"],x["priority"]),reverse=True)
    chosen=candidates[0]; direction=chosen["direction"]
    metrics["mtf_confirmation"]=bool(mtf_confirmation(m15c,direction)); metrics["confirmation"]=bool(entry_trigger_5m(m5c,direction))
    return {"signal":direction,"direction":direction,"score":chosen["score"],"quality":"HIGH","reason":f"VALID_{chosen['strategy']}",
            "strategies":[x["strategy"] for x in candidates if x["direction"]==direction],"strategy":chosen["strategy"],
            "strategy_diagnostics":diagnostics,"daily":daily_dir,"4h":h4_dir,"1h":h1_dir,
            "15m_rsi":rsi15,"adx_1h":adx1,"adx_15m":adx15,"mtf_confirmation":metrics["mtf_confirmation"],
            "volume_spike":bool(volume),"confirmation":metrics["confirmation"],**chosen["levels"]}


analyze=generate_signal
get_signal=generate_signal
