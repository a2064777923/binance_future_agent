"""Replay live trades: MFE/MAE + was-winning-then-reverted analysis.

Reads outcomes + order_intents from the live DB (mode=ro), fetches 1m klines
from Binance public fapi to reconstruct each trade's price path, and reports
whether the trade was profitable at peak before reverting. This is the 覆盤
the user asked for: see real trades from entry to exit and where they turned.

No writes. No secrets. No service disruption.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
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
            rows.append({"t": int(k[0]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4])})
        cursor = int(page[-1][0]) + 60_000
        if len(page) < 1000:
            break
        time.sleep(0.12)
    return rows


def load_trades(limit=50):
    conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    cur = conn.cursor()
    # build event_id -> leg map from order_intents
    leg_map = {}
    try:
        cur.execute("SELECT payload_json FROM order_intents ORDER BY id DESC LIMIT 500")
        for (pj,) in cur.fetchall():
            try:
                p = json.loads(pj or "{}")
            except Exception:
                continue
            eid = p.get("event_id") or p.get("candidate_event_id")
            leg = p.get("strategy_leg") or p.get("metadata", {}).get("strategy_leg") if isinstance(p.get("metadata"), dict) else p.get("strategy_leg")
            if eid and leg:
                leg_map[eid] = leg
    except Exception:
        pass
    trades = []
    cur.execute("SELECT payload_json FROM outcomes ORDER BY id DESC LIMIT ?", (limit,))
    for (pj,) in cur.fetchall():
        try:
            p = json.loads(pj or "{}")
        except Exception:
            continue
        intent = p.get("intent", {})
        eid = intent.get("event_id")
        side = intent.get("side", "").upper()
        symbol = intent.get("symbol")
        entry_price = intent.get("entry_price")
        occurred = intent.get("occurred_at")
        first_t = p.get("first_trade_time")
        last_t = p.get("last_trade_time")
        pnl = p.get("net_realized_pnl_usdt")
        trades.append({
            "symbol": symbol, "side": side, "entry": entry_price,
            "entry_time": first_t or occurred, "exit_time": last_t,
            "pnl": pnl, "leg": leg_map.get(eid, "?"),
            "occurred_at": occurred, "event_id": eid,
            "trade_count": p.get("trade_count"),
        })
    conn.close()
    return trades


def replay(trade):
    symbol = trade["symbol"]
    side = trade["side"]
    entry = trade["entry"]
    entry_ms = to_ms(trade["entry_time"])
    exit_ms = to_ms(trade["exit_time"])
    if not symbol or not entry or not entry_ms or not exit_ms or exit_ms <= entry_ms:
        return None
    klines = fetch_klines(symbol, entry_ms, exit_ms)
    if not klines:
        return None
    is_long = side in ("BUY", "LONG", "1", 1)
    mfe = mae = 0.0
    mfe_t = None
    for k in klines:
        if is_long:
            fav = k["h"] - entry; adv = entry - k["l"]
        else:
            fav = entry - k["l"]; adv = k["h"] - entry
        if fav > mfe:
            mfe = fav; mfe_t = k["t"]
        mae = max(mae, adv)
    pnl_pct = ((trade["pnl"] or 0) / (entry * trade.get("trade_count", 1))) if entry else 0
    # simpler: pnl as % of notional (entry * qty from first trade approx)
    mfe_pct = mfe / entry * 100 if entry else 0
    mae_pct = mae / entry * 100 if entry else 0
    t_min = (exit_ms - entry_ms) / 60000
    mfe_min = (mfe_t - entry_ms) / 60000 if mfe_t else None
    pnl = trade["pnl"] or 0
    return {
        "symbol": symbol, "side": side, "leg": trade["leg"],
        "entry": entry, "pnl_usdt": round(pnl, 4),
        "mfe_pct": round(mfe_pct, 3), "mae_pct": round(mae_pct, 3),
        "t_min": round(t_min, 1), "t_mfe_min": round(mfe_min, 1) if mfe_min else None,
        "win_at_peak": mfe_pct > 0.05,
        "reverted_to_loss": mfe_pct > 0.05 and pnl < 0,
    }


def main():
    trades = load_trades(50)
    print(f"# {len(trades)} recent live trades")
    replays = []
    for t in trades:
        r = replay(t)
        if r:
            replays.append(r)
            tag = "REVERT(loss after win)" if r["reverted_to_loss"] else ("WIN" if r["pnl_usdt"] > 0 else "LOSS")
            print(f"  {r['symbol']:14s} {r['leg']:12s} {r['side']:4s} pnl={r['pnl_usdt']:+.3f}U "
                  f"mfe={r['mfe_pct']:+.3f}% mae={r['mae_pct']:+.3f}% "
                  f"t={r['t_min']:.0f}m t_mfe={r['t_mfe_min']} [{tag}]")
    if not replays:
        print("# no replays (kline fetch or field issue)")
        return 1
    n = len(replays)
    wins = sum(1 for r in replays if r["pnl_usdt"] > 0)
    reverts = sum(1 for r in replays if r["reverted_to_loss"])
    win_at_peak = sum(1 for r in replays if r["win_at_peak"])
    print(f"\n# {n} trades: {wins} wins ({wins/n:.0%}), {win_at_peak} hit profit at peak ({win_at_peak/n:.0%}), {reverts} reverted to loss ({reverts/n:.0%})")
    print(f"# avg MFE = {sum(r['mfe_pct'] for r in replays)/n:+.3f}%")
    # by leg
    for leg in sorted({r["leg"] for r in replays}):
        sub = [r for r in replays if r["leg"] == leg]
        lw = sum(1 for r in sub if r["pnl_usdt"] > 0)
        lr = sum(1 for r in sub if r["reverted_to_loss"])
        print(f"#   {leg}: {len(sub)} trades, {lw} wins ({lw/max(len(sub),1):.0%}), {lr} reverted ({lr/max(len(sub),1):.0%}), avg_mfe={sum(r['mfe_pct'] for r in sub)/max(len(sub),1):+.3f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
