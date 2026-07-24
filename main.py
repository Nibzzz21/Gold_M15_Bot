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
        print("Waiting 12 seconds for candle feed sync...")
        time.sleep(12)

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

        # 2. Match exact closed candle
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

        # Candle range pips: ((High - Low) + 1) * 10
        candle_range_diff = curr_high - curr_low
        candle_pips = (candle_range_diff + 1.0) * 10.0

        # 3. Calculate 50 EMA up to the closed candle
        candles_chrono = values[::-1]
        target_chrono_idx = len(values) - 1 - idx
        relevant_history = candles_chrono[:target_chrono_idx + 1]

        ema_50 = calculate_ema50(relevant_history)
        
        # Safely format EMA display string
        if ema_50 is not None:
            ema_str = f"${ema_50:.2f}"
            if curr_close > ema_50:
                trend_status = f"🟢 Bullish Trend (Above 50 EMA @ {ema_str})"
            else:
                trend_status = f"🔴 Bearish Trend (Below 50 EMA @ {ema_str})"
        else:
            ema_str = "N/A"
            trend_status = "⚠️ N/A (Insufficient history for EMA)"

        # 4. Format Close Time
        raw_open_str = closed_candle["datetime"]
        dt_open      = datetime.strptime(raw_open_str, "%Y-%m-%d %H:%M:%S")
        dt_close     = dt_open + timedelta(minutes=15)
        close_time_pkt = dt_close.strftime("%d-%b-%Y %I:%M %p PKT")

        print(f"Target candle matched: Opened {raw_open_str} | Closed {close_time_pkt}")
        print(f"Close: {curr_close} | High: {curr_high} | Low: {curr_low} | 50 EMA: {ema_str}")

        # 5. Breakout & Inside Bar Evaluation
        if curr_close > prev1_high:
            # Bullish Breakout
            sl_price = curr_low
            sl_dist  = abs(curr_close - sl_price)
            sl_pips  = (sl_dist + 1.0) * 10.0
            
            # Lot size formula: 50 / ((pips * 10) + 50)
            lot_size = 50.0 / ((sl_pips * 10.0) + 50.0)

            msg = (
                f"⬆️ *GOLD (XAU/USD) 15M BULLISH BREAKOUT*\n\n"
                f"⏰ *Candle Closed At:* `{close_time_pkt}`\n"
                f"📈 Closed **ABOVE** previous candle high!\n\n"
                f"• *Recent Close:* `${curr_close:.2f}`\n"
                f"• *Prev High Broken:* `${prev1_high:.2f}`\n"
                f"• *Recent Candle Range:* `${curr_low:.2f}` - `${curr_high:.2f}`\n"
                f"• *Candle Range Pips:* `{candle_pips:.1f}` pips\n"
                f"• *Stop Loss (SL):* `${sl_price:.2f}`\n"
                f"• *Recommended Lot Size ($50 Risk):* `{lot_size:.2f}` lots\n\n"
                f"📊 *Trend:* {trend_status}"
            )
            send_telegram_alert(msg)

        elif curr_close < prev1_low:
            # Bearish Breakout
            sl_price = curr_high
            sl_dist  = abs(curr_close - sl_price)
            sl_pips  = (sl_dist + 1.0) * 10.0
            
            # Lot size formula: 50 / ((pips * 10) + 50)
            lot_size = 50.0 / ((sl_pips * 10.0) + 50.0)

            msg = (
                f"⬇️ *GOLD (XAU/USD) 15M BEARISH BREAKOUT*\n\n"
                f"⏰ *Candle Closed At:* `{close_time_pkt}`\n"
                f"📉 Closed **BELOW** previous candle low!\n\n"
                f"• *Recent Close:* `${curr_close:.2f}`\n"
                f"• *Prev Low Broken:* `${prev1_low:.2f}`\n"
                f"• *Recent Candle Range:* `${curr_low:.2f}` - `${curr_high:.2f}`\n"
                f"• *Candle Range Pips:* `{candle_pips:.1f}` pips\n"
                f"• *Stop Loss (SL):* `${sl_price:.2f}`\n"
                f"• *Recommended Lot Size ($50 Risk):* `{lot_size:.2f}` lots\n\n"
                f"📊 *Trend:* {trend_status}"
            )
            send_telegram_alert(msg)

        else:
            # Check if Inside Bar relative to previous 2 candles
            is_inside_bar = (curr_high <= max_prev2_high) and (curr_low >= min_prev2_low)

            if is_inside_bar:
                msg = (
                    f"📦 *GOLD (XAU/USD) 15M INSIDE BAR*\n\n"
                    f"⏰ *Candle Closed At:* `{close_time_pkt}`\n"
                    f"🔒 Candle is inside the range of previous 2 candles. Trend is most likely to continue.\n\n"
                    f"• *Recent Close:* `${curr_close:.2f}`\n"
                    f"• *Recent Candle Range:* `${curr_low:.2f}` - `${curr_high:.2f}`\n"
                    f"• *Candle Range Pips:* `{candle_pips:.1f}` pips\n"
                    f"• *Prev 2-Candle Range:* `${min_prev2_low:.2f}` - `${max_prev2_high:.2f}`\n\n"
                    f"📊 *Trend:* {trend_status}"
                )
                send_telegram_alert(msg)
            else:
                print("Candle closed within range. No Telegram alert sent.")

    except Exception as err:
        print("An error occurred during execution:")
        traceback.print_exc()

if __name__ == "__main__":
    check_gold_15m()
    
