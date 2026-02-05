#!/usr/bin/env python3
import math
import time
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, Any
import requests
from requests.adapters import HTTPAdapter, Retry
import config
from utils import sma, ema, rsi, atr

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL*")

SAFETY_LAG_SECONDS = 180
MIN_VOLUME_USDC = {"WPOL": 1500.0, "WETH": 5000.0}
MIN_TVL_USD = {"WPOL": 200_000.0, "WETH": 500_000.0}
MIN_TREND_SEPARATION = 0.001
EMA_FAST, EMA_SLOW, RSI_PERIOD, ATR_PERIOD, VOL_MA_PERIOD = 16, 60, 14, 14, 24
RSI_BUY_THRESHOLD, RSI_SELL_THRESHOLD = 50, 50

QUERY_PAGED = """
query ($pools: [String!]!, $from:Int!, $first:Int!, $skip:Int!) {
  _meta { block { number timestamp } hasIndexingErrors }
  poolHourDatas(
    first: $first skip: $skip orderBy: periodStartUnix orderDirection: asc
    where: { pool_in: $pools, periodStartUnix_gte: $from }
  ) {
    pool { id feeTier token0 { symbol } token1 { symbol } }
    periodStartUnix token0Price token1Price
    open high low close volumeToken0 volumeToken1 volumeUSD tvlUSD txCount
  }
}
"""

def safe_float(x) -> float:
    try: return float(x)
    except: return float("nan")

def inv(x: float) -> float:
    return 1.0 / x if x != 0 and math.isfinite(x) else float("nan")

def fetch_pool_hour_data_paged(hours_lookback: int) -> Dict[str, Any]:
    now = int(time.time())
    from_ts = (now - hours_lookback * 3600) // 3600 * 3600
    session = requests.Session()
    retries = Retry(total=6, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    all_rows, skip = [], 0
    for _ in range(20):
        variables = {"pools": config.POOLS, "from": from_ts, "first": 1000, "skip": skip}
        resp = session.post(config.ENDPOINT, json={"query": QUERY_PAGED, "variables": variables}, timeout=30)
        js = resp.json()
        if "errors" in js: raise RuntimeError(f"GQL Error: {js['errors']}")
        data = js["data"]
        meta_out = data["_meta"]
        rows = data.get("poolHourDatas", [])
        all_rows.extend(rows)
        if len(rows) < 1000: break
        skip += 1000
    return {"data": {"_meta": meta_out, "poolHourDatas": all_rows}}

def normalize_row(row: Dict) -> Optional[Tuple[str, Dict]]:
    pool = row["pool"]
    t0, t1 = pool["token0"]["symbol"], pool["token1"]["symbol"]
    ts, feeTier = int(row["periodStartUnix"]), int(pool["feeTier"])
    o, h, l, c = safe_float(row["open"]), safe_float(row["high"]), safe_float(row["low"]), safe_float(row["close"])
    vol_usd, tvl, tx = safe_float(row["volumeUSD"]), safe_float(row["tvlUSD"]), int(row["txCount"])
    if t1 == "USDC":
        asset = t0
        o, c, h, l = inv(o), inv(c), inv(l), inv(h)
        return asset, {"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume_usdc": vol_usd, "txCount": tx, "tvlUSD": tvl, "feeTier": feeTier}
    if t0 == "USDC":
        asset = t1
        return asset, {"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume_usdc": vol_usd, "txCount": tx, "tvlUSD": tvl, "feeTier": feeTier}
    return None

def generate_signal_at(asset: str, candles: List[Dict], idx: int, ef, es, r14, a14, vm, mt_s, r_b, r_s) -> Tuple[str, str]:
    if idx < 60: return "HOLD", "short history"
    last = candles[idx]
    if last["tvlUSD"] < MIN_TVL_USD.get(asset, 0) or last["volume_usdc"] < MIN_VOLUME_USDC.get(asset, 0): return "HOLD", "low liq"
    sep = abs(ef[idx] - es[idx]) / last["close"]
    if sep < mt_s: return "HOLD", "weak trend"
    up, down = ef[idx] > es[idx], ef[idx] < es[idx]
    r_now, r_prev = r14[idx], r14[idx-1]
    vol_spike = last["volume_usdc"] > vm[idx] * 1.1
    if up and r_prev < r_b <= r_now and vol_spike: return "BUY", "up+RSI+Vol"
    if down and r_prev > r_s >= r_now and vol_spike: return "SELL", "down+RSI+Vol"
    return "HOLD", "no setup"

def backtest_asset(asset: str, candles: List[Dict], ef_p=EMA_FAST, es_p=EMA_SLOW, r_p=RSI_PERIOD, a_p=ATR_PERIOD, v_p=VOL_MA_PERIOD, mt_s=MIN_TREND_SEPARATION, r_b=RSI_BUY_THRESHOLD, r_s=RSI_SELL_THRESHOLD) -> Dict[str, Any]:
    n = len(candles)
    if n < 120: return {"asset": asset, "trades_n": 0}
    highs, lows, closes = [c["high"] for c in candles], [c["low"] for c in candles], [c["close"] for c in candles]
    vols = [c["volume_usdc"] for c in candles]
    ef, es = ema(closes, ef_p), ema(closes, es_p)
    r14, a14, vm = rsi(closes, r_p), atr(highs, lows, closes, a_p), sma(vols, v_p)
    trades = []
    for idx in range(0, n - 1):
        sig, reason = generate_signal_at(asset, candles, idx, ef, es, r14, a14, vm, mt_s, r_b, r_s)
        if sig not in ("BUY", "SELL"): continue
        e_c = candles[idx + 1]
        ret = (e_c["close"] / e_c["open"] - 1.0) if sig == "BUY" else (e_c["open"] / e_c["close"] - 1.0)
        ret_net = ret - (2.0 * e_c["feeTier"] / 1000000.0)
        trades.append({"ret_net": ret_net})
    if not trades: return {"asset": asset, "trades_n": 0, "win_rate": 0.0, "total_ret_net": 0.0}
    wins, equity = sum(1 for t in trades if t["ret_net"] > 0), 1.0
    for t in trades: equity *= (1.0 + t["ret_net"])
    return {"asset": asset, "trades_n": len(trades), "win_rate": wins / len(trades), "total_ret_net": equity - 1.0}

def build_series(js):
    meta = js["data"]["_meta"]
    grouped = defaultdict(list)
    for row in js["data"]["poolHourDatas"]:
        out = normalize_row(row)
        if out: grouped[out[0]].append(out[1])
    for a in grouped:
        grouped[a].sort(key=lambda x: x["ts"])
        grouped[a] = [c for c in grouped[a] if (c["ts"] + 3600) <= (int(meta["block"]["timestamp"]) - SAFETY_LAG_SECONDS)]
    return grouped

def main():
    js = fetch_pool_hour_data_paged(24 * 90)
    grouped = build_series(js)
    for asset in config.ASSETS:
        s = grouped.get(asset, [])
        if s:
            stats = backtest_asset(asset, s)
            print(f"{asset}: trades={stats['trades_n']} | win_rate={stats.get('win_rate',0)*100:.2f}% | total_ret_net={stats.get('total_ret_net',0)*100:.2f}%")

if __name__ == "__main__":
    main()
