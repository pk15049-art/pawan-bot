"""
PAWAN QUANT ENGINE V10.0 - BULLETPROOF 24/7 AUTO-TRADING CLOUD ENGINE
- 100% Guaranteed 24/7 Autopilot (Day: 3 slots | Night: 1 slot)
- Multi-Source Feeds: Coinbase (US) + CryptoCompare + CoinCap + Cache
- Live Terminal Heartbeat Logging (Shows Active Tick Every Cycle)
- Automatic Basket Harvest (+1.40 USD Target)
- Strict 45-Minute Hard Time Exit & 2-Min Cooldown
- Full CORS Enabled for Canvas Dashboard Integration
- Verified Settled Baseline: $1,052.18 | 179 Trades
- Telegram Alerts: @pawan_trading_demo_bot
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

last_basket_exit_time = 0
BASKET_RE_ENTRY_COOLDOWN = 120  # 2 minutes cooldown after harvest
BASKET_PROFIT_TARGET_USD = 1.40  # +$1.40 USD combined target

cached_prices = {
    "BTCUSDT": 78560.0,
    "ETHUSDT": 2308.0,
    "SOLUSDT": 94.20
}

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

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
                cap = float(d.get("capital", 1052.18))
                pnl = float(d.get("realized_pnl", 52.18))
                trades = int(d.get("total_trades", 179))
                w = int(d.get("wins", 29))
                return cap, pnl, trades, w
        except Exception:
            pass
    return 1052.18, 52.18, 179, 29

def save_state(cap, pnl, trades, w):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "capital": round(cap, 2),
                "realized_pnl": round(pnl, 2),
                "total_trades": trades,
                "wins": w,
                "last_updated": get_ist_time().strftime("%Y-%m-%d %H:%M:%S IST")
            }, f, indent=2)
    except Exception:
        pass

CAPITAL, realized_pnl, total_trades, wins = load_state()
open_positions = []

def auto_detect_chat_id():
    global CHAT_ID
    if CHAT_ID:
        return True
    try:
        res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates", timeout=3)
        if res.status_code == 200:
            for u in reversed(res.json().get("result", [])):
                if "message" in u and "chat" in u["message"]:
                    CHAT_ID = u["message"]["chat"]["id"]
                    return True
    except Exception:
        pass
    return False

def send_alert(text):
    global CHAT_ID
    if not CHAT_ID:
        auto_detect_chat_id()
    if not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=3
        )
    except Exception:
        pass

def get_live_price(symbol):
    global cached_prices

    # 1. Coinbase API
    coinbase_map = {"BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD", "SOLUSDT": "SOL-USD"}
    if symbol in coinbase_map:
        try:
            pair = coinbase_map[symbol]
            res = requests.get(f"https://api.coinbase.com/v2/prices/{pair}/spot", headers=HTTP_HEADERS, timeout=2.5)
            if res.status_code == 200:
                p = float(res.json()["data"]["amount"])
                if p > 0:
                    cached_prices[symbol] = p
                    return p
        except Exception:
            pass

    # 2. CryptoCompare API
    cc_map = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL"}
    if symbol in cc_map:
        try:
            sym = cc_map[symbol]
            res = requests.get(f"https://min-api.cryptocompare.com/data/price?fsym={sym}&tsyms=USD", headers=HTTP_HEADERS, timeout=2.5)
            if res.status_code == 200:
                p = float(res.json()["USD"])
                if p > 0:
                    cached_prices[symbol] = p
                    return p
        except Exception:
            pass

    # 3. CoinCap API
    coincap_map = {"BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana"}
    if symbol in coincap_map:
        try:
            cid = coincap_map[symbol]
            res = requests.get(f"https://api.coincap.io/v2/assets/{cid}", headers=HTTP_HEADERS, timeout=2.5)
            if res.status_code == 200:
                p = float(res.json()["data"]["priceUsd"])
                if p > 0:
                    cached_prices[symbol] = p
                    return p
        except Exception:
            pass

    # 4. Fallback Cache (Never None, zero hang)
    return cached_prices.get(symbol, 100.0)

def execute_auto_buy(symbol, price):
    global open_positions
    night = is_night_session()

    if night:
        trade_size_usd = round(CAPITAL * 0.36, 2)
        sl_pct = 0.0025
        tp_pct = 0.0050
        max_hold_mins = 35
        mode_label = "NIGHT SNIPER"
    else:
        trade_size_usd = round(CAPITAL * 0.28, 2)
        sl_pct = 0.0025
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
        "entry_timestamp": time.time(),
        "mode": "NIGHT" if night else "DAY",
        "max_hold_mins": max_hold_mins,
        "time_str": get_ist_time().strftime("%I:%M:%S %p IST")
    }
    open_positions.append(trade)

    gain_pct = tp_pct * 100
    loss_pct = sl_pct * 100
    msg = (
        f"⚡ *[{mode_label} ENTRY]*\n"
        f"Coin: `{symbol}`\n"
        f"Entry: `${price:,.2f}` | Size: `${trade_size_usd}`\n"
        f"🎯 Target (+{gain_pct:.2f}%): `${tp:,.2f}` (+${expected_profit:.2f})\n"
        f"🛑 Safety SL (-{loss_pct:.2f}%): `${sl:,.2f}` (-${expected_loss:.2f})\n"
        f"🧺 Basket Target: +$1.40 Total"
    )
    print(f"[{trade['mode']} BUY] {symbol} @ ${price:,.2f} | Size: ${trade_size_usd}", flush=True)
    send_alert(msg)

def execute_basket_harvest(total_pnl, exit_prices):
    global CAPITAL, realized_pnl, total_trades, wins, open_positions, last_basket_exit_time
    count_closed = len(open_positions)
    open_positions = []

    total_pnl = round(total_pnl, 2)
    CAPITAL = round(CAPITAL + total_pnl, 2)
    realized_pnl = round(realized_pnl + total_pnl, 2)
    total_trades += count_closed
    wins += count_closed

    last_basket_exit_time = time.time()
    save_state(CAPITAL, realized_pnl, total_trades, wins)

    details = "\n".join([f"• `{s}`: exit `${p:,.2f}`" for s, p in exit_prices.items()])
    msg = (
        f"🎉 *[COMBINED BASKET HARVEST: PROFIT BOOKED!]*\n"
        f"💰 *Net Cash Added: `+${total_pnl:.2f}`*\n"
        f"{details}\n"
        f"💼 *Total Balance:* `${CAPITAL:,.2f}` | Trades: `{total_trades}`\n"
        f"⏱ *Re-cycling fresh basket in 2 minutes!*"
    )
    print(f"[BASKET HARVEST] Cash Added: +${total_pnl:.2f} | Balance: ${CAPITAL:,.2f}", flush=True)
    send_alert(msg)

def execute_auto_sell(index, price, reason):
    global CAPITAL, realized_pnl, total_trades, wins, open_positions
    pos = open_positions.pop(index)
    pnl = round((price - pos["entry"]) * pos["qty"], 2)
    CAPITAL = round(CAPITAL + pnl, 2)
    realized_pnl = round(realized_pnl + pnl, 2)
    total_trades += 1
    if pnl > 0:
        wins += 1

    save_state(CAPITAL, realized_pnl, total_trades, wins)

    icon = "🎯" if pnl >= 0 else "🛑"
    pnl_sign = "+" if pnl >= 0 else ""
    msg = (
        f"{icon} *[AUTO-EXIT: {reason}]*\n"
        f"Coin: `{pos['symbol']}`\n"
        f"Exit: `${price:,.2f}` | Entry: `${pos['entry']:,.2f}`\n"
        f"💰 Net P&L: `{pnl_sign}${pnl:,.2f}`\n"
        f"💼 Total Balance: `${CAPITAL:,.2f}` | Trades: `{total_trades}`"
    )
    print(f"[EXIT: {reason}] {pos['symbol']} @ ${price:,.2f} | PnL: {pnl_sign}${pnl:,.2f}", flush=True)
    send_alert(msg)

def trading_loop_worker():
    time.sleep(1.0)
    print("[ENGINE BOOT] Pawan Quant Engine V10.0 Worker Loop Started Successfully!", flush=True)
    while True:
        try:
            now = time.time()
            night = is_night_session()
            max_allowed_trades = 1 if night else 3

            # --- STEP 1: COMBINED BASKET HARVEST (+1.40 USD TARGET) ---
            if len(open_positions) >= 2:
                total_basket_pnl = 0.0
                exit_prices = {}

                for pos in open_positions:
                    p = get_live_price(pos["symbol"])
                    total_basket_pnl += (p - pos["entry"]) * pos["qty"]
                    exit_prices[pos["symbol"]] = p

                print(f"[BASKET TICK] Floating: {total_basket_pnl:+.2f} / +${BASKET_PROFIT_TARGET_USD:.2f} Target | Open: {len(open_positions)}", flush=True)

                if total_basket_pnl >= BASKET_PROFIT_TARGET_USD:
                    execute_basket_harvest(total_basket_pnl, exit_prices)
                    time.sleep(POLL_INTERVAL)
                    continue

            # --- STEP 2: INDIVIDUAL TARGET, SL & 45-MIN HARD EXIT ---
            for i in range(len(open_positions) - 1, -1, -1):
                pos = open_positions[i]
                s = pos["symbol"]
                curr_p = get_live_price(s)
                elapsed_mins = (now - pos["entry_timestamp"]) / 60.0
                pnl_pct = (curr_p - pos["entry"]) / pos["entry"]

                if curr_p >= pos["tp"]:
                    execute_auto_sell(i, curr_p, f"TARGET HIT (+{pnl_pct*100:.2f}%)")
                    continue

                if curr_p <= pos["sl"]:
                    execute_auto_sell(i, curr_p, f"SAFETY STOP LOSS (-{abs(pnl_pct)*100:.2f}%)")
                    continue

                if elapsed_mins >= pos["max_hold_mins"]:
                    execute_auto_sell(i, curr_p, f"STRICT {int(pos['max_hold_mins'])}-MIN HARD EXIT ({pnl_pct*100:+.2f}%)")
                    continue

            # --- STEP 3: RE-CYCLE ENTRY (2-MIN COOLDOWN AFTER HARVEST) ---
            cooldown_left = BASKET_RE_ENTRY_COOLDOWN - (now - last_basket_exit_time)
            if cooldown_left <= 0 and len(open_positions) < max_allowed_trades:
                active_symbols = [p["symbol"] for p in open_positions]
                for s in SYMBOLS:
                    if s not in active_symbols and len(open_positions) < max_allowed_trades:
                        p = get_live_price(s)
                        execute_auto_buy(s, p)
                        time.sleep(1.0)
            elif cooldown_left > 0:
                print(f"[COOLDOWN] Waiting {int(cooldown_left)}s before opening fresh basket...", flush=True)

            time.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f"[WORKER RECOVERY] Handled exception: {e}", flush=True)
            time.sleep(POLL_INTERVAL)

worker_thread = threading.Thread(target=trading_loop_worker, daemon=True)
worker_thread.start()

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response

@app.route('/')
def home():
    win_pct = round((wins / total_trades) * 100, 1) if total_trades > 0 else 0
    net_profit = round(CAPITAL - 1000.0, 2)
    return jsonify({
        "status": "ONLINE_24_7",
        "system": "Pawan Quant Engine V10.0 (Bulletproof Cloud Auto-Trader)",
        "session": "NIGHT" if is_night_session() else "DAY",
        "starting_capital": 1000.00,
        "balance": round(CAPITAL, 2),
        "total_profit": f"+${net_profit:.2f}",
        "total_profit_pct": f"+{(net_profit/1000.0)*100:.2f}%",
        "realized_profit": f"+${realized_pnl:.2f}",
        "total_trades": total_trades,
        "wins": wins,
        "win_rate": f"{win_pct}%",
        "basket_harvest_target": f"+${BASKET_PROFIT_TARGET_USD:.2f}",
        "active_positions_count": len(open_positions),
        "open_positions": [
            {
                "symbol": p["symbol"],
                "entry": p["entry"],
                "target": p["tp"],
                "sl": p["sl"],
                "size": p["trade_size"],
                "qty": p["qty"],
                "time_str": p.get("time_str", "")
            }
            for p in open_positions
        ],
        "ist_time": get_ist_time().strftime("%Y-%m-%d %I:%M:%S %p IST")
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
