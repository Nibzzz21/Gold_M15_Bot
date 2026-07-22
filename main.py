import os
import requests
import time
from datetime import datetime, timedelta

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
    # 1. Wait 12 seconds to ensure Twelve Data API updates its feed
    print("Waiting 12 seconds for candle feed sync...")
    time.sleep(12)

    if not TWELVE_DATA_API_KEY:
        print("Error: Missing TWELVE_DATA_API_KEY secret.")
        return

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": "XAU/USD",
        "interval": "15min",
        "outputsize": 10,
        "timezone": "Asia/Karachi",  # Requests Pakistan Standard Time
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
    if len(values) < 4:
        print("Insufficient candle data.")
        return

    # 2. Compute exact expected open time for the candle that just closed (PKT)
    now_pkt = datetime.utcnow() + timedelta(hours=5)
    minute_offset = now_pkt.minute % 15
    current_candle_open = now_pkt - timedelta(minutes=minute_offset, seconds=now_pkt.second, microseconds=now_pkt.microseconds)
    target_closed_candle_open = current_candle_open - timedelta(minutes=15)
    target_open_str = target_closed_candle_open.strftime("%Y-%m-%d %H:%M:00")

    # 3. Dynamic Indexing: Automatically locate the correct completed candle
    if values[0]["datetime"] == target_open_str:
        # Twelve Data hasn't pushed a new live candle yet; values[0] is the closed candle
        closed_candle = values[0]
        prev_1        = values[1]
        prev_2        = values[2]
    elif values[1]["datetime"] == target_open_str:
        # Twelve Data created the live forming candle at values[0]; values[1] is the closed candle
        closed_candle = values[1]
        prev_1        = values[2]
        prev_2        = values[3]
    else:
        # Fallback to values[1] if timestamps vary slightly
        closed_candle = values[1]
        prev_1        = values[2]
        prev_2        = values[3]

    curr_close    = float(closed_candle["close"])
    max_prev_high = max(float(prev_1["high"]), float(prev_2["high"]))
    min_prev_low  = min(float(prev_1["low"]), float(prev_2["low"]))
    
    # Calculate exact Candle CLOSE Time (Open Time + 15 minutes)
    raw_open_str = closed_candle["datetime"]
    dt_open      = datetime.strptime(raw_open_str, "%Y-%m-%d %H:%M:%S")
    dt_close     = dt_open + timedelta(minutes=15)
    
    close_time_pkt = dt_close.strftime("%d-%b-%Y %I:%M %p PKT")

    print(f"Analyzing candle that closed at {close_time_pkt}...")
    print(f"Closed Price: {curr_close} | Max Prev High: {max_prev_high} | Min Prev Low: {min_prev_low}")

    # Evaluate breakout conditions
    if curr_close > max_prev_high:
        msg = (
            f"🚀 *GOLD (XAU/USD) 15M BREAKOUT*\n\n"
            f"⏰ *Candle Closed At:* `{close_time_pkt}`\n"
            f"📈 Closed **HIGHER** than previous 2 candles high!\n\n"
            f"• *Close:* `${curr_close:.2f}`\n"
            f"• *Highest High:* `${max_prev_high:.2f}`"
        )
        send_telegram_alert(msg)
    elif curr_close < min_prev_low:
        msg = (
            f"🔻 *GOLD (XAU/USD) 15M BREAKOUT*\n\n"
            f"⏰ *Candle Closed At:* `{close_time_pkt}`\n"
            f"📉 Closed **LOWER** than previous 2 candles low!\n\n"
            f"• *Close:* `${curr_close:.2f}`\n"
            f"• *Lowest Low:* `${min_prev_low:.2f}`"
        )
        send_telegram_alert(msg)
    else:
        msg = (
            f"⚪ *GOLD (XAU/USD) 15M RANGE*\n\n"
            f"⏰ *Candle Closed At:* `{close_time_pkt}`\n"
            f"↔️ Candle closed **WITHIN RANGE** (No breakout).\n\n"
            f"• *Close:* `${curr_close:.2f}`\n"
            f"• *Range:* `${min_prev_low:.2f}` - `${max_prev_high:.2f}`"
        )
        send_telegram_alert(msg)

if __name__ == "__main__":
    check_gold_15m()
    
