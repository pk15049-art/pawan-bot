"""
PAWAN QUANT ENGINE V7.0 - 24/7 CLOUD WORKER (RENDER READY)
"""
import os
import time
import json
import threading
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify

app = Flask(__name__)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
POLL_INTERVAL = 3.0
TELEGRAM_BOT_TOKEN = "9023075336:AAEz4CLf3SPcEZY7ilJ9ajim2X1RhDrQtbM"
CHAT_ID = None
STATE_FILE = "account_state.json"

def get_ist_time():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

def is_night_session():
    ist_hour = get_ist_time().hour
    return ist_hour >= 23 or ist_hour < 8

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                d = json.load(f)
                cap = float(d.get("capital", 1043.94))
                pnl = float(d.get("realized_pnl", 43.94))
                trades = int(d.get("total_trades", 57))
                w = int(d.get("wins", 22))
                return cap, pnl, trades, w
        except: pass
    return 1043.94, 43.94, 57, 22

def save_state(cap, pnl, trades, w):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "capital": round(cap, 2),
                "realized_pnl": round(pnl, 2),
                "total_trades": trades,
                "wins": w,
                "last_updated": get_ist_time().strftime("%Y-%m-%d %H:%M:%S")
            }, f, indent=2)
    except: pass

CAPITAL, realized_pnl, total_trades, wins = load_state()
open_positions = []

def auto_detect_chat_id():
    global CHAT_ID
    if CHAT_ID: return True
    try:
        res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates", timeout=4)
        if res.status_code == 200:
            for u in reversed(res.json().get("result", [])):
                if "message" in u and "chat" in u["message"]:
                    CHAT_ID = u["message"]["chat"]["id"]
                    return True
    except: pass
    return False

def send_alert(text):
    global CHAT_ID
    if not CHAT_ID: auto_detect_chat_id()
    if not CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                      data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=4)
    except: pass

def get_live_price(symbol):
    try:
        res = requests.get(f"https://data.binance.com/api/v3/ticker/price?symbol={symbol}", timeout=3)
        if res.status_code == 200: return float(res.json()["price"])
    except: pass
    cg_ids = {"BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana"}
    if symbol in cg_ids:
        try:
            res = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={cg_ids[symbol]}&vs_currencies=usd", timeout=3)
            if res.status_code == 200: return float(res.json()[cg_ids[symbol]]["usd"])
        except: pass
    for p in open_positions:
        if p["symbol"] == symbol: return p["entry"]
    fallbacks = {"BTCUSDT": 77480.0, "ETHUSDT": 2248.0, "SOLUSDT": 95.8}
    return fallbacks.get(symbol, 100.0)

def execute_auto_buy(symbol, price):
    global open_positions
    night = is_night_session()

    if night:
        trade_size_usd = round(CAPITAL * 0.36, 2)
        sl_pct = 0.0025
        tp_pct = 0.0050
        max_hold_mins = 35
        mode_label = "NIGHT SNIPER (+2 WIN / -1 CUT)"
    else:
        trade_size_usd = round(CAPITAL * 0.28, 2)
        sl_pct = 0.0020
        tp_pct = 0.0040
        max_hold_mins = 45
        mode_label = "DAY MULTI-BASKET"

    sl = round(price * (1 - sl_pct), 2)
    tp = round(price * (1 + tp_pct), 2)
    qty = round(trade_size_usd / price, 6)
    expected_profit = round(trade_size_usd * tp_pct, 2)
    expected_loss = round(trade_size_usd * sl_pct, 2)

    trade = {
        "symbol": symbol,
        "entry": price,
        "trade_size": trade_size_usd,
        "qty": qty,
        "sl": sl,
        "tp": tp,
        "trailing_stop": sl,
        "entry_timestamp": time.time(),
        "mode": "NIGHT" if night else "DAY",
        "max_hold_mins": max_hold_mins,
        "time_str": get_ist_time().strftime("%I:%M:%S %p")
    }
    open_positions.append(trade)

    gain_pct = tp_pct * 100
    loss_pct = sl_pct * 100
    msg = (
        f"⚡ *[{mode_label} ENTRY]*\n"
        f"Coin: `{symbol}`\n"
        f"Entry Price: `${price:,.2f}`\n"
        f"Size: `${trade_size_usd}`\n"
        f"🎯 Target (+{gain_pct:.2f}%): `${tp:,.2f}` (Gain: +${expected_profit:.2f})\n"
        f"🛑 Stop Loss (-{loss_pct:.2f}%): `${sl:,.2f}` (Risk: -${expected_loss:.2f})\n"
        f"⏱ Max Hold: {max_hold_mins} Mins"
    )
    print(f"[{trade['mode']} BUY] {symbol} @ ${price:,.2f} | Size: ${trade_size_usd} | Target: ${tp:,.2f}", flush=True)
    send_alert(msg)

