"""Extract backtest summary printable on server."""
import json
import sys

variants = sys.argv[1:] or ["quant_setup", "quant_setup_live_action_flow"]
for v in variants:
    path = f"reports/p71-{v}.json"
    r = json.load(open(path))
    print(f"=== variant: {v} ===")
    summary = r.get("summary", r)
    if isinstance(summary, dict):
        for k in sorted(summary.keys()):
            print(f"  {k} = {summary[k]}")
    syms = r.get("symbols") or r.get("symbol_results")
    if syms:
        print("  per-symbol:")
        for sym in syms:
            label = sym.get("symbol", "?")
            ss = sym.get("summary", sym)
            tcount = ss.get("trade_count", ss.get("total_trades", ss.get("trades", "?")))
            wr = ss.get("win_rate", "?")
            pf = ss.get("profit_factor", "?")
            tn = ss.get("total_net_pnl_percent", ss.get("total_net_pnl_usdt", "?"))
            print(f"    {label}: trades={tcount} wr={wr} pf={pf} net={tn}")
    print()
