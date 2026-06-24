#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${BFA_DEPLOY_ROOT:-/opt/binance-futures-agent}"
ETC_DIR="${BFA_ETC_DIR:-/etc/binance-futures-agent}"
UNIT_PATH="/etc/systemd/system/binance-futures-agent.service"
LIVE_UNIT_PATH="/etc/systemd/system/binance-futures-agent-live.service"
LIVE_TIMER_PATH="/etc/systemd/system/binance-futures-agent-live.timer"
SENTINEL_UNIT_PATH="/etc/systemd/system/binance-futures-agent-position-sentinel.service"
SENTINEL_TIMER_PATH="/etc/systemd/system/binance-futures-agent-position-sentinel.timer"
PENDING_LIMIT_WATCHDOG_UNIT_PATH="/etc/systemd/system/binance-futures-agent-pending-limit-watchdog.service"
PENDING_LIMIT_WATCHDOG_TIMER_PATH="/etc/systemd/system/binance-futures-agent-pending-limit-watchdog.timer"
DB_MAINTENANCE_UNIT_PATH="/etc/systemd/system/binance-futures-agent-db-maintenance.service"
DB_MAINTENANCE_TIMER_PATH="/etc/systemd/system/binance-futures-agent-db-maintenance.timer"
RAW_FEED_UNIT_PATH="/etc/systemd/system/binance-futures-agent-raw-feed.service"
PAPER_UNIT_PATH="/etc/systemd/system/binance-futures-agent-paper.service"
PAPER_TIMER_PATH="/etc/systemd/system/binance-futures-agent-paper.timer"
ARCHIVE_PATH="${1:-}"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_isolated_paths() {
  [ "$APP_ROOT" = "/opt/binance-futures-agent" ] || die "refusing non-isolated APP_ROOT: $APP_ROOT"
  [ "$ETC_DIR" = "/etc/binance-futures-agent" ] || die "refusing non-isolated ETC_DIR: $ETC_DIR"
  [ "$UNIT_PATH" = "/etc/systemd/system/binance-futures-agent.service" ] || die "refusing unexpected unit path"
  [ "$LIVE_UNIT_PATH" = "/etc/systemd/system/binance-futures-agent-live.service" ] || die "refusing unexpected live unit path"
  [ "$LIVE_TIMER_PATH" = "/etc/systemd/system/binance-futures-agent-live.timer" ] || die "refusing unexpected live timer path"
  [ "$SENTINEL_UNIT_PATH" = "/etc/systemd/system/binance-futures-agent-position-sentinel.service" ] || die "refusing unexpected sentinel unit path"
  [ "$SENTINEL_TIMER_PATH" = "/etc/systemd/system/binance-futures-agent-position-sentinel.timer" ] || die "refusing unexpected sentinel timer path"
  [ "$PENDING_LIMIT_WATCHDOG_UNIT_PATH" = "/etc/systemd/system/binance-futures-agent-pending-limit-watchdog.service" ] || die "refusing unexpected pending-limit watchdog unit path"
  [ "$PENDING_LIMIT_WATCHDOG_TIMER_PATH" = "/etc/systemd/system/binance-futures-agent-pending-limit-watchdog.timer" ] || die "refusing unexpected pending-limit watchdog timer path"
  [ "$DB_MAINTENANCE_UNIT_PATH" = "/etc/systemd/system/binance-futures-agent-db-maintenance.service" ] || die "refusing unexpected db maintenance unit path"
  [ "$DB_MAINTENANCE_TIMER_PATH" = "/etc/systemd/system/binance-futures-agent-db-maintenance.timer" ] || die "refusing unexpected db maintenance timer path"
  [ "$RAW_FEED_UNIT_PATH" = "/etc/systemd/system/binance-futures-agent-raw-feed.service" ] || die "refusing unexpected raw-feed unit path"
  [ "$PAPER_UNIT_PATH" = "/etc/systemd/system/binance-futures-agent-paper.service" ] || die "refusing unexpected paper unit path"
  [ "$PAPER_TIMER_PATH" = "/etc/systemd/system/binance-futures-agent-paper.timer" ] || die "refusing unexpected paper timer path"
}

install_system_dependencies() {
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y python3 python3-venv python-is-python3 sqlite3 ca-certificates
    return 0
  fi
  command -v python3 >/dev/null 2>&1 || die "python3 is required"
  command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 is required"
}

prepare_directories() {
  install -d -m 0755 "$APP_ROOT"
  install -d -m 0755 "$APP_ROOT/app"
  install -d -m 0700 "$APP_ROOT/data"
  install -d -m 0700 "$APP_ROOT/data/raw-feed"
  install -d -m 0700 "$APP_ROOT/logs"
  install -d -m 0700 "$APP_ROOT/runtime"
  install -d -m 0700 "$APP_ROOT/runtime/square_exports"
  install -d -m 0755 "$ETC_DIR"
}

install_source_archive() {
  [ -n "$ARCHIVE_PATH" ] || return 0
  [ -f "$ARCHIVE_PATH" ] || die "source archive not found: $ARCHIVE_PATH"

  rm -rf "$APP_ROOT/app.new"
  install -d -m 0755 "$APP_ROOT/app.new"
  tar -xzf "$ARCHIVE_PATH" -C "$APP_ROOT/app.new"
  rm -rf "$APP_ROOT/app"
  mv "$APP_ROOT/app.new" "$APP_ROOT/app"
}

install_env_placeholder() {
  if [ ! -f "$ETC_DIR/env" ]; then
    tr -d '\r' < "$APP_ROOT/app/deploy/server-env.example" > "$ETC_DIR/env"
    chmod 0600 "$ETC_DIR/env"
  else
    tmp_env="$(mktemp)"
    tr -d '\r' < "$ETC_DIR/env" > "$tmp_env"
    cat "$tmp_env" > "$ETC_DIR/env"
    rm -f "$tmp_env"
    chmod 0600 "$ETC_DIR/env"
  fi
}

install_python_environment() {
  python3 -m venv "$APP_ROOT/.venv"
  "$APP_ROOT/.venv/bin/python" -m pip install --upgrade pip
  "$APP_ROOT/.venv/bin/python" -m pip install -e "$APP_ROOT/app"
}

install_systemd_unit() {
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent.service" "$UNIT_PATH"
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent-live.service" "$LIVE_UNIT_PATH"
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent-live.timer" "$LIVE_TIMER_PATH"
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent-position-sentinel.service" "$SENTINEL_UNIT_PATH"
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent-position-sentinel.timer" "$SENTINEL_TIMER_PATH"
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent-pending-limit-watchdog.service" "$PENDING_LIMIT_WATCHDOG_UNIT_PATH"
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent-pending-limit-watchdog.timer" "$PENDING_LIMIT_WATCHDOG_TIMER_PATH"
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent-db-maintenance.service" "$DB_MAINTENANCE_UNIT_PATH"
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent-db-maintenance.timer" "$DB_MAINTENANCE_TIMER_PATH"
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent-raw-feed.service" "$RAW_FEED_UNIT_PATH"
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent-paper.service" "$PAPER_UNIT_PATH"
  install -m 0644 "$APP_ROOT/app/deploy/systemd/binance-futures-agent-paper.timer" "$PAPER_TIMER_PATH"
  systemctl daemon-reload
}

main() {
  require_isolated_paths
  install_system_dependencies
  prepare_directories
  install_source_archive
  install_env_placeholder
  install_python_environment
  install_systemd_unit
  printf 'Bootstrap complete. Edit %s, then run health checks before enabling live mode.\n' "$ETC_DIR/env"
}

main "$@"
