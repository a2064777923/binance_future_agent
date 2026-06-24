"""Select a research universe of 24 perpetual USDT-COIN symbols.

Stratified by quote volume into large/mid/small caps, always including the 9
live symbols plus BTC/ETH anchors, plus a spread of altcoins for diversity.
Read-only against Binance public fapi. No secrets, no DB, no live state.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

LIVE_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "HYPEUSDT", "ONDOUSDT",
    "PUMPUSDT", "SUIUSDT", "NEARUSDT", "ZECUSDT",
}
ANCHORS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
TARGET_COUNT = 24


def fetch_24hr() -> list[dict]:
    req = urllib.request.Request(
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
        headers={"User-Agent": "bfa-research"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if not isinstance(payload, list):
        raise RuntimeError("unexpected 24hr payload")
    return payload


def fetch_exchange_info() -> set[str]:
    req = urllib.request.Request(
        "https://fapi.binance.com/fapi/v1/exchangeInfo",
        headers={"User-Agent": "bfa-research"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        info = json.load(r)
    eligible = set()
    for s in info["symbols"]:
        if (
            s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
            and s.get("underlyingType") == "COIN"
            and "TRADFI" not in (s.get("underlyingSubType") or [])
        ):
            eligible.add(s["symbol"])
    return eligible


def main() -> int:
    eligible = fetch_exchange_info()
    rows = fetch_24hr()
    candidates = []
    for row in rows:
        sym = row.get("symbol", "")
        if sym not in eligible:
            continue
        try:
            qv = float(row.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue
        # skip stablecoin pairs / obvious non-tradeable
        if qv <= 0:
            continue
        candidates.append({"symbol": sym, "quote_volume": qv})
    candidates.sort(key=lambda x: x["quote_volume"], reverse=True)

    # stratify into tiers by rank
    n = len(candidates)
    tier1_end = max(10, n // 20)      # top 5%
    tier2_end = max(30, n // 5)        # top 20%
    tier1 = [c["symbol"] for c in candidates[:tier1_end]]
    tier2 = [c["symbol"] for c in candidates[tier1_end:tier2_end]]
    tier3 = [c["symbol"] for c in candidates[tier2_end:] if c["quote_volume"] >= 20_000_000]

    selected = set(ANCHORS)
    # add all live symbols first
    for s in LIVE_SYMBOLS:
        if s in eligible:
            selected.add(s)

    # fill tier1 (large cap)
    for s in tier1:
        if len(selected) >= TARGET_COUNT:
            break
        selected.add(s)

    # add some mid-cap alts from tier2
    mid_targets = [
        "AVAXUSDT", "DOGEUSDT", "LINKUSDT", "ADAUSDT", "XRPUSDT",
        "BNBUSDT", "TRXUSDT", "LTCUSDT", "BCHUSDT", "DOTUSDT",
        "ARBUSDT", "OPUSDT", "APTUSDT", "INJUSDT", "TIAUSDT",
        "SEIUSDT", "SAGAUSDT", "WIFUSDT", "PEPEUSDT", "WLDUSDT",
        "FILUSDT", "ETCUSDT", "ATOMUSDT", "NEARUSDT", "FTMUSDT",
    ]
    for s in mid_targets:
        if len(selected) >= TARGET_COUNT:
            break
        if s in tier2 or s in tier1:
            selected.add(s)

    # add small-cap volatile alts from tier3
    small_targets = [
        "PUMPUSDT", "JUPUSDT", "PYTHUSDT", "STRTKUSDT", "ENOUSDT",
        "ZROUSDT", "KMNOUSDT", "IOUSDT", "IOUSDT",
    ]
    for s in small_targets:
        if len(selected) >= TARGET_COUNT:
            break
        if s in eligible:
            selected.add(s)

    # top up from tier2/tier3 if still short
    pool = tier2 + tier3
    for s in pool:
        if len(selected) >= TARGET_COUNT:
            break
        selected.add(s)

    final = sorted(selected)[:TARGET_COUNT]
    by_sym = {c["symbol"]: c for c in candidates}
    print(f"# research universe ({len(final)} symbols)")
    print(f"# tiers: large={len(tier1)} mid={len(tier2)} small(>20M qv)={len(tier3)}")
    print("#")
    print("# symbol       tier      quote_volume_24h")
    for s in final:
        qv = by_sym.get(s, {}).get("quote_volume", 0)
        tier = "large" if s in tier1 else ("mid" if s in tier2 else "small")
        live = " [live]" if s in LIVE_SYMBOLS else ""
        print(f"{s:14s} {tier:8s} {qv:>16,.0f}{live}")

    out = {"symbols": final, "live_symbols": sorted(LIVE_SYMBOLS & eligible)}
    with open("data/research/universe.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nwrote data/research/universe.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
