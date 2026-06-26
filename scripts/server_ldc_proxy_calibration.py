"""Proxy-side calibration for the LDC release verdict.

The offline lift sweep calibrates LDC against a PROXY setup side (a simple
mom_6 sign), not the real setup pipeline (14 factors + regime router + AI
review). This script makes that approximation measurable: it reads recorded
trade_setups over a window, recomputes the proxy side from each setup's
features, and reports proxy-vs-actual side agreement.

Read-only. It does not place orders, call signed Binance endpoints, or
mutate SQLite — mirroring scripts/server_live_trade_forensics.py.

The release verdict is two-headed: local lift > 1.0 AND this agreement read
together. High lift + low agreement -> lift calibrated to wrong baseline,
must be discounted. Run on the server where the DB lives.

Usage:
    python scripts/server_ldc_proxy_calibration.py \
        --db /opt/binance-futures-agent/data/agent.sqlite \
        --since 2026-06-01T00:00:00Z
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping


def proxy_side_from_features(features: Mapping[str, Any]) -> str:
    """Proxy side = sign of kline_momentum_percent (mirrors train_ldc_classifier)."""
    mom = features.get("kline_momentum_percent")
    try:
        return "long" if float(mom) >= 0 else "short"
    except (TypeError, ValueError):
        return "long"   # neutral default; matches the training script's >= 0 branch


def agreement_report_from_setups(setups: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare actual setup side to the proxy side recomputed from features."""
    n = len(setups)
    agree = 0
    for s in setups:
        actual = str(s.get("side") or "").lower()
        feats = s.get("candidate", {}).get("features", {})
        if actual and actual in {"long", "short"}:
            if proxy_side_from_features(feats) == actual:
                agree += 1
    frac = agree / n if n else 0.0
    return {
        "n_setups": n,
        "n_agree": agree,
        "agreement_fraction": round(frac, 4),
        "interpretation": (
            ">= 0.8: proxy is a faithful stand-in, lift verdict trustworthy. "
            "0.5-0.8: moderate divergence, discount lift somewhat. "
            "< 0.5: proxy diverges systematically, lift calibrated to wrong baseline "
            "- do NOT authorize live on lift alone."
        ),
    }


def load_setups_from_db(db_path: str, *, since: str) -> list[dict[str, Any]]:
    """Read trade_setups payloads since `since`. Read-only."""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT payload FROM trade_setups WHERE occurred_at >= ? ORDER BY occurred_at",
            (since,),
        ).fetchall()
        setups = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
                setup = payload.get("setup", {})
                candidate = payload.get("candidate", {})
                if setup.get("side"):
                    setups.append({"side": setup["side"], "candidate": candidate})
            except (json.JSONDecodeError, TypeError):
                continue
        return setups
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--since", default="2026-01-01T00:00:00Z")
    args = ap.parse_args()
    if not Path(args.db).exists():
        print(f"db not found: {args.db}")
        return 1
    setups = load_setups_from_db(args.db, since=args.since)
    report = agreement_report_from_setups(setups)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
