"""Record Binance USD-M public raw feed for hftbacktest conversion.

The output gzip format is intentionally the one expected by hftbacktest's
``binancefutures.convert`` utility: one line per message,
``local_timestamp_ns raw_json``.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
SRC_DIR = ROOT_DIR / "src"
for path in (SCRIPT_DIR, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from bfa.market.raw_feed_recorder import (  # noqa: E402
    RawFeedRecorderConfig,
    RawSecondBarCache,
    normalize_symbols,
    raw_feed_line,
    write_raw_second_cache_payload,
)


async def main_async() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True, help="comma-separated Binance USD-M symbols")
    parser.add_argument("--output", required=True, help="gzip output path")
    parser.add_argument("--base-url", default="wss://fstream.binance.com")
    parser.add_argument("--depth-speed-ms", type=int, default=100)
    parser.add_argument("--duration-seconds", type=float, default=0.0, help="0 means run until interrupted")
    parser.add_argument("--no-trades", action="store_true", help="record depth only")
    parser.add_argument("--seconds-cache-output", help="optional compact JSON cache of latest 1s trade bars")
    parser.add_argument("--seconds-cache-window", type=int, default=1200)
    parser.add_argument("--seconds-cache-flush-seconds", type=float, default=2.0)
    parser.add_argument("--raw-write-batch-messages", type=int, default=256)
    parser.add_argument("--gzip-compresslevel", type=int, default=3)
    parser.add_argument("--websocket-max-queue", type=int, default=4096)
    args = parser.parse_args()

    config = RawFeedRecorderConfig(
        symbols=normalize_symbols(args.symbols),
        output_path=Path(args.output),
        base_url=args.base_url,
        depth_speed_ms=int(args.depth_speed_ms),
        include_trades=not args.no_trades,
    )
    count = await record_raw_feed(
        config,
        duration_seconds=float(args.duration_seconds),
        seconds_cache_output=Path(args.seconds_cache_output) if args.seconds_cache_output else None,
        seconds_cache_window=int(args.seconds_cache_window),
        seconds_cache_flush_seconds=float(args.seconds_cache_flush_seconds),
        raw_write_batch_messages=int(args.raw_write_batch_messages),
        gzip_compresslevel=int(args.gzip_compresslevel),
        websocket_max_queue=int(args.websocket_max_queue),
    )
    print({"output": str(config.output_path), "messages": count, "url": config.websocket_url})
    return 0


async def record_raw_feed(
    config: RawFeedRecorderConfig,
    *,
    duration_seconds: float = 0.0,
    seconds_cache_output: Path | None = None,
    seconds_cache_window: int = 1200,
    seconds_cache_flush_seconds: float = 2.0,
    raw_write_batch_messages: int = 256,
    gzip_compresslevel: int = 3,
    websocket_max_queue: int = 4096,
) -> int:
    try:
        import websockets
    except Exception as exc:  # noqa: BLE001 - runtime dependency may be intentionally optional.
        raise SystemExit("install websockets in the runtime environment before recording raw feeds") from exc

    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + duration_seconds if duration_seconds > 0 else None
    count = 0
    seconds_cache = (
        RawSecondBarCache.load_json(seconds_cache_output, window_seconds=seconds_cache_window)
        if seconds_cache_output is not None
        else None
    )
    flush_interval = max(seconds_cache_flush_seconds, 0.1)
    next_cache_flush = time.monotonic() + flush_interval
    cache_write_task: asyncio.Task[None] | None = None
    raw_batch: list[str] = []
    batch_size = max(1, int(raw_write_batch_messages))
    compresslevel = max(1, min(9, int(gzip_compresslevel)))
    try:
        async with websockets.connect(
            config.websocket_url,
            compression=None,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=2,
            max_queue=max(16, int(websocket_max_queue)),
        ) as websocket:
            with gzip.open(config.output_path, "at", encoding="utf-8", compresslevel=compresslevel) as handle:
                try:
                    while deadline is None or time.monotonic() < deadline:
                        timeout = max(0.1, deadline - time.monotonic()) if deadline is not None else None
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                        except asyncio.TimeoutError:
                            break
                        local_timestamp_ns = time.time_ns()
                        raw_batch.append(raw_feed_line(message, local_timestamp_ns=local_timestamp_ns))
                        if len(raw_batch) >= batch_size:
                            handle.write("".join(raw_batch))
                            raw_batch.clear()
                        if seconds_cache is not None:
                            seconds_cache.ingest_combined_message(message)
                            if time.monotonic() >= next_cache_flush:
                                if cache_write_task is None or cache_write_task.done():
                                    if cache_write_task is not None:
                                        await cache_write_task
                                    snapshot = seconds_cache.to_dict()
                                    cache_write_task = asyncio.create_task(
                                        asyncio.to_thread(
                                            write_raw_second_cache_payload,
                                            seconds_cache_output,
                                            snapshot,
                                        )
                                    )
                                next_cache_flush = time.monotonic() + flush_interval
                        count += 1
                finally:
                    if raw_batch:
                        handle.write("".join(raw_batch))
                        raw_batch.clear()
    finally:
        if cache_write_task is not None:
            await cache_write_task
        if seconds_cache is not None:
            await asyncio.to_thread(seconds_cache.write_json, seconds_cache_output)
    return count


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
