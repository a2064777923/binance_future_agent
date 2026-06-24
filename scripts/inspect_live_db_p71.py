"""Read-only inspect of live agent.sqlite to validate Phase 71 diagnostics.

Opens the DB in `mode=ro&immutable=1` so the live writer is undisturbed.
No state is written, no env is read, no exchange is contacted.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter


def main(db_path: str = "/opt/binance-futures-agent/data/agent.sqlite") -> int:
    uri = f"file:{db_path}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = sorted(r[0] for r in cur.fetchall())
    print("tables:", tables)
    print()

    schema_target = "ai_decisions"
    cur.execute(f"PRAGMA table_info({schema_target})")
    cols = [r[1] for r in cur.fetchall()]
    print(f"{schema_target} columns:", cols)
    print()

    # last 3 days, decision distribution from payload_json
    try:
        cur.execute(
            "SELECT payload_json FROM ai_decisions "
            "WHERE occurred_at > datetime('now','-3 days')"
        )
        decisions = Counter()
        reasons = Counter()
        for (pj,) in cur.fetchall():
            try:
                payload = json.loads(pj or "{}")
            except Exception:
                continue
            d = payload.get("decision") or payload.get("verdict") or "unknown"
            decisions[str(d)] += 1
            for raw in payload.get("reasons") or payload.get("reason_codes") or []:
                base = str(raw).split(":", 1)[0]
                reasons[base] += 1
        print("decision distribution last 3d:", dict(decisions))
        print()
        print("top reject reason families (last 3d):")
        for k, v in reasons.most_common(25):
            print(f"  {v:5d}  {k}")
    except Exception as exc:
        print("decision/reasons query failed:", exc)

    # paper_outcomes summary (this is paper_guard's input)
    try:
        cur.execute(
            "SELECT COUNT(*), MIN(occurred_at), MAX(occurred_at) FROM paper_outcomes"
        )
        n, lo, hi = cur.fetchone()
        print()
        print(f"paper_outcomes total: count={n} from={lo} to={hi}")
        cur.execute("SELECT payload_json FROM paper_outcomes ORDER BY id DESC LIMIT 200")
        rows = cur.fetchall()
        wins = 0
        losses = 0
        pnl_sum = 0.0
        sample_keys = set()
        for (pj,) in rows:
            try:
                p = json.loads(pj or "{}")
            except Exception:
                continue
            sample_keys.update(p.keys())
            pnl = p.get("net_pnl_usdt") or p.get("pnl_usdt") or p.get("realized_pnl_usdt") or 0.0
            try:
                pnl = float(pnl)
            except Exception:
                pnl = 0.0
            pnl_sum += pnl
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
        print(
            f"last 200 paper_outcomes: wins={wins} losses={losses} pnl_sum={pnl_sum:.4f}U "
            f"win_rate={wins/max(wins+losses,1):.3f}"
        )
        print(f"  sample payload keys (subset): {sorted(list(sample_keys))[:15]}")
    except Exception as exc:
        print("paper_outcomes query failed:", exc)

    # outcomes summary (real outcomes)
    try:
        cur.execute("SELECT COUNT(*), MIN(occurred_at), MAX(occurred_at) FROM outcomes")
        n, lo, hi = cur.fetchone()
        print()
        print(f"outcomes total: count={n} from={lo} to={hi}")
        cur.execute("SELECT payload_json FROM outcomes")
        wins = 0
        losses = 0
        pnl_sum = 0.0
        for (pj,) in cur.fetchall():
            try:
                p = json.loads(pj or "{}")
            except Exception:
                continue
            pnl = p.get("net_pnl_usdt") or p.get("pnl_usdt") or p.get("realized_pnl_usdt") or 0.0
            try:
                pnl = float(pnl)
            except Exception:
                pnl = 0.0
            pnl_sum += pnl
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
        print(
            f"all outcomes: wins={wins} losses={losses} pnl_sum={pnl_sum:.4f}U "
            f"win_rate={wins/max(wins+losses,1):.3f}"
        )
    except Exception as exc:
        print("outcomes query failed:", exc)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
