"""Find ONDO/LTC/ADA today's decisions + sentinel activity in the live DB.

Read-only. Looks for the 3 screenshot trades (shorts, entry 0.3041/41.81/0.1471)
and traces what the agent/sentinel did with them.
"""
import sqlite3, json

DB = "/opt/binance-futures-agent/data/agent.sqlite"
conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = sorted(r[0] for r in cur.fetchall())
print("tables:", tables)
print()

targets = {"ONDOUSDT", "LTCUSDT", "ADAUSDT"}

# 1. ai_decisions mentioning these symbols today
print("=== ai_decisions for ONDO/LTC/ADA (recent) ===")
cur.execute("SELECT occurred_at, payload_json FROM ai_decisions ORDER BY id DESC LIMIT 400")
shown = 0
for ts, pj in cur.fetchall():
    try:
        p = json.loads(pj or "{}")
    except Exception:
        continue
    sym = p.get("symbol")
    if sym not in targets:
        continue
    if shown >= 18:
        break
    decision = p.get("decision")
    reasons = p.get("reasons") or []
    leg = p.get("strategy_leg") or p.get("metadata", {}).get("strategy_leg") if isinstance(p.get("metadata"), dict) else p.get("strategy_leg")
    print(f"  {ts} {sym} decision={decision} leg={leg}")
    # show key reason codes (first 6)
    for r in reasons[:6]:
        print(f"      {r}")
    shown += 1
print()

# 2. order_intents for these
print("=== order_intents for ONDO/LTC/ADA (recent) ===")
try:
    cur.execute("SELECT occurred_at, payload_json FROM order_intents ORDER BY id DESC LIMIT 400")
    shown = 0
    for ts, pj in cur.fetchall():
        try:
            p = json.loads(pj or "{}")
        except Exception:
            continue
        sym = p.get("symbol")
        if sym not in targets:
            continue
        if shown >= 12:
            break
        md = p.get("metadata", {}) if isinstance(p.get("metadata"), dict) else {}
        leg = p.get("strategy_leg") or md.get("strategy_leg")
        regime = p.get("regime_label") or md.get("regime_label")
        print(f"  {ts} {sym} side={p.get('side')} entry={p.get('entry_price')} stop={p.get('stop_price')} target={p.get('target_price')} leg={leg} regime={regime}")
        shown += 1
except Exception as e:
    print("  order_intents query failed:", e)
print()

# 3. any sentinel-specific table?
sentinel_tables = [t for t in tables if "sentinel" in t.lower() or "position" in t.lower() or "adjustment" in t.lower()]
print("=== sentinel/position tables ===", sentinel_tables)
for t in sentinel_tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        n = cur.fetchone()[0]
        print(f"  {t}: {n} rows")
    except Exception as e:
        print(f"  {t}: {e}")

conn.close()
