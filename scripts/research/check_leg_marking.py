"""Check if order_intents carry strategy_leg (read-only)."""
import sqlite3, json
conn = sqlite3.connect("file:/opt/binance-futures-agent/data/agent.sqlite?mode=ro&immutable=1", uri=True)
cur = conn.cursor()
cur.execute("SELECT payload_json FROM order_intents ORDER BY id DESC LIMIT 8")
for i, (pj,) in enumerate(cur.fetchall()):
    p = json.loads(pj or "{}")
    md = p.get("metadata", {})
    if not isinstance(md, dict):
        md = {}
    leg = p.get("strategy_leg") or md.get("strategy_leg")
    reg = p.get("regime_label") or md.get("regime_label")
    print(f"intent {i}: symbol={p.get('symbol')} leg={leg} regime={reg} metadata_keys={sorted(md.keys())[:8]}")
# also: does position_review / position_sentinel store the leg?
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%position%'")
print("position tables:", [r[0] for r in cur.fetchall()])
conn.close()
