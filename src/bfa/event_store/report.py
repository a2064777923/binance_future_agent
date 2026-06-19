"""Review metrics for stored fills and outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any


@dataclass(frozen=True)
class ReviewReport:
    trade_count: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    gross_pnl_usdt: float = 0.0
    fees_usdt: float = 0.0
    slippage_usdt: float = 0.0
    net_pnl_usdt: float = 0.0
    expectancy_usdt: float = 0.0
    max_drawdown_usdt: float = 0.0
    reason_codes: dict[str, dict[str, float | int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_count": self.trade_count,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "gross_pnl_usdt": self.gross_pnl_usdt,
            "fees_usdt": self.fees_usdt,
            "slippage_usdt": self.slippage_usdt,
            "net_pnl_usdt": self.net_pnl_usdt,
            "expectancy_usdt": self.expectancy_usdt,
            "max_drawdown_usdt": self.max_drawdown_usdt,
            "reason_codes": self.reason_codes,
        }


def generate_review_report(connection: sqlite3.Connection) -> ReviewReport:
    connection.row_factory = sqlite3.Row
    outcome_payloads = _payloads(connection, "outcomes")
    fill_payloads = _payloads(connection, "fills")
    if not outcome_payloads and not fill_payloads:
        return ReviewReport()

    gross_values: list[float] = []
    net_values: list[float] = []
    fees = sum(_number(payload.get("fee_usdt") or payload.get("fees_usdt")) for payload in fill_payloads)
    slippage = sum(_number(payload.get("slippage_usdt")) for payload in fill_payloads)
    reason_codes: dict[str, dict[str, float | int]] = {}

    for payload in outcome_payloads:
        gross = _number(payload.get("gross_pnl_usdt") or payload.get("pnl_usdt"))
        outcome_fees = _number(payload.get("fee_usdt") or payload.get("fees_usdt"))
        outcome_slippage = _number(payload.get("slippage_usdt"))
        net = payload.get("net_pnl_usdt")
        net_pnl = _number(net) if net is not None else gross - outcome_fees - outcome_slippage
        gross_values.append(gross)
        net_values.append(net_pnl)
        fees += outcome_fees
        slippage += outcome_slippage
        for code in _reason_codes(payload):
            bucket = reason_codes.setdefault(code, {"count": 0, "net_pnl_usdt": 0.0})
            bucket["count"] = int(bucket["count"]) + 1
            bucket["net_pnl_usdt"] = float(bucket["net_pnl_usdt"]) + net_pnl

    trade_count = len(net_values)
    wins = sum(1 for value in net_values if value > 0)
    losses = sum(1 for value in net_values if value < 0)
    net_total = sum(net_values)
    gross_total = sum(gross_values)
    return ReviewReport(
        trade_count=trade_count,
        wins=wins,
        losses=losses,
        win_rate=(wins / trade_count) if trade_count else 0.0,
        gross_pnl_usdt=gross_total,
        fees_usdt=fees,
        slippage_usdt=slippage,
        net_pnl_usdt=net_total,
        expectancy_usdt=(net_total / trade_count) if trade_count else 0.0,
        max_drawdown_usdt=_max_drawdown(net_values),
        reason_codes=reason_codes,
    )


def _payloads(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"SELECT payload_json FROM {table} ORDER BY occurred_at ASC, id ASC"
    ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def _number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _reason_codes(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("reason_codes") or payload.get("reasons") or []
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, list):
        return [str(part).strip() for part in raw if str(part).strip()]
    return []


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    equity = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    return abs(max_drawdown)

