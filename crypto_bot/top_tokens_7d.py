#!/usr/bin/env python3
"""
top_tokens_7d.py — Discover top tradable tokens vs *native* USDC on Uniswap V3 Polygon via The Graph

What it does:
- Uses last 7 COMPLETE days (yesterday back 6 days), UTC day boundaries
- Fetches poolDayDatas for pools where native USDC is token0 and where native USDC is token1
- Aggregates 7d volumeUSD per pool and tracks latest tvlUSD in that window
- Filters for reliability (volume + tvl)
- EXCLUDES "USDC/USDC" (native USDC vs bridged USDC.e) so you don't trade stable->stable
- Produces:
  1) Top pools by 7d volume
  2) Top tokens vs native USDC (best pool per token)
  3) Ready-to-paste POOLS list (direct market discovery venues)

Deps:
  pip install requests
"""

import time
import math
import warnings
from collections import defaultdict
from typing import Dict, Any, List, Tuple

import requests
from requests.adapters import HTTPAdapter, Retry

# Optional: silence LibreSSL warning on some macOS builds
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL*")

import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SUBGRAPH_API_KEY")
SUBGRAPH_ID = "3hCPRGf4z88VC5rsBKU5AA9FBBq5nF3jbKJG7VZCbhjm"
ENDPOINT = f"https://gateway-arbitrum.network.thegraph.com/api/{API_KEY}/subgraphs/id/{SUBGRAPH_ID}"

# Native USDC (Polygon) — this is your trading quote asset
USDC_NATIVE = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359".lower()

# Bridged USDC (commonly USDC.e on Polygon) seen in your output.
# We exclude any pool where both sides are "USDC variants", and we never select USDC as a tradable "other token".
USDC_BRIDGED = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174".lower()

USDC_VARIANTS = {USDC_NATIVE, USDC_BRIDGED}

# ---- Reliability knobs ----
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 25
RETRY_TOTAL = 6
BACKOFF_FACTOR = 1
PAGE_SIZE = 1000

# ---- Output / ranking knobs ----
TOP_N_TOKENS = 10         # how many tokens you want in final output + POOLS list
TOP_N_POOLS_DEBUG = 15    # extra debug list of pools

# ---- Quality gates (tune for your needs) ----
# If you want more tokens, lower these; if you want only "big venues", raise these.
MIN_7D_VOLUME_USD = 50_000.0
MIN_LATEST_TVL_USD = 100_000.0

QUERY_USDC_TOKEN0 = """
query($days:[Int!]!, $usdc:String!, $first:Int!, $skip:Int!) {
  _meta { block { number timestamp } hasIndexingErrors }

  poolDayDatas(
    first: $first
    skip: $skip
    orderBy: id
    orderDirection: asc
    where: {
      date_in: $days
      pool_: { token0: $usdc }
    }
  ) {
    id
    date
    volumeUSD
    tvlUSD
    pool {
      id
      feeTier
      token0 { id symbol decimals }
      token1 { id symbol decimals }
    }
  }
}
"""

QUERY_USDC_TOKEN1 = """
query($days:[Int!]!, $usdc:String!, $first:Int!, $skip:Int!) {
  _meta { block { number timestamp } hasIndexingErrors }

  poolDayDatas(
    first: $first
    skip: $skip
    orderBy: id
    orderDirection: asc
    where: {
      date_in: $days
      pool_: { token1: $usdc }
    }
  ) {
    id
    date
    volumeUSD
    tvlUSD
    pool {
      id
      feeTier
      token0 { id symbol decimals }
      token1 { id symbol decimals }
    }
  }
}
"""


