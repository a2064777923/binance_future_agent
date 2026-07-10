"""Dump full intent payload for the ADA ALGO_REPLACE events to see if they
are stop-loss or take-profit orders, and whether reduceOnly/closePosition."""
import sqlite3, json

DB = "/opt/binance-futures-agent/data/agent.sqlite"
conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
cur = conn.cursor()
cur.execute("SELECT occurred_at, payload_json FROM exchange_responses ORDER BY id DESC LIMIT 400")
rows = []
for ts, pj in cur.fetchall():
    if "ADAUSDT" not in (pj or ""):
        continue
    rows.append((ts, pj))
rows.reverse()
for ts, pj in rows:
    try:
        p = json.loads(pj or "{}")
    except Exception:
        continue
    intent = p.get("intent", {})
    response = p.get("response", {})
    sym = intent.get("symbol", "")
    if sym != "ADAUSDT":
        continue
    otype = intent.get("order_type") or intent.get("type", "?")
    if "REPLACE" not in str(otype) and "BACKFILL" not in str(otype):
        continue
    print(f"\n=== {ts} {otype} ===")
    print("  intent:", json.dumps(intent, indent=2)[:600])
    print("  response:", json.dumps(response, indent=2)[:400])
conn.close()
