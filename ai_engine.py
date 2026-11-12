import numpy as np
import logging
import joblib
import os

logger = logging.getLogger(__name__)

# لیست ویژگی‌هایی که AI بر اساس آن‌ها تصمیم می‌گیرد
FEATURES = [
    "rsi_15m", 
    "adx_1h", 
    "volume_ratio", 
    "daily_trend_score", 
    "h4_trend_score", 
    "strategy_id",
    "hour_of_day"
]

# نقشه‌برداری استراتژی‌ها به عدد برای مدل
STRATEGY_MAP = {
    "SR_BREAKOUT": 1, "LIQUIDITY_SWEEP": 2, "AMD_STRATEGY": 3,
    "BREAKOUT": 4, "SR_REJECTION": 5, "FAST_TREND": 6,
    "SESSION_LIQUIDITY": 7, "RANGE_TRADING": 8, "BB_REVERSION": 9, "REVERSAL": 10
}

class AITrader:
    def __init__(self):
        self.model_path = "ai_model.pkl"
        self.model = None
        self.is_ready = False
        self.load_or_init_model()

    def load_or_init_model(self):
        """اگر مدل ذخیره شده وجود داشت، آن را لود می‌کند. در غیر این صورت یک مدل پایه می‌سازد."""
        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                self.is_ready = True
                logger.info("AI_ENGINE | Pre-trained model loaded successfully.")
            except Exception as e:
                logger.error(f"AI_ENGINE | Failed to load model: {e}")
        else:
            logger.warning("AI_ENGINE | No pre-trained model found. AI will run in 'Shadow Mode' (allowing all trades).")
            # در حالت شادو، ربات بدون فیلتر AI کار می‌کند تا دیتا جمع شود

    def extract_features(self, result, btc_context):
        """استخراج ویژگی‌های عددی از سیگنال فعلی برای تغذیه به AI"""
        try:
            rsi_15 = float(result.get("15m_rsi", 50))
            adx_1h = float(result.get("adx_1h", 20))
            
            # شاخص حجم (اگر حجم بالا باشد 1.0، در غیر این صورت 0.5)
            volume_ratio = 1.0 if result.get("volume_spike") else 0.5
            
            # امتیاز روند روزانه (1=Bullish, -1=Bearish, 0=Range)
            daily_dir = result.get("daily", "RANGE")
            daily_score = 1 if daily_dir == "BULLISH" else (-1 if daily_dir == "BEARISH" else 0)
            
            h4_dir = result.get("4h", "RANGE")
            h4_score = 1 if h4_dir == "BULLISH" else (-1 if h4_dir == "BEARISH" else 0)
            
            strat_name = result.get("strategy", "UNKNOWN")
            strat_id = STRATEGY_MAP.get(strat_name, 0)
            
            # ساعت روز (سشن‌ها)
            import datetime
            hour = datetime.datetime.now(datetime.timezone.utc).hour

            return [
                rsi_15,
                adx_1h,
                volume_ratio,
                daily_score,
                h4_score,
                strat_id,
                hour
            ]
        except Exception as e:
            logger.error(f"AI_ENGINE | Feature extraction error: {e}")
            return None

    def predict_confidence(self, features):
        """احتمال موفقیت سیگنال را بر اساس مدل محاسبه می‌کند"""
        if not self.is_ready or features is None:
            return 100.0 # اگر مدل آماده نبود، همه سیگنال‌ها را تایید کن (حالت شادو)

        try:
            # ورودی باید به شکل آرایه دو بعدی باشد
            X = np.array([features])
            
            # پیش‌بینی احتمال کلاس 1 (موفقیت)
            probabilities = self.model.predict_proba(X)
            confidence = probabilities[0][1] * 100 # تبدیل به درصد
            
            return confidence
        except Exception as e:
            logger.error(f"AI_ENGINE | Prediction error: {e}")
            return 100.0

# یک نمونه سراسری برای استفاده در ربات
ai_brain = AITrader()