def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=RETRY_TOTAL,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def gql_post(session: requests.Session, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    r = session.post(
        ENDPOINT,
        json={"query": query, "variables": variables},
        headers={"Content-Type": "application/json"},
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
    )
    r.raise_for_status()
    js = r.json()
    if "errors" in js and js["errors"]:
        raise RuntimeError(f"GraphQL errors: {js['errors']}")
    if "data" not in js or js["data"] is None:
        raise RuntimeError(f"Empty data: {js}")
    return js


def compute_last_7_complete_days() -> List[int]:
    # yesterday 00:00 UTC, then back 6 more days
    now = int(time.time())
    yday = now - (now % 86400) - 86400
    return [yday - i * 86400 for i in range(0, 7)]


def fetch_paged_pool_day_datas(query: str, days: List[int], usdc_addr: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    session = make_session()
    all_rows: List[Dict[str, Any]] = []
    meta_out: Dict[str, Any] = {}

    skip = 0
    while True:
        variables = {
            "days": days,
            "usdc": usdc_addr.lower(),
            "first": PAGE_SIZE,
            "skip": skip,
        }
        js = gql_post(session, query, variables)
        meta = js["data"]["_meta"]
        meta_out = meta

        if meta.get("hasIndexingErrors"):
            raise RuntimeError("Subgraph indexing error detected — do not use this data")

        rows = js["data"].get("poolDayDatas", []) or []
        all_rows.extend(rows)

        if len(rows) < PAGE_SIZE:
            break
        skip += PAGE_SIZE

    return meta_out, all_rows


def fnum(x) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else 0.0
    except Exception:
        return 0.0


def is_usdc_variant(token_addr: str, token_symbol: str) -> bool:
    # Address-based is most reliable; symbol-based helps if some variant isn't in USDC_VARIANTS
    if token_addr.lower() in USDC_VARIANTS:
        return True
    if (token_symbol or "").upper() == "USDC":
        return True
    return False


def main():
    days = compute_last_7_complete_days()
    days_sorted = sorted(days)
    start_day = days_sorted[0]
    end_day = days_sorted[-1]

    meta0, rows0 = fetch_paged_pool_day_datas(QUERY_USDC_TOKEN0, days, USDC_NATIVE)
    meta1, rows1 = fetch_paged_pool_day_datas(QUERY_USDC_TOKEN1, days, USDC_NATIVE)

    # Keep the later meta (by block number)
    meta = meta1 if int(meta1["block"]["number"]) >= int(meta0["block"]["number"]) else meta0

    rows = rows0 + rows1

    print("Latest block:", meta["block"])
    print(f"7D window (complete days): {start_day} → {end_day}  (unix day starts, UTC)")
    print(f"Fetched {len(rows)} poolDayDatas rows (raw)")

    # Aggregate by pool over the 7 days
    pool_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "pool": None,
        "volume7d": 0.0,
        "latest_date": 0,
        "latest_tvlUSD": 0.0,
    })

    for r in rows:
        pool = r["pool"]
        pool_id = pool["id"]
        date = int(r["date"])
        vol = fnum(r["volumeUSD"])
        tvl = fnum(r["tvlUSD"])

        st = pool_stats[pool_id]
        st["pool"] = pool
        st["volume7d"] += vol

        if date > st["latest_date"]:
            st["latest_date"] = date
            st["latest_tvlUSD"] = tvl

    # Filter pools:
    # 1) reliability gates: 7d volume and latest tvl
    # 2) exclude USDC-variant <-> USDC-variant pools (USDC/USDC)
    filtered_pools = []
    for st in pool_stats.values():
        p = st["pool"]
        if not p:
            continue

        if st["volume7d"] < MIN_7D_VOLUME_USD:
            continue
        if st["latest_tvlUSD"] < MIN_LATEST_TVL_USD:
            continue

        t0 = p["token0"]
        t1 = p["token1"]
        t0_is_usdc_var = is_usdc_variant(t0["id"], t0["symbol"])
        t1_is_usdc_var = is_usdc_variant(t1["id"], t1["symbol"])

        # Exclude stable "USDC/USDC" pools (native vs bridged)
        if t0_is_usdc_var and t1_is_usdc_var:
            continue

        filtered_pools.append(st)

    filtered_pools.sort(key=lambda s: s["volume7d"], reverse=True)

    print("\nTop pools (after filters):")
    for i, st in enumerate(filtered_pools[:TOP_N_POOLS_DEBUG], 1):
        p = st["pool"]
        t0 = p["token0"]["symbol"]
        t1 = p["token1"]["symbol"]
        fee = int(p["feeTier"])
        print(
            f"{i:02d}. {t0}/{t1} fee={fee:<5} "
            f"volume7dUSD={st['volume7d']:,.0f} "
            f"latest_tvlUSD={st['latest_tvlUSD']:,.0f} "
            f"pool={p['id']}"
        )

    # Best pool per TOKEN vs native USDC
    token_best: Dict[str, Dict[str, Any]] = {}

    for st in filtered_pools:
        p = st["pool"]
        t0 = p["token0"]
        t1 = p["token1"]

        # Identify the "other token" in a USDC(native) pool
        if t0["id"].lower() == USDC_NATIVE:
            other = t1
        elif t1["id"].lower() == USDC_NATIVE:
            other = t0
        else:
            # Shouldn't happen since we queried only pools where USDC_NATIVE is token0 or token1
            continue

        # Exclude any "other token" that is also a USDC variant (prevents USDC/USDC from appearing)
        if is_usdc_variant(other["id"], other["symbol"]):
            continue

        other_addr = other["id"].lower()
        cur = token_best.get(other_addr)
        if (cur is None) or (st["volume7d"] > cur["volume7d"]):
            token_best[other_addr] = {
                "symbol": other["symbol"],
                "token": other_addr,
                "best_pool": p["id"],
                "feeTier": int(p["feeTier"]),
                "pair": f'{t0["symbol"]}/{t1["symbol"]}',
                "volume7d": st["volume7d"],
                "latest_tvlUSD": st["latest_tvlUSD"],
            }

    top_tokens = sorted(token_best.values(), key=lambda x: x["volume7d"], reverse=True)

    print("\nTop tradable tokens vs USDC(native) (best pool per token, 7D volume):")
    for i, t in enumerate(top_tokens[:TOP_N_TOKENS], 1):
        print(
            f"{i:02d}. {t['symbol']:>10}  "
            f"volume7dUSD={t['volume7d']:,.0f}  "
            f"latest_tvlUSD={t['latest_tvlUSD']:,.0f}  "
            f"fee={t['feeTier']}  pair={t['pair']}  "
            f"pool={t['best_pool']}  token={t['token']}"
        )

    if not top_tokens:
        print("\nNo tokens passed the filters. Lower MIN_7D_VOLUME_USD / MIN_LATEST_TVL_USD and retry.")
        return

    # ---- Ready-to-paste POOLS list (Direct Market Discovery venues) ----
    pools_for_bot = [t["best_pool"] for t in top_tokens[:TOP_N_TOKENS]]

    print("\n# ---- READY TO PASTE ----")
    print("POOLS = [")
    for pid in pools_for_bot:
        print(f'  "{pid}",')
    print("]")

    # Also print a mapping so you know which pool corresponds to which token
    print("\nPOOL_INFO = {")
    for t in top_tokens[:TOP_N_TOKENS]:
        print(f'  "{t["symbol"]}": {{ "token": "{t["token"]}", "pool": "{t["best_pool"]}", "feeTier": {t["feeTier"]} }},')
    print("}")

if __name__ == "__main__":
    main()
