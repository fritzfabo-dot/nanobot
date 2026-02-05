import math
from typing import List, Optional

def sma(values: List[float], period: int) -> List[float]:
    out = []
    for i in range(len(values)):
        start = max(0, i - period + 1)
        out.append(sum(values[start:i+1]) / (i - start + 1))
    return out

def ema(values: List[float], period: int) -> List[float]:
    k = 2.0 / (period + 1.0)
    out = []
    prev = None
    for v in values:
        if prev is None: prev = v
        else: prev = v * k + prev * (1.0 - k)
        out.append(prev)
    return out

def rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    if len(values) < period + 1: return [None] * len(values)
    out = [None] * len(values)
    gains, losses = [], []
    for i in range(1, period + 1):
        d = values[i] - values[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    avg_g, avg_l = sum(gains)/period, sum(losses)/period
    out[period] = 100.0 - (100.0 / (1.0 + avg_g/avg_l)) if avg_l != 0 else 100.0
    for i in range(period + 1, len(values)):
        d = values[i] - values[i-1]
        g, l = max(d, 0), max(-d, 0)
        avg_g = (avg_g * (period-1) + g) / period
        avg_l = (avg_l * (period-1) + l) / period
        out[i] = 100.0 - (100.0 / (1.0 + avg_g/avg_l)) if avg_l != 0 else 100.0
    return out

def atr(highs, lows, closes, period=14):
    n = len(closes)
    if n < period: return [None] * n
    trs = [0.0] * n
    for i in range(n):
        if i == 0: trs[i] = highs[i] - lows[i]
        else: trs[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    out = [None] * n
    first_atr_idx = period - 1
    out[first_atr_idx] = sum(trs[:period]) / period
    for i in range(first_atr_idx + 1, n): out[i] = (out[i - 1] * (period - 1) + trs[i]) / period
    return out
