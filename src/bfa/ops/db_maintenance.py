"""SQLite retention and compaction helpers for live operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Any

from bfa.config import AppConfig
from bfa.event_store.migrations import connect


@dataclass(frozen=True)
class TableCount:
    table: str
    rows: int

    def to_dict(self) -> dict[str, Any]:
        return {"table": self.table, "rows": self.rows}


@dataclass(frozen=True)
class DatabaseFootprint:
    path: str
    file_bytes: int | None
    page_count: int
    page_size: int
    freelist_count: int
    table_counts: list[TableCount] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "file_bytes": self.file_bytes,
            "page_count": self.page_count,
            "page_size": self.page_size,
            "freelist_count": self.freelist_count,
            "estimated_db_bytes": self.page_count * self.page_size,
            "estimated_free_bytes": self.freelist_count * self.page_size,
            "table_counts": [item.to_dict() for item in self.table_counts],
        }


@dataclass(frozen=True)
class DbMaintenanceReport:
    schema: str
    status: str
    execute: bool
    vacuum: bool
    retention_hours: float
    cutoff_iso: str
    cutoff_epoch_ms: int
    before: DatabaseFootprint
    after: DatabaseFootprint
    deletion_candidates: dict[str, int]
    deleted: dict[str, int]
    batch_size: int
    max_delete_rows: int
    raw_feed: RawFeedMaintenanceReport | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "execute": self.execute,
            "vacuum": self.vacuum,
            "retention_hours": self.retention_hours,
            "cutoff_iso": self.cutoff_iso,
            "cutoff_epoch_ms": self.cutoff_epoch_ms,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "deletion_candidates": dict(self.deletion_candidates),
            "deleted": dict(self.deleted),
            "batch_size": self.batch_size,
            "max_delete_rows": self.max_delete_rows,
            "raw_feed": self.raw_feed.to_dict() if self.raw_feed else None,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class RawFeedFile:
    path: str
    bytes: int
    modified_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "bytes": self.bytes,
            "modified_at": self.modified_at,
        }


@dataclass(frozen=True)
class RawFeedMaintenanceReport:
    directory: str
    retention_hours: float
    cutoff_iso: str
    execute: bool
    before_file_count: int
    before_bytes: int
    deletion_candidates: list[RawFeedFile]
    deleted_files: list[RawFeedFile]
    after_file_count: int
    after_bytes: int
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "directory": self.directory,
            "retention_hours": self.retention_hours,
            "cutoff_iso": self.cutoff_iso,
            "execute": self.execute,
            "before_file_count": self.before_file_count,
            "before_bytes": self.before_bytes,
            "deletion_candidates": [item.to_dict() for item in self.deletion_candidates],
            "deleted_files": [item.to_dict() for item in self.deleted_files],
            "after_file_count": self.after_file_count,
            "after_bytes": self.after_bytes,
            "reasons": list(self.reasons),
        }


TABLES_TO_SUMMARIZE = (
    "events",
    "market_snapshots",
    "candidates",
    "trade_setups",
    "ai_decisions",
    "order_intents",
    "exchange_responses",
    "fills",
    "outcomes",
    "risk_state",
    "paper_signals",
    "paper_observations",
    "paper_outcomes",
    "narratives",
)


def build_db_maintenance_report(
    config: AppConfig,
    *,
    db_path: str | None = None,
    retention_hours: float | None = None,
    execute: bool = False,
    vacuum: bool = False,
    batch_size: int | None = None,
    max_delete_rows: int | None = None,
    raw_feed_dir: str | None = None,
    raw_feed_retention_hours: float | None = None,
    clean_raw_feed: bool = False,
    now: str | None = None,
) -> DbMaintenanceReport:
    path = db_path or config.get("BFA_DB_PATH")
    retention = (
        float(retention_hours)
        if retention_hours is not None
        else float(config.get("BFA_DB_MARKET_SNAPSHOT_RETENTION_HOURS"))
    )
    if retention <= 0:
        raise ValueError("retention_hours must be positive")
    resolved_batch_size = (
        int(batch_size)
        if batch_size is not None
        else int(float(config.get("BFA_DB_MAINTENANCE_BATCH_SIZE", "5000")))
    )
    if resolved_batch_size <= 0:
        raise ValueError("batch_size must be positive")
    resolved_max_delete_rows = (
        int(max_delete_rows)
        if max_delete_rows is not None
        else int(float(config.get("BFA_DB_MAINTENANCE_MAX_DELETE_ROWS", "25000")))
    )
    if resolved_max_delete_rows <= 0:
        raise ValueError("max_delete_rows must be positive")
    cutoff = _parse_now(now) - timedelta(hours=retention)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff_epoch_ms = int(cutoff.timestamp() * 1000)

    raw_feed_report = (
        build_raw_feed_maintenance_report(
            config,
            raw_feed_dir=raw_feed_dir,
            retention_hours=raw_feed_retention_hours,
            execute=execute,
            now=cutoff + timedelta(hours=retention),
        )
        if clean_raw_feed or raw_feed_dir or raw_feed_retention_hours is not None
        else None
    )

    connection = connect(path)
    try:
        before = _footprint(connection, path, include_table_counts=not execute)
        deletion_candidates = _deletion_candidates(connection, cutoff_iso, cutoff_epoch_ms)
        deleted = {"market_snapshots": 0, "events": 0}
        reasons = ["dry_run"] if not execute else ["retention_applied"]
        if execute:
            deleted = _delete_old_market_snapshots(
                connection,
                cutoff_iso,
                cutoff_epoch_ms,
                batch_size=resolved_batch_size,
                max_delete_rows=resolved_max_delete_rows,
            )
            if deletion_candidates["market_snapshots"] > deleted["market_snapshots"]:
                reasons.append("delete_limited")
            if vacuum:
                reasons.append("vacuum_applied")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            else:
                connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
                reasons.append("vacuum_skipped")
        elif vacuum:
            reasons.append("vacuum_requested_but_execute_false")
        after = _footprint(connection, path, include_table_counts=not execute)
    finally:
        connection.close()

    if not execute:
        status = "db_maintenance_preview"
    elif vacuum:
        status = "db_maintenance_applied_vacuumed"
    else:
        status = "db_maintenance_applied"

    return DbMaintenanceReport(
        schema="bfa_db_maintenance_v1",
        status=status,
        execute=execute,
        vacuum=vacuum,
        retention_hours=retention,
        cutoff_iso=cutoff_iso,
        cutoff_epoch_ms=cutoff_epoch_ms,
        before=before,
        after=after,
        deletion_candidates=deletion_candidates,
        deleted=deleted,
        batch_size=resolved_batch_size,
        max_delete_rows=resolved_max_delete_rows,
        raw_feed=raw_feed_report,
        reasons=reasons,
    )


def build_raw_feed_maintenance_report(
    config: AppConfig,
    *,
    raw_feed_dir: str | None = None,
    retention_hours: float | None = None,
    execute: bool = False,
    now: str | datetime | None = None,
) -> RawFeedMaintenanceReport:
    directory = Path(raw_feed_dir or config.get("BFA_RAW_FEED_DIR", "/opt/binance-futures-agent/data/raw-feed"))
    retention = (
        float(retention_hours)
        if retention_hours is not None
        else float(config.get("BFA_RAW_FEED_RETENTION_HOURS", "24"))
    )
    if retention <= 0:
        raise ValueError("raw_feed_retention_hours must be positive")
    parsed_now = now if isinstance(now, datetime) else _parse_now(now)
    cutoff = parsed_now - timedelta(hours=retention)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    before = _raw_feed_files(directory)
    candidates = [item for item in before if _raw_feed_file_mtime(item.path) < cutoff]
    deleted: list[RawFeedFile] = []
    reasons = ["raw_feed_dry_run"] if not execute else ["raw_feed_retention_applied"]
    if execute:
        for item in candidates:
            path = Path(item.path)
            if _safe_raw_feed_delete_path(path, directory):
                try:
                    path.unlink()
                    deleted.append(item)
                except FileNotFoundError:
                    deleted.append(item)
            else:
                reasons.append(f"raw_feed_delete_skipped_unsafe_path:{path}")
    after = _raw_feed_files(directory)
    return RawFeedMaintenanceReport(
        directory=str(directory),
        retention_hours=retention,
        cutoff_iso=cutoff_iso,
        execute=execute,
        before_file_count=len(before),
        before_bytes=sum(item.bytes for item in before),
        deletion_candidates=candidates,
        deleted_files=deleted,
        after_file_count=len(after),
        after_bytes=sum(item.bytes for item in after),
        reasons=reasons,
    )


def _delete_old_market_snapshots(
    connection: sqlite3.Connection,
    cutoff_iso: str,
    cutoff_epoch_ms: int,
    *,
    batch_size: int,
    max_delete_rows: int,
) -> dict[str, int]:
    market_deleted = 0
    event_deleted = 0
    remaining = max_delete_rows
    previous_foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        for where_sql, params in _older_than_cutoff_ranges(cutoff_iso, cutoff_epoch_ms):
            while remaining > 0:
                limit = min(batch_size, remaining)
                rows = connection.execute(
                    f"""
                    SELECT id, event_id
                    FROM market_snapshots
                    WHERE {where_sql}
                    ORDER BY occurred_at ASC, id ASC
                    LIMIT ?
                    """,
                    (*params, limit),
                ).fetchall()
                if not rows:
                    break
                market_ids = [int(row["id"]) for row in rows]
                event_ids = [int(row["event_id"]) for row in rows if row["event_id"] is not None]
                market_deleted += _delete_ids(connection, "market_snapshots", market_ids)
                if event_ids:
                    event_deleted += _delete_event_ids(connection, event_ids)
                connection.commit()
                remaining -= len(market_ids)
    finally:
        connection.execute(f"PRAGMA foreign_keys = {previous_foreign_keys}")
    return {
        "market_snapshots": max(int(market_deleted), 0),
        "events": max(int(event_deleted), 0),
    }


def _delete_ids(connection: sqlite3.Connection, table: str, row_ids: list[int]) -> int:
    if not row_ids:
        return 0
    deleted = 0
    for chunk in _chunks(row_ids, 900):
        placeholders = ",".join("?" for _ in chunk)
        deleted += max(
            int(
                connection.execute(
                    f"DELETE FROM {table} WHERE id IN ({placeholders})",
                    chunk,
                ).rowcount
            ),
            0,
        )
    return deleted


def _delete_event_ids(connection: sqlite3.Connection, row_ids: list[int]) -> int:
    if not row_ids:
        return 0
    deleted = 0
    for chunk in _chunks(row_ids, 900):
        placeholders = ",".join("?" for _ in chunk)
        deleted += max(
            int(
                connection.execute(
                    f"DELETE FROM events WHERE event_type = 'market_snapshot' AND id IN ({placeholders})",
                    chunk,
                ).rowcount
            ),
            0,
        )
    return deleted


def _chunks(values: list[int], size: int) -> list[list[int]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _deletion_candidates(
    connection: sqlite3.Connection,
    cutoff_iso: str,
    cutoff_epoch_ms: int,
) -> dict[str, int]:
    market_count = 0
    event_count = 0
    for where_sql, params in _older_than_cutoff_ranges(cutoff_iso, cutoff_epoch_ms):
        market_count += int(
            connection.execute(
                f"SELECT COUNT(*) FROM market_snapshots WHERE {where_sql}",
                params,
            ).fetchone()[0]
        )
        event_count += int(
            connection.execute(
                f"""
                SELECT COUNT(*) FROM events
                WHERE event_type = 'market_snapshot'
                  AND {where_sql}
                """,
                params,
            ).fetchone()[0]
        )
    return {"market_snapshots": market_count, "events": event_count}


def _older_than_cutoff_ranges(cutoff_iso: str, cutoff_epoch_ms: int) -> list[tuple[str, tuple[str, str]]]:
    # The live store persists Binance event times as 13-digit epoch-ms strings.
    # These fixed-width values sort correctly as text, so this range keeps the
    # (occurred_at, id) index usable instead of forcing a table scan via CAST().
    return [
        ("occurred_at >= ? AND occurred_at < ?", ("1000000000000", str(cutoff_epoch_ms))),
        ("occurred_at >= ? AND occurred_at < ?", ("1970-", cutoff_iso)),
    ]


def _footprint(connection: sqlite3.Connection, path: str, *, include_table_counts: bool = True) -> DatabaseFootprint:
    page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    freelist_count = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    file_bytes = Path(path).stat().st_size if path and path != ":memory:" and Path(path).exists() else None
    table_counts = (
        [
            TableCount(table=table, rows=_count_table(connection, table))
            for table in TABLES_TO_SUMMARIZE
            if _table_exists(connection, table)
        ]
        if include_table_counts
        else []
    )
    return DatabaseFootprint(
        path=path,
        file_bytes=file_bytes,
        page_count=page_count,
        page_size=page_size,
        freelist_count=freelist_count,
        table_counts=table_counts,
    )


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _count_table(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _raw_feed_files(directory: Path) -> list[RawFeedFile]:
    if not directory.exists():
        return []
    files: list[RawFeedFile] = []
    for path in sorted(directory.glob("binance-usdm-raw-*.gz")):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            RawFeedFile(
                path=str(path),
                bytes=int(stat.st_size),
                modified_at=datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
    return files


def _raw_feed_file_mtime(path: str) -> datetime:
    return datetime.fromtimestamp(Path(path).stat().st_mtime, UTC)


def _safe_raw_feed_delete_path(path: Path, directory: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_dir = directory.resolve()
    except FileNotFoundError:
        return True
    return (
        resolved_path.parent == resolved_dir
        and resolved_path.suffix == ".gz"
        and resolved_path.name.startswith("binance-usdm-raw-")
    )


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
