import requests
import time

# API Key خودت رو بذار اینجا
API_KEY = "YOUR_API_KEY"  

# حداقل حجم 24ساعته دلاری برای فیلتر کردن کوین‌ها
MIN_VOLUME = 1000000 

# حداکثر تعداد کوین‌هایی که میخوای بررسی کنی
LIMIT = 100  

# آدرس API
url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

params = {
    "start": "1",
    "limit": LIMIT,
    "convert": "USD"
}

headers = {
    "Accepts": "application/json",
    "X-CMC_PRO_API_KEY": API_KEY
}

try:
    response = requests.get(url, params=params, headers=headers)
    data = response.json()["data"]

    results = []
    for coin in data:
        volume_24h = coin["quote"]["USD"]["volume_24h"]
        if volume_24h < MIN_VOLUME:
            continue

        price = coin["quote"]["USD"]["price"]
        ath = coin["quote"]["USD"].get("ath_price", price)  # اگر API قرارداد ATH نداشت
        atl = coin["quote"]["USD"].get("atl_price", price)  # اگر API قرارداد ATL نداشت

        # محاسبه فاصله‌ها
        if ath != 0:
            dist_to_ath_pct = ((ath - price) / ath) * 100
        else:
            dist_to_ath_pct = 0
        
        if atl != 0:
            dist_to_atl_pct = ((price - atl) / atl) * 100
        else:
            dist_to_atl_pct = 0

        potential_growth = ath / price if price != 0 else 0

        results.append({
            "symbol": coin["symbol"],
            "price": price,
            "volume_24h": volume_24h,
            "dist_to_ath_%": dist_to_ath_pct,
            "dist_to_atl_%": dist_to_atl_pct,
            "growth_x": potential_growth
        })

        time.sleep(0.3)  # برای جلوگیری از بلاک شدن API

    # مرتب‌سازی بر اساس بیشترین فاصله تا ATH
    sorted_coins = sorted(results, key=lambda x: x["dist_to_ath_%"], reverse=True)

    print("Top Coins by Distance to ATH:")
    for c in sorted_coins[:20]:
        print(f"{c['symbol']}: Price ${c['price']:.4f}, "
              f"Vol ${c['volume_24h']:.0f}, "
              f"ATH Dist {c['dist_to_ath_%']:.2f}%, "
              f"ATL Dist {c['dist_to_atl_%']:.2f}%, "
              f"Growth x{c['growth_x']:.2f}")

except Exception as e:
    print(f"Error: {e}")
