"""Train a fail-closed near-BBO calibration artifact from public shadow labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bfa.backtest.near_bbo_calibration import (  # noqa: E402
    NearBboCalibrationConfig,
    fit_near_bbo_calibration,
    load_near_bbo_labels,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", required=True, help="shadow JSON/JSONL; repeat for multiple sessions")
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-labels", type=int, default=500)
    parser.add_argument("--min-fills", type=int, default=100)
    parser.add_argument("--min-profitable-fills", type=int, default=20)
    parser.add_argument("--min-losing-fills", type=int, default=20)
    parser.add_argument("--validation-fraction", type=float, default=0.25)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    labels = load_near_bbo_labels(args.input)
    report = fit_near_bbo_calibration(
        labels,
        NearBboCalibrationConfig(
            min_labels=max(1, int(args.min_labels)),
            min_fills=max(1, int(args.min_fills)),
            min_profitable_fills=max(1, int(args.min_profitable_fills)),
            min_losing_fills=max(1, int(args.min_losing_fills)),
            validation_fraction=float(args.validation_fraction),
        ),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    if not args.quiet:
        print(
            json.dumps(
                {
                    "output": str(output),
                    "status": report["status"],
                    "reasons": report["reasons"],
                    "counts": report["counts"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0 if report["status"] == "trained" else 2


if __name__ == "__main__":
    raise SystemExit(main())
