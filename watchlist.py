# ============================================================
# watchlist.py — 50 coins configured for Toobit (Fixed Names)
# ============================================================

WATCHLIST = {
    # ---- CORE 10 ----
    "BTC":  {"symbol": "BTC-SWAP-USDT",  "category": "core"},
    "ETH":  {"symbol": "ETH-SWAP-USDT",  "category": "core"},
    "BNB":  {"symbol": "BNB-SWAP-USDT",  "category": "core"},
    "SOL":  {"symbol": "SOL-SWAP-USDT",  "category": "core"},
    "XRP":  {"symbol": "XRP-SWAP-USDT",  "category": "core"},
    "HYPE": {"symbol": "HYPE-SWAP-USDT", "category": "core"},
    "LINK": {"symbol": "LINK-SWAP-USDT", "category": "core"},
    "SUI":  {"symbol": "SUI-SWAP-USDT",  "category": "core"},
    "TRX":  {"symbol": "TRX-SWAP-USDT",  "category": "core"},
    "DOGE": {"symbol": "DOGE-SWAP-USDT", "category": "core"},

    # ---- LAYER 1 ----
    "ADA":  {"symbol": "ADA-SWAP-USDT",  "category": "l1"},
    "AVAX": {"symbol": "AVAX-SWAP-USDT", "category": "l1"},
    "TON":  {"symbol": "TON-SWAP-USDT",  "category": "l1"},
    "NEAR": {"symbol": "NEAR-SWAP-USDT", "category": "l1"},
    "APT":  {"symbol": "APT-SWAP-USDT",  "category": "l1"},
    "SEI":  {"symbol": "SEI-SWAP-USDT",  "category": "l1"},
    "KAS":  {"symbol": "KAS-SWAP-USDT",  "category": "l1"},
    "HBAR": {"symbol": "HBAR-SWAP-USDT", "category": "l1"},
    "XLM":  {"symbol": "XLM-SWAP-USDT",  "category": "l1"},
    "DOT":  {"symbol": "DOT-SWAP-USDT",  "category": "l1"},
    "ATOM": {"symbol": "ATOM-SWAP-USDT", "category": "l1"},

    # ---- DEFI / ORACLE ----
    "UNI":    {"symbol": "UNI-SWAP-USDT",    "category": "defi"},
    "AAVE":   {"symbol": "AAVE-SWAP-USDT",   "category": "defi"},
    "ONDO":   {"symbol": "ONDO-SWAP-USDT",   "category": "defi"},
    "PENDLE": {"symbol": "PENDLE-SWAP-USDT", "category": "defi"},
    "JUP":    {"symbol": "JUP-SWAP-USDT",    "category": "defi"},
    "LDO":    {"symbol": "LDO-SWAP-USDT",    "category": "defi"},
    "CRV":    {"symbol": "CRV-SWAP-USDT",    "category": "defi"},
    "INJ":    {"symbol": "INJ-SWAP-USDT",    "category": "defi"},
    "RUNE":   {"symbol": "RUNE-SWAP-USDT",   "category": "defi"},

    # ---- MEMECOINS (اصلاح شده با پیشوند 1000) ----
    "PEPE":  {"symbol": "1000PEPE-SWAP-USDT",  "category": "meme"},
    "SHIB":  {"symbol": "1000SHIB-SWAP-USDT",  "category": "meme"},
    "BONK":  {"symbol": "1000BONK-SWAP-USDT",  "category": "meme"},
    "FLOKI": {"symbol": "1000FLOKI-SWAP-USDT", "category": "meme"},
    "WIF":   {"symbol": "WIF-SWAP-USDT",       "category": "meme"},

    # ---- AI / DEPIN ----
    "TAO":    {"symbol": "TAO-SWAP-USDT",    "category": "ai"},
    "RENDER": {"symbol": "RENDER-SWAP-USDT", "category": "ai"},
    "FET":    {"symbol": "FET-SWAP-USDT",    "category": "ai"},
    "AR":     {"symbol": "AR-SWAP-USDT",     "category": "ai"},

    # ---- LAYER 2 ----
    "ARB": {"symbol": "ARB-SWAP-USDT", "category": "l2"},
    "OP":  {"symbol": "OP-SWAP-USDT",  "category": "l2"},
    "IMX": {"symbol": "IMX-SWAP-USDT", "category": "l2"},
    "POL": {"symbol": "POL-SWAP-USDT", "category": "l2"},

    # ---- EXCHANGE TOKENS ----
    "OKB": {"symbol": "OKB-SWAP-USDT", "category": "exchange"},

    # ---- RWA ----
    "XAUT": {"symbol": "XAUT-SWAP-USDT", "category": "rwa"},
    "PAXG": {"symbol": "PAXG-SWAP-USDT", "category": "rwa"},

    # ---- LEGACY ----
    "LTC": {"symbol": "LTC-SWAP-USDT", "category": "legacy"},
    "BCH": {"symbol": "BCH-SWAP-USDT", "category": "legacy"},
    "ETC": {"symbol": "ETC-SWAP-USDT", "category": "legacy"},

    # ---- PRIVACY ----
    "XMR": {"symbol": "XMR-SWAP-USDT", "category": "privacy"},
    "ZEC": {"symbol": "ZEC-SWAP-USDT", "category": "privacy"},
}

def get_symbols():
    return [cfg["symbol"] for cfg in WATCHLIST.values()]
