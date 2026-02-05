#!/usr/bin/env python3
import math
import warnings
import requests
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
from requests.adapters import HTTPAdapter, Retry
import config
from utils import sma, ema, rsi

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL*")

QUERY = """
query ($pools: [String!]!) {
  _meta { block { number timestamp } hasIndexingErrors }
  poolHourDatas(
    first: 720
    orderBy: periodStartUnix
    orderDirection: desc
    where: { pool_in: $pools }
  ) {
    pool { id feeTier token0 { symbol } token1 { symbol } }
    periodStartUnix
    token0Price token1Price
    open high low close
    volumeToken0 volumeToken1 volumeUSD
    tvlUSD txCount
  }
}
"""

SAFETY_LAG_SECONDS = 180
MIN_VOLUME_USDC = {"WPOL": 1500.0, "WETH": 5000.0}
MIN_TVL_USD = {"WPOL": 200_000.0, "WETH": 500_000.0}
MIN_TREND_SEPARATION = 0.001
EMA_FAST, EMA_SLOW, RSI_PERIOD, VOL_MA_PERIOD = 16, 60, 14, 24
RSI_BUY_THRESHOLD, RSI_SELL_THRESHOLD = 50, 50

def utc_str(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def safe_float(x) -> float:
    try: return float(x)
    except: return float("nan")

def inv(x: float) -> float:
    return 1.0 / x if x != 0 and math.isfinite(x) else float("nan")

def fetch_data() -> Dict:
    s = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    r = s.post(config.ENDPOINT, json={"query": QUERY, "variables": {"pools": config.POOLS}}, timeout=30)
    r.raise_for_status()
    return r.json()

def normalize(row: Dict) -> Optional[Tuple[str, Dict]]:
    pool = row["pool"]
    t0, t1 = pool["token0"]["symbol"], pool["token1"]["symbol"]
    ts = int(row["periodStartUnix"])
    o, h, l, c = safe_float(row["open"]), safe_float(row["high"]), safe_float(row["low"]), safe_float(row["close"])
    vol_usd, tvl, tx = safe_float(row["volumeUSD"]), safe_float(row["tvlUSD"]), int(row["txCount"])
    if t1 == "USDC":
        asset = t0
        o, c, h, l = inv(o), inv(c), inv(l), inv(h)
        return asset, {"ts": ts, "close": c, "volume_usdc": vol_usd, "tvlUSD": tvl, "txCount": tx}
    if t0 == "USDC":
        asset = t1
        return asset, {"ts": ts, "close": c, "volume_usdc": vol_usd, "tvlUSD": tvl, "txCount": tx}
    return None

def get_signal(asset: str, series: List[Dict]) -> Tuple[str, str]:
    if len(series) < 60: return "HOLD", "short history"
    closes, vols = [c["close"] for c in series], [c["volume_usdc"] for c in series]
    ef, es, r, vm = ema(closes, EMA_FAST), ema(closes, EMA_SLOW), rsi(closes, RSI_PERIOD), sma(vols, VOL_MA_PERIOD)
    last = series[-1]
    if last["tvlUSD"] < MIN_TVL_USD.get(asset, 0) or last["volume_usdc"] < MIN_VOLUME_USDC.get(asset, 0): return "HOLD", "low liq/vol"
    sep = abs(ef[-1] - es[-1]) / closes[-1]
    if sep < MIN_TREND_SEPARATION: return "HOLD", f"weak trend {sep*100:.2f}%"
    up, down = ef[-1] > es[-1], ef[-1] < es[-1]
    r_now, r_prev = r[-1], r[-2]
    vol_spike = last["volume_usdc"] > vm[-1] * 1.1
    if up and r_prev < RSI_BUY_THRESHOLD <= r_now and vol_spike: return "BUY", f"up+RSI+Vol (RSI={r_now:.1f})"
    if down and r_prev > RSI_SELL_THRESHOLD >= r_now and vol_spike: return "SELL", f"down+RSI+Vol (RSI={r_now:.1f})"
    return "HOLD", f"no setup (RSI={r_now:.1f})"

def main():
    data = fetch_data()
    meta = data["data"]["_meta"]
    rows = data["data"]["poolHourDatas"]
    grouped = defaultdict(list)
    for r in rows:
        n = normalize(r)
        if n: grouped[n[0]].append(n[1])
    for a in grouped:
        grouped[a].sort(key=lambda x: x["ts"])
        grouped[a] = [c for c in grouped[a] if (c["ts"] + 3600) <= (int(meta["block"]["timestamp"]) - SAFETY_LAG_SECONDS)]
    for a in config.ASSETS:
        s = grouped.get(a, [])
        if not s: continue
        sig, reason = get_signal(a, s)
        print(f"{a}: {sig} | {reason} | price={s[-1]['close']:.6f}")

if __name__ == "__main__":
    main()
