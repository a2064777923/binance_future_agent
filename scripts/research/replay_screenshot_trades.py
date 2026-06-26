"""Replay the screenshot trades: ONDO/LTC/ADA shorts from today 06-24.

Uses the exact entry prices and sides from the screenshot to find the trade
window via 1m klines, then reconstructs the full path + MFE/MAE. These are the
big-loss trades the user is asking about (-3 to -4.7U each, -25% to -35%).
"""
import json, sys, time, urllib.request
from datetime import datetime, timezone

# From the screenshot (06-24 evening):
TRADES = [
    {"symbol": "ONDOUSDT", "side": "SELL", "entry": 0.3041, "exit": 0.3074, "pnl": -4.14, "dur_min": 13, "lev": 30},
    {"symbol": "LTCUSDT", "side": "SELL", "entry": 41.81, "exit": 42.13, "pnl": -4.69, "dur_min": 71, "lev": 30},
    {"symbol": "ADAUSDT", "side": "SELL", "entry": 0.1471, "exit": 0.1486, "pnl": -3.35, "dur_min": 22, "lev": 30},
]


def fetch_recent(symbol, hours=6):
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - hours * 3600 * 1000
    rows, cursor = [], start
    while cursor < end:
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}"
               f"&interval=1m&startTime={cursor}&endTime={end}&limit=1000")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bfa-replay"})
            with urllib.request.urlopen(req, timeout=15) as r:
                page = json.load(r)
        except Exception:
            break
        if not page:
            break
        for k in page:
            rows.append({"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4])})
        cursor = int(page[-1][0]) + 60000
        if len(page) < 1000:
            break
        time.sleep(0.12)
    return rows


def find_trade_window(klines, entry, side, dur_min):
    """Find the bar where price crosses entry (for SELL, price rises to entry)."""
    is_short = side == "SELL"
    candidates = []
    for i, k in enumerate(klines):
        # entry fill: for a SELL limit, price rises to entry; for market, close crosses
        if is_short and k["h"] >= entry >= k["l"]:
            candidates.append(i)
        elif not is_short and k["l"] <= entry <= k["h"]:
            candidates.append(i)
    # pick the candidate closest to "dur_min" ago
    return candidates


def replay(t, klines):
    entry = t["entry"]
    is_short = t["side"] == "SELL"
    cands = find_trade_window(klines, entry, t["side"], t["dur_min"])
    if not cands:
        # fallback: find bar whose range contains entry in last few hours
        return None
    # try each candidate window of dur_min length
    best = None
    for ci in cands:
        end_i = min(ci + t["dur_min"] + 5, len(klines))
        window = klines[ci:end_i]
        if len(window) < 3:
            continue
        mfe = mae = 0.0
        mfe_t = mae_t = None
        for k in window:
            if is_short:
                fav = entry - k["l"]; adv = k["h"] - entry
            else:
                fav = k["h"] - entry; adv = entry - k["l"]
            if fav > mfe:
                mfe = fav; mfe_t = k["t"]
            if adv > mae:
                mae = adv; mae_t = k["t"]
        path = [round((k["c"] - entry) / entry * 100 * (-1 if is_short else 1), 3) for k in window]
        score = abs(mae / entry * 100 - abs((t["exit"] - t["entry"]) / t["entry"] * 100))
        cand = {"ci": ci, "mfe_pct": round(mfe / entry * 100, 3), "mae_pct": round(mae / entry * 100, 3),
                "mfe_t_min": round((mfe_t - window[0]["t"]) / 60000, 1) if mfe_t else None,
                "mae_t_min": round((mae_t - window[0]["t"]) / 60000, 1) if mae_t else None,
                "path": path, "score": score}
        if best is None or cand["score"] < best["score"]:
            best = cand
    return best


def main():
    for t in TRADES:
        klines = fetch_recent(t["symbol"], hours=8)
        print(f"\n=== {t['symbol']} {t['side']} entry={t['entry']} exit={t['exit']} "
              f"pnl={t['pnl']}U dur={t['dur_min']}min lev={t['lev']}x ===")
        if not klines:
            print("  (kline fetch failed)")
            continue
        r = replay(t, klines)
        if not r:
            print(f"  (could not locate entry in last 8h; {len(klines)} klines fetched)")
            continue
        print(f"  MFE={r['mfe_pct']:+.3f}% @ {r['mfe_t_min']}min   MAE={r['mae_pct']:+.3f}% @ {r['mae_t_min']}min")
        path = r["path"]
        step = max(1, len(path) // 28)
        spark = path[::step]
        line = "  "
        for pct in spark:
            idx = min(7, max(0, int((pct + 1.5) * 2)))
            line += "▁▂▃▄▅▆▇█"[idx]
        print(f"  path (signed % from entry): {line}")
        print("  " + " ".join(f"{p:+.2f}" for p in spark))
        if r["mfe_pct"] > 0.05:
            profit_bars = sum(1 for p in path if p > 0)
            print(f"  >> profitable {profit_bars}/{len(path)} min before loss; MFE {r['mfe_pct']:+.3f}% NOT protected")
        elif r["mae_pct"] > 2.0:
            print(f"  >> pure adverse: went against immediately, MAE {r['mae_pct']:+.3f}% (stop too wide or missing)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
