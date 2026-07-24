import os
import requests
import time
import traceback
from datetime import datetime, timedelta, timezone

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

def calculate_ema50(candles_chronological: list) -> float:
    closes = [float(c["close"]) for c in candles_chronological]
    if len(closes) < 50:
        return None

    ema = sum(closes[:50]) / 50.0
    multiplier = 2 / (50 + 1)

    for price in closes[50:]:
        ema = (price - ema) * multiplier + ema

    return ema

def check_gold_15m():
    try:
        if not TWELVE_DATA_API_KEY:
            print("Error: Missing TWELVE_DATA_API_KEY secret.")
            return

        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": "XAU/USD",
            "interval": "15min",
            "outputsize": 80,
            "timezone": "Asia/Karachi",
            "apikey": TWELVE_DATA_API_KEY
        }

        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        if "values" not in data:
            print(f"API Error: {data.get('message', 'Unknown error')}")
            return

        values = data["values"]
        if len(values) < 60:
            print("Insufficient candle data returned.")
            return

        # 1. Compute expected open time for the target closed candle (PKT = UTC+5)
        now_pkt = datetime.now(timezone.utc) + timedelta(hours=5)
        minute_offset = now_pkt.minute % 15
        
        current_candle_open = now_pkt.replace(second=0, microsecond=0) - timedelta(minutes=minute_offset)
        target_closed_candle_open = current_candle_open - timedelta(minutes=15)
        target_open_str = target_closed_candle_open.strftime("%Y-%m-%d %H:%M:00")

        # 2. Dynamic Match: Search values for the exact target closed candle timestamp
        idx = None
        for i, candle in enumerate(values):
            if candle.get("datetime") == target_open_str:
                idx = i
                break

        if idx is None:
            print(f"Target closed candle ({target_open_str}) not yet synced in Twelve Data feed.")
            return

        if idx + 2 >= len(values):
            print("Not enough historic candles returned after target candle.")
            return

        closed_candle = values[idx]
        prev_1        = values[idx + 1]
        prev_2        = values[idx + 2]

        # Extract prices
        curr_close = float(closed_candle["close"])
        curr_high  = float(closed_candle["high"])
        curr_low   = float(closed_candle["low"])

        prev1_high = float(prev_1["high"])
        prev1_low  = float(prev_1["low"])

        prev2_high = float(prev_2["high"])
        prev2_low  = float(prev_2["low"])

        max_prev2_high = max(prev1_high, prev2_high)
        min_prev2_low  = min(prev1_low, prev2_low)

        # 3. Calculate 50 EMA up to the closed candle
        candles_chrono = values[::-1]
        target_chrono_idx = len(values) - 1 - idx
        relevant_history = candles_chrono[:target_chrono_idx + 1]

        ema_50 = calculate_ema50(relevant_history)
        
        if ema_50 is not None:
            if curr_close > ema_50:
                trend_status = f"🟢 Bullish Trend (Above 50 EMA @ `${ema_50:.2f}`)"
            else:
                trend_status = f"🔴 Bearish Trend (Below 50 EMA @ `${ema_50:.2f}`)"
        else:
            trend_status = "⚠️ N/A (Insufficient history for EMA)"

        # 4. Format Close Time
        raw_open_str = closed_candle["datetime"]
        dt_open      = datetime.strptime(raw_open_str, "%Y-%m-%d %H:%M:%S")
        dt_close     = dt_open + timedelta(minutes=15)
        close_time_pkt = dt_close.strftime("%d-%b-%Y %I:%M %p PKT")

        print(f"Target candle matched: Opened {raw_open_str} | Closed {close_time_pkt}")
        print(f"Close: {curr_close} | Prev High: {prev1_high} | Prev Low: {prev1_low} | 50 EMA: {ema_50:.2f if ema_50 else 'N/A'}")

        # 5. Breakout & Inside Bar Evaluation
        if curr_close > prev1_high:
            msg = (
                f"⬆️ *GOLD (XAU/USD) 15M BULLISH BREAKOUT*\n\n"
                f"⏰ *Candle Closed At:* `{close_time_pkt}`\n"
                f"📈 Closed **ABOVE** previous candle high!\n\n"
                f"• *Recent Close:* `${curr_close:.2f}`\n"
                f"• *Prev Candle High:* `${prev1_high:.2f}`\n"
                f"• *Prev Candle Low:* `${prev1_low:.2f}`\n"
                f"• *Prev Range:* `${prev1_low:.2f}` - `${prev1_high:.2f}`\n"
                f"• *Stop Loss (SL):* `${curr_low:.2f}`\n\n"
                f"📊 *Trend:* {trend_status}"
            )
            send_telegram_alert(msg)

        elif curr_close < prev1_low:
            msg = (
                f"⬇️ *GOLD (XAU/USD) 15M BEARISH BREAKOUT*\n\n"
                f"⏰ *Candle Closed At:* `{close_time_pkt}`\n"
                f"📉 Closed **BELOW** previous candle low!\n\n"
                f"• *Recent Close:* `${curr_close:.2f}`\n"
                f"• *Prev Candle High:* `${prev1_high:.2f}`\n"
                f"• *Prev Candle Low:* `${prev1_low:.2f}`\n"
                f"• *Prev Range:* `${prev1_low:.2f}` - `${prev1_high:.2f}`\n"
                f"• *Stop Loss (SL):* `${curr_high:.2f}`\n\n"
                f"📊 *Trend:* {trend_status}"
            )
            send_telegram_alert(msg)

        else:
            is_inside_bar = (curr_high <= max_prev2_high) and (curr_low >= min_prev2_low)

            if is_inside_bar:
                msg = (
                    f"📦 *GOLD (XAU/USD) 15M INSIDE BAR*\n\n"
                    f"⏰ *Candle Closed At:* `{close_time_pkt}`\n"
                    f"🔒 Candle is inside the range of previous 2 candles. Trend is most likely to continue.\n\n"
                    f"• *Recent Close:* `${curr_close:.2f}`\n"
                    f"• *Prev 2-Candle Range:* `${min_prev2_low:.2f}` - `${max_prev2_high:.2f}`\n\n"
                    f"📊 *Trend:* {trend_status}"
                )
                send_telegram_alert(msg)
            else:
                print("Candle closed within range. No Telegram alert sent.")

    except Exception as err:
        print("An error occurred during execution:")
        traceback.print_exc()

