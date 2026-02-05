#!/usr/bin/env python3
import itertools
from typing import Dict, List, Any
from backtesting import fetch_pool_hour_data_paged, build_series, backtest_asset
import config

PARAM_GRID = {
    "ema_fast": [8, 12, 16, 20],
    "ema_slow": [30, 40, 50, 60, 80],
    "rsi_buy_threshold": [40, 45, 50],
    "rsi_sell_threshold": [50, 55, 60],
    "min_trend_sep": [0.001, 0.002, 0.003],
}

def run_optimization():
    print(f"Fetching data for {config.ASSETS}...")
    js = fetch_pool_hour_data_paged(24 * 90)
    grouped = build_series(js)
    combos = [dict(zip(PARAM_GRID.keys(), v)) for v in itertools.product(*PARAM_GRID.values())]
    print(f"Testing {len(combos)} combinations on WPOL...")
    results = []
    for params in combos:
        s = grouped.get("WPOL", [])
        stats = backtest_asset("WPOL", s, ef_p=params["ema_fast"], es_p=params["ema_slow"], r_b=params["rsi_buy_threshold"], r_s=params["rsi_sell_threshold"], mt_s=params["min_trend_sep"])
        if stats.get("trades_n", 0) > 20:
            results.append({"params": params, "total_net_ret": stats["total_ret_net"], "win_rate": stats["win_rate"], "trades": stats["trades_n"]})
    results.sort(key=lambda x: x["total_net_ret"], reverse=True)
    for rank, res in enumerate(results[:5], 1):
        p = res["params"]
        print(f"Rank {rank}: Net Ret={res['total_net_ret']*100:.2f}% | WR={res['win_rate']*100:.2f}% | Trades={res['trades']} | Params={p}")

if __name__ == "__main__":
    run_optimization()
