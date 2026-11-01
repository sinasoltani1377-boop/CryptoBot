import os
import logging
import threading
from typing import Any, Dict, Optional

import ccxt

logger = logging.getLogger(__name__)

TOOBIT_ENABLED      = os.getenv("TOOBIT_ENABLED", "0") == "1"
TOOBIT_API_KEY      = os.getenv("TOOBIT_API_KEY", "")
TOOBIT_SECRET       = os.getenv("TOOBIT_SECRET", "")
TOOBIT_LEVERAGE     = int(os.getenv("TOOBIT_LEVERAGE", "20"))
TOOBIT_MARGIN_USDT  = float(os.getenv("TOOBIT_MARGIN_USDT", "1"))

_exchange: Optional[ccxt.toobit] = None
_init_lock = threading.Lock()
_order_lock = threading.Lock()


def is_enabled() -> bool:
    return TOOBIT_ENABLED and bool(TOOBIT_API_KEY) and bool(TOOBIT_SECRET)


def _get_exchange() -> Optional[ccxt.toobit]:
    global _exchange
    if not is_enabled():
        return None
    with _init_lock:
        if _exchange is None:
            try:
                _exchange = ccxt.toobit({
                    "apiKey": TOOBIT_API_KEY,
                    "secret": TOOBIT_SECRET,
                    "enableRateLimit": True,
                    "options": {"defaultType": "swap"},   # پرپچوال USDT-M
                })
                logger.info("CCXT Toobit آماده شد")
            except Exception as exc:
                logger.exception("خطا در راه‌اندازی Toobit: %s", exc)
                return None
    return _exchange


def _to_ccxt_symbol(toobit_symbol: str) -> str:
    # "BTC-SWAP-USDT" → "BTC/USDT:USDT"
    if toobit_symbol.endswith("-SWAP-USDT"):
        base = toobit_symbol[:-len("-SWAP-USDT")]
        return f"{base}/USDT:USDT"
    return toobit_symbol


def open_position(
    toobit_symbol: str,
    direction: str,
    reference_price: float,
) -> Optional[Dict[str, Any]]:
    """باز کردن پوزیشن مارکت روی Toobit با اهرم تنظیم‌شده."""
    ex = _get_exchange()
    if ex is None:
        return None

    direction = str(direction).upper()
    if direction not in ("LONG", "SHORT"):
        return None

    side = "buy" if direction == "LONG" else "sell"
    symbol = _to_ccxt_symbol(toobit_symbol)

    try:
        # ۱) ست کردن اهرم و حالت ایزوله
        with _order_lock:
            try:
                ex.set_leverage(TOOBIT_LEVERAGE, symbol)
                ex.set_margin_mode("isolated", symbol)
            except Exception:
                # اگه قبلاً ست شده، خطا میده — نادیده بگیر
                logger.debug("set_leverage/margin_mode رد شد برای %s", symbol)

        # ۲) محاسبه حجم از ارزش اسمی
        price = float(reference_price)
        if price <= 0:
            return None
        notional = TOOBIT_MARGIN_USDT * TOOBIT_LEVERAGE
        amount = ex.amount_to_precision(symbol, notional / price)

        # ۳) ارسال سفارش مارکت
        with _order_lock:
            order = ex.create_order(
                symbol=symbol,
                type="market",
                side=side,
                amount=float(amount),
            )

    except Exception as exc:
        logger.exception("باز کردن در Toobit شکست خورد %s: %s", toobit_symbol, exc)
        return None

    logger.info(
        "Toobit OPEN | %s | %s | amt=%s | lev=%sx | id=%s",
        toobit_symbol, side, amount, TOOBIT_LEVERAGE, order.get("id"),
    )

    return {
        "exchange": "toobit",
        "order_id": order.get("id"),
        "symbol": symbol,
        "side": side,
        "amount": float(amount),
        "price": price,
        "leverage": TOOBIT_LEVERAGE,
        "margin_usdt": TOOBIT_MARGIN_USDT,
    }


def close_fraction(
    toobit_symbol: str,
    direction: str,
    original_amount: float,
    fraction: float,
    reference_price: float,
) -> bool:
    """بستن `fraction` (بین ۰ تا ۱) از پوزیشن اصلی با سفارش مارکت."""
    ex = _get_exchange()
    if ex is None:
        return False

    direction = str(direction).upper()
    close_side = "sell" if direction == "LONG" else "buy"
    symbol = _to_ccxt_symbol(toobit_symbol)

    fraction = max(0.0, min(float(fraction), 1.0))
    amount_to_close = float(original_amount) * fraction
    if amount_to_close <= 0:
        return True

    try:
        amount_str = ex.amount_to_precision(symbol, amount_to_close)
        with _order_lock:
            order = ex.create_order(
                symbol=symbol,
                type="market",
                side=close_side,
                amount=float(amount_str),
                params={"reduceOnly": True},   # 🔑 فقط کاهش پوزیشن، نه باز کردن عکس
            )
    except Exception as exc:
        logger.exception("بستن در Toobit شکست خورد %s: %s", toobit_symbol, exc)
        return False

    logger.info(
        "Toobit CLOSE | %s | %s | amt=%s | frac=%.2f | id=%s",
        toobit_symbol, close_side, amount_str, fraction, order.get("id"),
    )
    return True


def fetch_balance() -> Optional[Dict[str, Any]]:
    ex = _get_exchange()
    if ex is None:
        return None
    try:
        return ex.fetch_balance()
    except Exception:
        logger.exception("دریافت موجودی Toobit شکست خورد")
        return None
