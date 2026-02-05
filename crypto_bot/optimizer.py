#!/usr/bin/env python3
"""
optimizer.py — Grid search optimization for MAXIMUM PROFIT on WPOL only.
"""

import itertools
import math
from typing import Dict, List, Any
from backtesting import (
    fetch_pool_hour_data_paged,
    build_series,
    backtest_asset,
    ASSETS,
    HOURS_LOOKBACK,
    utc_str,
)

# =========================
# Parameter Grid (WPOL Profit Focus)
# =========================

PARAM_GRID = {
    # WPOL can be volatile. Test fast reaction vs smoothing.
    "ema_fast": [8, 12, 16, 20],
    "ema_slow": [30, 40, 50, 60, 80],

    # RSI Period
    "rsi_period": [14],

    # Thresholds:
    # 50/50 = pure trend following
    # 45/55 = momentum with slight buffer
    # 40/60 = deeper pullback / mean reversion elements
    "rsi_buy_threshold": [40, 45, 50],
    "rsi_sell_threshold": [50, 55, 60],

    # Trend Filter
    "min_trend_sep": [0.001, 0.002, 0.003],

    # ATR period standard
    "atr_period": [14],
}

def get_combinations(grid: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    keys = list(grid.keys())
    values = list(grid.values())
    combinations = []
    for v in itertools.product(*values):
        combinations.append(dict(zip(keys, v)))
    return combinations

def run_optimization():
    print(f"Fetching data (90 days) for {ASSETS}...")
    try:
        js = fetch_pool_hour_data_paged(HOURS_LOOKBACK)
        grouped, info = build_series(js)
        print(f"Data fetched. Range: {HOURS_LOOKBACK} hours.")
    except Exception as e:
        print(f"Error fetching data: {e}")
        return

    # Generate combinations
    combos = [dict(zip(PARAM_GRID.keys(), v)) for v in itertools.product(*PARAM_GRID.values())]
    print(f"Testing {len(combos)} combinations on WPOL...")

    results = []

    for i, params in enumerate(combos):
        if i % 100 == 0:
            print(f"Processing {i}/{len(combos)}...", end="\r")

        # Run backtest for this combo on WPOL only
        asset = "WPOL"
        candles = grouped.get(asset, [])
        if len(candles) < 120:
            continue

        stats = backtest_asset(
            asset,
            candles,
            ema_fast_period=params["ema_fast"],
            ema_slow_period=params["ema_slow"],
            rsi_period=params["rsi_period"],
            atr_period=params["atr_period"],
            min_trend_sep=params["min_trend_sep"],
            rsi_buy_threshold=params["rsi_buy_threshold"],
            rsi_sell_threshold=params["rsi_sell_threshold"],
        )

        if "error" in stats:
            continue

        total_trades = stats["trades_n"]
        total_net_ret = stats["total_ret_net"]
        win_rate = stats["win_rate"]

        if total_trades == 0:
            continue

        # Strategy Constraints
        days = HOURS_LOOKBACK / 24.0
        trades_per_day = total_trades / days

        # Constraint: At least 0.25 signal per day (1 every 4 days)
        # Relaxed because we are only looking at ONE asset now.
        if trades_per_day < 0.25:
            continue

        results.append({
            "params": params,
            "total_trades": total_trades,
            "trades_per_day": trades_per_day,
            "total_net_ret": total_net_ret,
            "win_rate": win_rate,
        })

    print(f"\nOptimization complete. Found {len(results)} valid configurations.")

    if not results:
        print("No configuration met the criteria.")
        return

    # Sort by TOTAL NET RETURN (Profit Maximization)
    results.sort(key=lambda x: x["total_net_ret"], reverse=True)

    print("\nTop 5 PROFIT Configurations for WPOL:")
    print("=" * 80)
    for rank, res in enumerate(results[:5], 1):
        p = res["params"]
        print(f"Rank {rank}:")
        print(f"  Params: EMA={p['ema_fast']}/{p['ema_slow']} RSI={p['rsi_buy_threshold']}/{p['rsi_sell_threshold']} Sep={p['min_trend_sep']}")
        print(f"  Metrics: Net Ret={res['total_net_ret']*100:.2f}% | Win Rate={res['win_rate']*100:.2f}% | Trades={res['total_trades']}")
        print("-" * 40)

if __name__ == "__main__":
    run_optimization()
