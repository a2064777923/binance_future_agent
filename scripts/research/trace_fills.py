"""Trace ONDO/LTC/ADA today via fills + exchange_responses + ai-decisions log.

The screenshot trades aren't in the recent outcomes yet. Find them via the
fills table (every fill is recorded) and cross-ref ai-decisions.jsonl.
Read-only.
"""
import sqlite3, json
from pathlib import Path

DB = "/opt/binance-futures-agent/data/agent.sqlite"
conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
cur = conn.cursor()

targets = {"ONDOUSDT", "LTCUSDT", "ADAUSDT"}

# fills table
print("=== fills for ONDO/LTC/ADA (recent 200) ===")
try:
    cur.execute("SELECT occurred_at, payload_json FROM fills ORDER BY id DESC LIMIT 200")
except Exception as e:
    # maybe different schema
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print("tables:", [r[0] for r in cur.fetchall()])
    raise SystemExit(0)
rows = []
for ts, pj in cur.fetchall():
    try:
        p = json.loads(pj or "{}")
    except Exception:
        continue
    sym = p.get("symbol")
    if sym not in targets:
        continue
    rows.append((ts, p))
for ts, p in rows[:20]:
    print(f"  {ts} {p.get('symbol')} side={p.get('side')} price={p.get('price')} "
          f"qty={p.get('qty') or p.get('quantity')} pnl={p.get('realized_pnl_usdt')} "
          f"maker={p.get('maker')} pos_side={p.get('position_side')}")

# exchange_responses (order submissions / rejections / sentinel actions)
print("\n=== exchange_responses for ONDO/LTC/ADA (recent 300) ===")
try:
    cur.execute("SELECT occurred_at, payload_json FROM exchange_responses ORDER BY id DESC LIMIT 300")
    found = 0
    for ts, pj in cur.fetchall():
        try:
            p = json.loads(pj or "{}")
        except Exception:
            continue
        blob = pj or ""
        if not any(t in blob for t in targets):
            continue
        if found >= 15:
            break
        sym = p.get("symbol", "?")
        etype = p.get("type") or p.get("event_type") or "?"
        status = p.get("status") or p.get("result") or "?"
        # show order type / reason
        keys = [k for k in p.keys() if k not in ("symbol", "type", "status", "event_type")]
        print(f"  {ts} {sym} type={etype} status={status} extra={{{', '.join(keys[:5])}}}")
        found += 1
except Exception as e:
    print("  query failed:", e)

# ai-decisions.jsonl grep (today, these symbols)
print("\n=== ai-decisions.jsonl grep (today ONDO/LTC/ADA) ===")
logpath = Path("/opt/binance-futures-agent/logs/ai-decisions.jsonl")
if logpath.exists():
    import subprocess
    # tail last 3000 lines, grep for targets, show decision + reasons
    r = subprocess.run(
        ["bash", "-c", f"tail -5000 {logpath} | grep -E 'ONDOUSDT|LTCUSDT|ADAUSDT' | tail -20"],
        capture_output=True, text=True, timeout=30,
    )
    for line in r.stdout.splitlines():
        try:
            p = json.loads(line)
        except Exception:
            continue
        sym = p.get("symbol", "?")
        decision = p.get("decision", "?")
        ts = p.get("occurred_at") or p.get("timestamp") or "?"
        reasons = p.get("reasons") or []
        leg = p.get("strategy_leg") or (p.get("metadata", {}).get("strategy_leg") if isinstance(p.get("metadata"), dict) else None)
        rstr = ", ".join(str(x).split(":")[0] for x in reasons[:5])
        print(f"  {ts} {sym} decision={decision} leg={leg} reasons=[{rstr}]")

conn.close()
