"""Find the specific ONDO/LTC/ADA big-loss trades from today."""
import sqlite3, json
conn = sqlite3.connect("file:/opt/binance-futures-agent/data/agent.sqlite?mode=ro&immutable=1", uri=True)
cur = conn.cursor()
cur.execute("SELECT payload_json FROM outcomes ORDER BY id DESC LIMIT 100")
targets = {"ONDOUSDT", "LTCUSDT", "ADAUSDT", "RESOLVUSDT"}
found_any = False
for (pj,) in cur.fetchall():
    try:
        p = json.loads(pj or "{}")
    except Exception:
        continue
    intent = p.get("intent", {})
    sym = intent.get("symbol")
    if sym not in targets:
        continue
    found_any = True
    pnl = p.get("net_realized_pnl_usdt")
    print(f"{sym} side={intent.get('side')} entry={intent.get('entry_price')} "
          f"pnl={pnl} first={p.get('first_trade_time')} last={p.get('last_trade_time')} "
          f"lev={intent.get('leverage')} qty={intent.get('quantity')} "
          f"trades={p.get('trade_count')}")
    for tr in (p.get("trades") or [])[-2:]:
        print(f"    trade: side={tr.get('side')} price={tr.get('price')} pnl={tr.get('realized_pnl_usdt')} time={tr.get('time_iso')}")
if not found_any:
    print("no ONDO/LTC/ADA/RESOLV in recent 100 outcomes; showing last 10 outcomes:")
    cur.execute("SELECT payload_json FROM outcomes ORDER BY id DESC LIMIT 10")
    for (pj,) in cur.fetchall():
        try:
            p = json.loads(pj or "{}")
        except Exception:
            continue
        intent = p.get("intent", {})
        print(f"  {intent.get('symbol')} pnl={p.get('net_realized_pnl_usdt')} last={p.get('last_trade_time')}")
conn.close()
