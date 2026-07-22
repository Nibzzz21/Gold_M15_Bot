import os
import requests

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing Telegram secrets.")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
        print("Telegram alert sent successfully!")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def check_gold_15m():
    if not TWELVE_DATA_API_KEY:
        print("Error: Missing TWELVE_DATA_API_KEY secret.")
        return

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": "XAU/USD",
        "interval": "15min",
        "outputsize": 5,
        "apikey": TWELVE_DATA_API_KEY
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
    except Exception as e:
        print(f"Network error: {e}")
        return

    if "values" not in data:
        print(f"API Error: {data.get('message', 'Unknown error')}")
        return

    values = data["values"]
    if len(values) < 3:
        print("Insufficient candle data.")
        return

    # Twelve Data gives newest closed candle at index 0
    curr = values[0]
    p1   = values[1]
    p2   = values[2]

    curr_close    = float(curr["close"])
    max_prev_high = max(float(p1["high"]), float(p2["high"]))
    min_prev_low  = min(float(p1["low"]), float(p2["low"]))
    candle_time   = curr["datetime"]

    # Evaluate conditions
    if curr_close > max_prev_high:
        msg = (
            f"🚀 *GOLD (XAU/USD) 15M ALERT*\n\n"
            f"⏰ *Time:* {candle_time} UTC\n"
            f"📈 Candle closed **HIGHER** than previous 2 candles high!\n\n"
            f"• *Close:* `${curr_close:.2f}`\n"
            f"• *Prev Max High:* `${max_prev_high:.2f}`"
        )
        send_telegram_alert(msg)
    elif curr_close < min_prev_low:
        msg = (
            f"🔻 *GOLD (XAU/USD) 15M ALERT*\n\n"
            f"⏰ *Time:* {candle_time} UTC\n"
            f"📉 Candle closed **LOWER** than previous 2 candles low!\n\n"
            f"• *Close:* `${curr_close:.2f}`\n"
            f"• *Prev Min Low:* `${min_prev_low:.2f}`"
        )
        send_telegram_alert(msg)
    else:
        print(f"[{candle_time}] Candle closed within range. No alert sent.")

if __name__ == "__main__":
    check_gold_15m()
      