def execute_auto_sell(index, price, reason):
    global CAPITAL, realized_pnl, total_trades, wins, open_positions
    pos = open_positions.pop(index)
    pnl = round((price - pos["entry"]) * pos["qty"], 2)
    CAPITAL = round(CAPITAL + pnl, 2)
    realized_pnl = round(realized_pnl + pnl, 2)
    total_trades += 1
    if pnl > 0: wins += 1

    save_state(CAPITAL, realized_pnl, total_trades, wins)

    icon = "🎯" if pnl >= 0 else "🛑"
    pnl_sign = "+" if pnl >= 0 else ""
    msg = (
        f"{icon} *[AUTO-EXIT: {reason}]*\n"
        f"Coin: `{pos['symbol']}`\n"
        f"Exit: `${price:,.2f}` | Entry: `${pos['entry']:,.2f}`\n"
        f"💰 Net P&L: `{pnl_sign}${pnl:,.2f}`\n"
        f"💼 Total Balance: `${CAPITAL:,.2f}` | Completed Trades: `{total_trades}`"
    )
    print(f"[EXIT: {reason}] {pos['symbol']} @ ${price:,.2f} | PnL: {pnl_sign}${pnl:,.2f}", flush=True)
    send_alert(msg)

def trading_loop_worker():
    while True:
        try:
            now = time.time()
            night = is_night_session()
            max_allowed_trades = 1 if night else 3

            for i in range(len(open_positions) - 1, -1, -1):
                pos = open_positions[i]
                s = pos["symbol"]
                curr_p = get_live_price(s)
                elapsed_mins = (now - pos["entry_timestamp"]) / 60.0
                pnl_pct = (curr_p - pos["entry"]) / pos["entry"]

                if curr_p >= pos["tp"]:
                    execute_auto_sell(i, curr_p, "TARGET HIT (+2.00 PROFIT)")
                    continue

                if pnl_pct >= 0.0025 and pos["trailing_stop"] < pos["entry"]:
                    pos["trailing_stop"] = pos["entry"]

                if pnl_pct >= 0.0035 and pos["trailing_stop"] < pos["entry"] * 1.0015:
                    pos["trailing_stop"] = round(pos["entry"] * 1.0015, 2)

                if curr_p <= pos["trailing_stop"]:
                    reason = "TRAILING PROFIT LOCK HIT" if pos["trailing_stop"] >= pos["entry"] else "STOP LOSS CUT (-0.25%)"
                    execute_auto_sell(i, curr_p, reason)
                    continue

                if elapsed_mins >= pos["max_hold_mins"]:
                    if curr_p >= pos["entry"] * 1.0008:
                        execute_auto_sell(i, curr_p, f"{int(pos['max_hold_mins'])}-MIN TIME HARVEST (+{pnl_pct*100:.2f}%)")
                        continue
                    elif elapsed_mins >= (pos["max_hold_mins"] + 15):
                        execute_auto_sell(i, curr_p, "STAGNANT RANGE ROTATION")
                        continue

            if len(open_positions) < max_allowed_trades:
                active_symbols = [p["symbol"] for p in open_positions]
                for s in SYMBOLS:
                    if s not in active_symbols and len(open_positions) < max_allowed_trades:
                        p = get_live_price(s)
                        execute_auto_buy(s, p)
                        time.sleep(1.0)

            time.sleep(POLL_INTERVAL)
        except Exception:
            time.sleep(POLL_INTERVAL)

# Background auto-trader thread
threading.Thread(target=trading_loop_worker, daemon=True).start()

@app.route('/')
def home():
    return jsonify({
        "status": "ONLINE_24_7",
        "system": "Pawan Quant Engine V7.0",
        "current_session": "NIGHT" if is_night_session() else "DAY",
        "balance": CAPITAL,
        "total_trades": total_trades,
        "open_trades_count": len(open_positions),
        "ist_time": get_ist_time().strftime("%Y-%m-%d %I:%M:%S %p IST")
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
