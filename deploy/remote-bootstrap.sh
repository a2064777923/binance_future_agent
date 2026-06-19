#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${BFA_DEPLOY_ROOT:-/opt/binance-futures-agent}"
ETC_DIR="${BFA_ETC_DIR:-/etc/binance-futures-agent}"
UNIT_PATH="/etc/systemd/system/binance-futures-agent.service"
ARCHIVE_PATH="${1:-}"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_isolated_paths() {
  [ "$APP_ROOT" = "/opt/binance-futures-agent" ] || die "refusing non-isolated APP_ROOT: $APP_ROOT"
  [ "$ETC_DIR" = "/etc/binance-futures-agent" ] || die "refusing non-isolated ETC_DIR: $ETC_DIR"
  [ "$UNIT_PATH" = "/etc/systemd/system/binance-futures-agent.service" ] || die "refusing unexpected unit path"
}

prepare_directories() {
  install -d -m 0755 "$APP_ROOT"
  install -d -m 0755 "$APP_ROOT/app"
  install -d -m 0700 "$APP_ROOT/data"
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
    install -m 0600 "$APP_ROOT/app/deploy/server-env.example" "$ETC_DIR/env"
  else
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
  systemctl daemon-reload
}

main() {
  require_isolated_paths
  prepare_directories
  install_source_archive
  install_env_placeholder
  install_python_environment
  install_systemd_unit
  printf 'Bootstrap complete. Edit %s, then run health checks before enabling live mode.\n' "$ETC_DIR/env"
}

main "$@"
