"""Inspect outcome payload structure (read-only)."""
import sqlite3, json
conn = sqlite3.connect("file:/opt/binance-futures-agent/data/agent.sqlite?mode=ro&immutable=1", uri=True)
cur = conn.cursor()
cur.execute("SELECT payload_json FROM outcomes ORDER BY id DESC LIMIT 3")
for i, (pj,) in enumerate(cur.fetchall()):
    p = json.loads(pj or "{}")
    print(f"=== outcome {i} keys: {sorted(p.keys())} ===")
    print(json.dumps(p, indent=2)[:900])
    print()
# also check orders table for trade details
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%order%'")
print("order tables:", [r[0] for r in cur.fetchall()])
cur.execute("SELECT payload_json FROM orders ORDER BY id DESC LIMIT 2")
for i, (pj,) in enumerate(cur.fetchall()):
    p = json.loads(pj or "{}")
    print(f"=== order {i} keys: {sorted(p.keys())} ===")
    print(json.dumps(p, indent=2)[:700])
conn.close()