def get_seconds_until_next_run(lead_seconds: int = 15) -> float:
    """
    Calculates exact sleep time until the next 15-min mark + lead_seconds delay.
    Target times: :00:15, :15:15, :30:15, :45:15.
    """
    now = datetime.now(timezone.utc)
    minute_offset = now.minute % 15
    current_interval_start = now.replace(second=0, microsecond=0) - timedelta(minutes=minute_offset)
    
    # Target execution time for current interval
    target_time = current_interval_start + timedelta(seconds=lead_seconds)
    
    # If target time for current interval has passed, target the next interval (+15 mins)
    if now >= target_time:
        target_time += timedelta(minutes=15)
        
    return (target_time - now).total_seconds()

def main():
    print("Gold 15M Monitor started. Synchronizing with 15-minute candle intervals...")
    while True:
        try:
            sleep_time = get_seconds_until_next_run(lead_seconds=15)
            next_run = datetime.now(timezone.utc) + timedelta(seconds=sleep_time)
            next_run_pkt = next_run + timedelta(hours=5)
            
            print(f"\nNext check scheduled at {next_run_pkt.strftime('%H:%M:%S PKT')} (sleeping for {int(sleep_time)}s)...")
            time.sleep(sleep_time)
            
            print(f"Waking up at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} to analyze completed candle...")
            check_gold_15m()
            
        except KeyboardInterrupt:
            print("\nMonitor stopped manually.")
            break
        except Exception as e:
            print(f"Unexpected error in main loop: {e}")
            time.sleep(10)  # Brief pause before retrying loop

if __name__ == "__main__":
    main()
            
