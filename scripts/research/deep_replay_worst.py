"""Deep-replay the worst-loss live trades: full 1m path + reversal point.

Focus on the trades that lost the most (the user's screenshot case). For each,
fetch the complete 1m kline path from entry to exit, mark the MFE peak and the
reversal, and show exactly when/where protection should have triggered but
didn't. This is the actionable 覆盤: not aggregate stats, but the specific
trades that hurt.

Read-only DB + public klines. No writes.
"""
from __future__ import annotations
import json, sqlite3, sys, time, urllib.request
from datetime import datetime

DB = "/opt/binance-futures-agent/data/agent.sqlite"


def to_ms(t):
    if isinstance(t, (int, float)):
        return int(t)
    if isinstance(t, str):
        try:
            return int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return None
    return None


def fetch_klines(symbol, start_ms, end_ms):
    rows, cursor = [], start_ms
    while cursor < end_ms:
        url = (f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}"
               f"&interval=1m&startTime={cursor}&endTime={end_ms}&limit=1000")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bfa-replay"})
            with urllib.request.urlopen(req, timeout=15) as r:
                page = json.load(r)
        except Exception:
            break
        if not page:
            break
        for k in page:
            rows.append({"t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
                         "l": float(k[3]), "c": float(k[4])})
        cursor = int(page[-1][0]) + 60000
        if len(page) < 1000:
            break
        time.sleep(0.12)
    return rows


def load_worst(limit=8):
    conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT payload_json FROM outcomes ORDER BY id DESC LIMIT 80")
    rows = []
    for (pj,) in cur.fetchall():
        try:
            p = json.loads(pj or "{}")
        except Exception:
            continue
        intent = p.get("intent", {})
        pnl = p.get("net_realized_pnl_usdt")
        if pnl is None:
            continue
        rows.append({
            "symbol": intent.get("symbol"), "side": intent.get("side", ""),
            "entry": intent.get("entry_price"),
            "entry_time": p.get("first_trade_time") or intent.get("occurred_at"),
            "exit_time": p.get("last_trade_time"),
            "pnl": float(pnl), "trade_count": p.get("trade_count"),
        })
    conn.close()
    rows.sort(key=lambda r: r["pnl"])  # most negative first
    return rows[:limit]


def deep_replay(t):
    sym, side = t["symbol"], str(t["side"]).upper()
    entry = t["entry"]
    ems = to_ms(t["entry_time"]); xms = to_ms(t["exit_time"])
    if not all([sym, entry, ems, xms]) or xms <= ems:
        return None
    klines = fetch_klines(sym, ems, xms)
    if not klines:
        return None
    is_long = side in ("BUY", "LONG")
    mfe = mae = 0.0; mfe_t = mae_t = None
    path = []
    for k in klines:
        if is_long:
            fav = k["h"] - entry; adv = entry - k["l"]
        else:
            fav = entry - k["l"]; adv = k["h"] - entry
        if fav > mfe:
            mfe = fav; mfe_t = k["t"]
        if adv > mae:
            mae = adv; mae_t = k["t"]
        path.append((k["t"], round((k["c"] - entry) / entry * 100 * (1 if is_long else -1), 3)))
    return {
        "symbol": sym, "side": side, "entry": entry, "pnl": t["pnl"],
        "n_bars": len(klines), "t_min": round((xms - ems) / 60000, 1),
        "mfe_pct": round(mfe / entry * 100, 3), "mae_pct": round(mae / entry * 100, 3),
        "t_mfe_min": round((mfe_t - ems) / 60000, 1) if mfe_t else None,
        "t_mae_min": round((mae_t - ems) / 60000, 1) if mae_t else None,
        "path_close_pct": path,  # signed close % from entry, per minute
    }


def main():
    worst = load_worst(8)
    print(f"# {len(worst)} worst-loss trades (deep replay)")
    for t in worst:
        r = deep_replay(t)
        if not r:
            print(f"  {t['symbol']:12s} {t['side']:4s} pnl={t['pnl']:+.3f}U  (replay failed)")
            continue
        print(f"\n=== {r['symbol']} {r['side']} | pnl={r['pnl']:+.3f}U | {r['n_bars']}min ===")
        print(f"  entry={r['entry']}  MFE={r['mfe_pct']:+.3f}% @ {r['t_mfe_min']}min  MAE={r['mae_pct']:+.3f}% @ {r['t_mae_min']}min")
        # show the path as a sparkline every 2 min
        path = [pct for (_t, pct) in r["path_close_pct"]]
        step = max(1, len(path) // 30)
        spark = path[::step]
        print(f"  path (signed % from entry, every ~{step}min):")
        line = "  "
        for pct in spark:
            idx = min(7, max(0, int((pct + 1) * 2)))
            line += "▁▂▃▄▅▆▇█"[idx]
        print(line)
        nums = "  " + " ".join(f"{p:+.2f}" for p in spark)
        print(nums)
        # the key question: how long was it in profit before reverting?
        if r["mfe_pct"] > 0.05 and r["pnl"] < 0:
            profit_bars = sum(1 for p in path if p > 0)
            print(f"  >> was profitable for {profit_bars}/{len(path)} min before closing at a loss")
            print(f"  >> protection should have locked near MFE ({r['mfe_pct']:+.3f}%) but didn't")
    return 0


if __name__ == "__main__":
    sys.exit(main())
