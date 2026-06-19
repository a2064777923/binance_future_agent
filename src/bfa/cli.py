"""Command-line utilities for local foundation checks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from typing import TextIO

from bfa.config import load_config, validate_config


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "config-check":
        return _run_config_check(args, env=env, stdout=stdout)

    parser.print_help(file=stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bfa")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_check = subparsers.add_parser(
        "config-check",
        help="validate runtime configuration without printing secrets",
    )
    config_check.add_argument(
        "--env-file",
        help="optional env file to load before environment overrides",
    )
    return parser


def _run_config_check(
    args: argparse.Namespace,
    *,
    env: Mapping[str, str] | None,
    stdout: TextIO | None,
) -> int:
    config = load_config(env=env, env_file=args.env_file)
    result = validate_config(config)
    payload = {
        "mode": result.mode.value if result.mode is not None else None,
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
        "redacted": result.redacted,
    }
    print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
