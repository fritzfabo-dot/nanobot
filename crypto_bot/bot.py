#!/usr/bin/env python3
import os
import json
import time
import requests
from datetime import datetime
import config
from strategy_signal import fetch_data, normalize, get_signal
from execute_trade import Trader

DATA_DIR = "/app/crypto_bot/data"
ACTIVE_TRADES_FILE = os.path.join(DATA_DIR, "active_trades.json")

# Prefer repository workspace if available
if os.path.exists("/app/workspace"):
    WORKSPACE_DIR = "/app/workspace"
else:
    WORKSPACE_DIR = os.path.expanduser("~/.nanobot/workspace")

TOKEN_MAP = {
    "WPOL": config.WPOL,
    "WETH": config.WETH
}

def get_nanobot_config():
    config_path = os.path.expanduser("~/.nanobot/config.json")
    if os.path.exists(config_path):
        with open(config_path, 'r') as f: return json.load(f)
    return {}

def log_to_memory(message, is_trade_result=False):
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    daily_file = os.path.join(WORKSPACE_DIR, "memory", f"{date_str}.md")

    os.makedirs(os.path.dirname(daily_file), exist_ok=True)
    with open(daily_file, 'a') as f:
        f.write(f"[{now.strftime('%H:%M:%S')}] {message}\n")

    if is_trade_result:
        # Update long-term memory summary
        memory_md = os.path.join(WORKSPACE_DIR, "memory", "MEMORY.md")
        if os.path.exists(memory_md):
            with open(memory_md, 'r') as f: content = f.read()
            if "## Trading History" not in content:
                content += "\n\n## Trading History\n\n"
            content += f"- {now.strftime('%Y-%m-%d %H:%M')}: {message}\n"
            with open(memory_md, 'w') as f: f.write(content)

def notify(message, is_important=False):
    print(f"NOTIFICATION: {message}")
    log_to_memory(message, is_trade_result=is_important)

    nb_config = get_nanobot_config()
    telegram = nb_config.get("channels", {}).get("telegram", {})
    if telegram.get("enabled") and telegram.get("token"):
        token = telegram["token"]
        for user_id in telegram.get("allowFrom", []):
            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                payload = {"chat_id": user_id, "text": f"🤖 CryptoBot: {message}"}
                requests.post(url, json=payload, timeout=10)
            except Exception as e:
                print(f"Failed to send Telegram message: {e}")

def run_bot():
    log_to_memory("Bot started: checking market opportunities.")
    active_trades = load_active_trades()
    now = time.time()

    # 1. Check for trades to close
    remaining_trades = []
    for trade in active_trades:
        if now - trade['entry_ts'] >= 3600:
            notify(f"Closing trade for {trade['asset']} after 1 hour.")
            if config.POLYGON_RPC_URL and config.PRIVATE_KEY:
                trader = Trader(config.POLYGON_RPC_URL, config.PRIVATE_KEY)
                token_addr = TOKEN_MAP.get(trade['asset'])
                amount = trader.get_balance(token_addr)
                if amount > 0:
                    try:
                        trader.swap(token_addr, config.USDC, amount)
                        notify(f"SUCCESS: Swapped back {trade['asset']} to USDC.", is_important=True)
                    except Exception as e:
                        notify(f"ERROR: Failed to close trade for {trade['asset']}: {e}")
            else:
                try:
                    data = fetch_data()
                    rows = data["data"]["poolHourDatas"]
                    current_price = next((normalize(r)[1]['close'] for r in rows if normalize(r) and normalize(r)[0] == trade['asset']), None)
                    if current_price:
                        pnl = (current_price / trade['price'] - 1) * 100
                        notify(f"[DRY RUN] Closed {trade['asset']} at {current_price:.6f}. Est. PnL: {pnl:.2f}%", is_important=True)
                    else:
                        notify(f"[DRY RUN] Closed {trade['asset']}. Price unavailable.", is_important=True)
                except:
                    notify(f"[DRY RUN] Closed {trade['asset']}.", is_important=True)
        else:
            remaining_trades.append(trade)

    # 2. Check for new opportunities
    try:
        data = fetch_data()
        meta = data["data"]["_meta"]
        rows = data["data"]["poolHourDatas"]
        grouped = {}
        for r in rows:
            n = normalize(r)
            if n:
                if n[0] not in grouped: grouped[n[0]] = []
                grouped[n[0]].append(n[1])

        for asset in config.ASSETS:
            series = grouped.get(asset, [])
            if not series: continue
            series.sort(key=lambda x: x['ts'])
            series = [c for c in series if (c['ts'] + 3600) <= (int(meta['block']['timestamp']) - 180)]

            sig, reason = get_signal(asset, series)
            if sig == "BUY":
                if any(t['asset'] == asset for t in remaining_trades): continue

                notify(f"OPPORTUNITY: BUY {asset} because {reason}")
                if config.POLYGON_RPC_URL and config.PRIVATE_KEY:
                    trader = Trader(config.POLYGON_RPC_URL, config.PRIVATE_KEY)
                    usdc_balance = trader.get_balance(config.USDC)
                    trade_amount = int(usdc_balance * config.USDC_PER_TRADE_PERCENT)
                    if trade_amount > 1000000:
                        try:
                            trader.swap(config.USDC, TOKEN_MAP[asset], trade_amount, expected_price=series[-1]['close'])
                            remaining_trades.append({'asset': asset, 'entry_ts': now, 'price': series[-1]['close']})
                            notify(f"EXECUTED: BUY {asset} at {series[-1]['close']:.6f}.", is_important=True)
                        except Exception as e:
                            notify(f"FAILED: BUY {asset}: {e}")
                    else:
                        notify(f"SKIPPED: Insufficient USDC for {asset}.")
                else:
                    notify(f"[DRY RUN] Executing BUY for {asset} at {series[-1]['close']:.6f}.", is_important=True)
                    remaining_trades.append({'asset': asset, 'entry_ts': now, 'price': series[-1]['close']})
    except Exception as e:
        notify(f"SIGNAL ERROR: {e}")

    save_active_trades(remaining_trades)

def load_active_trades():
    if os.path.exists(ACTIVE_TRADES_FILE):
        with open(ACTIVE_TRADES_FILE, 'r') as f: return json.load(f)
    return []

def save_active_trades(trades):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ACTIVE_TRADES_FILE, 'w') as f: json.dump(trades, f)

if __name__ == "__main__":
    run_bot()
