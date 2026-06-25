"""Deep-dive the exchange_responses for today's ONDO/LTC/ADA trades.

Shows the full intent + response for each exchange action, so we can see
exactly what orders were placed, replaced, or cancelled — including sentinel
protective orders and why they did/didn't prevent the loss.
Read-only.
"""
import sqlite3, json

DB = "/opt/binance-futures-agent/data/agent.sqlite"
conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
cur = conn.cursor()
targets = ("ONDOUSDT", "LTCUSDT", "ADAUSDT")

cur.execute("SELECT occurred_at, payload_json FROM exchange_responses ORDER BY id DESC LIMIT 400")
rows = []
for ts, pj in cur.fetchall():
    if not any(t in (pj or "") for t in targets):
        continue
    rows.append((ts, pj))
rows.reverse()  # chronological

print(f"# {len(rows)} exchange_responses for ONDO/LTC/ADA today\n")
for ts, pj in rows:
    try:
        p = json.loads(pj or "{}")
    except Exception:
        continue
    intent = p.get("intent", {}) if isinstance(p.get("intent"), dict) else {}
    response = p.get("response", {}) if isinstance(p.get("response"), dict) else {}
    rtype = p.get("response_type") or response.get("type", "?")
    sym = intent.get("symbol") or response.get("symbol", "?")
    if sym not in targets:
        continue
    otype = intent.get("order_type") or intent.get("type", "?")
    side = intent.get("side", "?")
    price = intent.get("price") or intent.get("stop_price") or intent.get("trigger_price")
    qty = intent.get("quantity") or intent.get("origQty")
    close_pos = intent.get("close_position") or intent.get("reduceOnly")
    status = response.get("status") or response.get("code") or "?"
    order_id = response.get("orderId")
    # the key signal: is this a protective/stop order?
    is_algo = "STOP" in str(otype).upper() or "TAKE_PROFIT" in str(otype).upper() or close_pos
    tag = "PROTECT" if (is_algo or close_pos) else ("ENTRY" if not close_pos else "?")
    reason = intent.get("reason") or intent.get("client_algo") or response.get("msg", "")
    print(f"{ts} {sym:9s} [{tag:6s}] type={otype:14s} side={side:4s} price={price} qty={qty} "
          f"closePos={close_pos} status={status} id={order_id} {reason}")
conn.close()
