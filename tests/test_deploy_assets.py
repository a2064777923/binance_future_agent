import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
SCRIPTS = ROOT / "scripts"
DOCS = ROOT / "docs"


class DeployAssetTests(unittest.TestCase):
    def read(self, *parts):
        return (DEPLOY.joinpath(*parts)).read_text(encoding="utf-8")

    def test_linux_deploy_assets_use_lf_line_endings(self):
        paths = [
            *DEPLOY.rglob("*.sh"),
            *DEPLOY.joinpath("systemd").glob("*"),
            DEPLOY / "server-env.example",
            ROOT / ".env.example",
        ]

        for path in paths:
            if path.is_file():
                self.assertNotIn(b"\r\n", path.read_bytes(), f"{path} must use LF line endings")

    def test_server_env_example_has_empty_secret_values(self):
        text = self.read("server-env.example")

        for key in (
            "BINANCE_API_KEY",
            "BINANCE_API_SECRET",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "X_BEARER_TOKEN",
            "TELEGRAM_BOT_TOKEN",
        ):
            self.assertRegex(text, rf"(?m)^{key}=$")
        self.assertIn("BFA_MODE=dry_run", text)
        self.assertIn("BFA_AI_FALLBACK_TO_QUANT_ENABLED=true", text)
        self.assertIn("BFA_REQUIRE_PROTECTIVE_ORDERS=true", text)
        self.assertIn("BFA_MARKET_HEAT_NARRATIVE_ENABLED=true", text)
        self.assertIn("BFA_MANUAL_POSITION_SYMBOLS=", text)
        self.assertIn("BFA_LIVE_AUTO_HOT_SYMBOLS=true", text)
        self.assertIn("BFA_LIVE_AUTO_HOT_TOP_N=80", text)
        self.assertIn("BFA_LIVE_REQUIRE_NARRATIVE_EVIDENCE=false", text)
        self.assertIn("BFA_LIVE_CANDIDATE_SCORE_MODE=market_momentum", text)
        self.assertIn("BFA_LIVE_CANDIDATE_MIN_QUOTE_VOLUME_USDT=10000000", text)
        self.assertIn("BFA_LIVE_CANDIDATE_MAX_KLINE_RANGE_PERCENT=12", text)
        self.assertIn("BFA_LIVE_QUANT_SETUP_VARIANT=quant_setup_live_action_flow", text)
        self.assertIn("BFA_REGIME_ROUTER_ENABLED=true", text)
        self.assertIn("BFA_REGIME_ROUTER_SHADOW_ONLY=true", text)
        self.assertIn("BFA_LIVE_OUTCOME_GUARD_ENABLED=true", text)
        self.assertIn("BFA_LIVE_OUTCOME_GUARD_MIN_SYMBOL_OUTCOMES=5", text)
        self.assertIn("BFA_LIVE_OUTCOME_GUARD_SYMBOL_MIN_LOSS_USDT=0.25", text)
        self.assertIn("BFA_LIVE_OUTCOME_GUARD_SYMBOL_MODE=downsize", text)
        self.assertIn("BFA_LIVE_OUTCOME_GUARD_MIN_SIDE_OUTCOMES=6", text)
        self.assertIn("BFA_LIVE_OUTCOME_GUARD_SIDE_MODE=downsize", text)
        self.assertIn("BFA_FORWARD_PAPER_AUTO_HOT_SYMBOLS=true", text)
        self.assertIn("BFA_FORWARD_PAPER_TOP_N=40", text)
        self.assertIn("BFA_FORWARD_PAPER_GUARD_ENABLED=true", text)
        self.assertIn("BFA_FORWARD_PAPER_GUARD_MIN_TOTAL_OUTCOMES=30", text)
        self.assertIn("BFA_FORWARD_PAPER_GUARD_FACTOR_MODE=downsize", text)
        self.assertIn("BFA_FORWARD_PAPER_GUARD_FACTOR_DOWNSIZE_MULTIPLIER=0.65", text)
        self.assertIn("BFA_FORWARD_PAPER_GUARD_FACTOR_EXEMPT_REASONS=", text)
        self.assertIn("OPENAI_BASE_URL=https://api.openai.com/v1", text)
        self.assertIn("OPENAI_TIMEOUT_SECONDS=5", text)
        self.assertIn("OPENAI_MAX_OUTPUT_TOKENS=400", text)
        self.assertIn("OPENAI_RETRY_AFTER_SECONDS=300", text)
        self.assertIn("DEEPSEEK_BASE_URL=https://api.deepseek.com", text)
        self.assertIn("DEEPSEEK_MODEL=deepseek-v4-flash", text)
        self.assertIn("BFA_DB_PATH=/opt/binance-futures-agent/data/agent.sqlite", text)

    def test_deploy_assets_do_not_reference_forbidden_paths_or_secrets(self):
        forbidden = [
            "F:\\stock",
            "/opt/stock",
            "stock.service",
            "crontab",
            "server-password",
            "sshpass",
        ]
        for base in (DEPLOY, SCRIPTS, DOCS):
            for path in base.rglob("*"):
                if "__pycache__" in path.parts:
                    continue
                if path.is_file():
                    text = path.read_text(encoding="utf-8")
                    for value in forbidden:
                        self.assertNotIn(value, text, f"{value} found in {path}")

    def test_deploy_script_defaults_to_preview_and_requires_apply(self):
        script = (SCRIPTS / "deploy-server.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$Apply", script)
        self.assertIn("Preview only. Re-run with -Apply", script)
        self.assertIn('if ($Apply)', script)
        self.assertIn('"/opt/binance-futures-agent"', script)
        self.assertIn('"/etc/binance-futures-agent"', script)
        self.assertNotIn("-pw", script.lower())
        self.assertNotIn("sshpass", script.lower())

    def test_server_readiness_script_is_preview_first_and_read_only(self):
        script = (SCRIPTS / "run-server-readiness.ps1").read_text(encoding="utf-8")

        self.assertIn("[switch]$Run", script)
        self.assertIn("Preview only. Re-run with -Run", script)
        self.assertIn("BatchMode=yes", script)
        self.assertIn('"/opt/binance-futures-agent"', script)
        self.assertIn('"/etc/binance-futures-agent"', script)
        self.assertIn("ops\", \"live-resume-readiness", script)
        self.assertIn("--manual-exposure-symbols", script)
        self.assertIn("ETHUSDT", script)
        self.assertIn("quant_setup_selective_guarded", script)
        self.assertIn("bfa_live_resume_readiness_v1", script)
        self.assertNotRegex(script, re.compile(r"systemctl\s+(enable|start|restart|stop|disable)\b"))
        self.assertNotIn("risk-profile-apply", script)
        self.assertNotIn("time-exit-execute", script)
        self.assertNotIn("agent run-once", script)
        self.assertNotIn("-pw", script.lower())
        self.assertNotIn("sshpass", script.lower())

    def test_deployment_docs_preserve_dry_run_first_posture(self):
        docs = (DOCS / "deployment.md").read_text(encoding="utf-8")

        self.assertIn("BFA_MODE=dry_run", docs)
        self.assertIn("Preview mode", docs)
        self.assertIn("BFA_MODE=live", docs)
        self.assertIn("binance-futures-agent-live.timer", docs)
        self.assertIn("BFA_REQUIRE_PROTECTIVE_ORDERS=true", docs)
        self.assertIn("BFA_MARKET_HEAT_NARRATIVE_ENABLED=true", docs)
        self.assertIn("OPENAI_BASE_URL=https://api.openai.com/v1", docs)
        self.assertIn("OPENAI_TIMEOUT_SECONDS=5", docs)
        self.assertIn("openai_backoff.json", docs)
        self.assertIn("fail closed", docs)
        self.assertNotIn("ssh root@", docs)

    def test_systemd_unit_uses_project_isolated_paths(self):
        unit = self.read("systemd", "binance-futures-agent.service")
        live_unit = self.read("systemd", "binance-futures-agent-live.service")
        live_timer = self.read("systemd", "binance-futures-agent-live.timer")
        sentinel_unit = self.read("systemd", "binance-futures-agent-position-sentinel.service")
        sentinel_timer = self.read("systemd", "binance-futures-agent-position-sentinel.timer")
        pending_watchdog_unit = self.read("systemd", "binance-futures-agent-pending-limit-watchdog.service")
        pending_watchdog_timer = self.read("systemd", "binance-futures-agent-pending-limit-watchdog.timer")
        db_maintenance_unit = self.read("systemd", "binance-futures-agent-db-maintenance.service")
        db_maintenance_timer = self.read("systemd", "binance-futures-agent-db-maintenance.timer")
        outcome_reconcile_unit = self.read("systemd", "binance-futures-agent-outcome-reconcile.service")
        outcome_reconcile_timer = self.read("systemd", "binance-futures-agent-outcome-reconcile.timer")
        raw_feed_unit = self.read("systemd", "binance-futures-agent-raw-feed.service")
        paper_unit = self.read("systemd", "binance-futures-agent-paper.service")
        paper_timer = self.read("systemd", "binance-futures-agent-paper.timer")

        self.assertIn("WorkingDirectory=/opt/binance-futures-agent/app", unit)
        self.assertIn("EnvironmentFile=/etc/binance-futures-agent/env", unit)
        self.assertIn("/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops health-check", unit)
        self.assertIn("ReadWritePaths=/opt/binance-futures-agent /etc/binance-futures-agent", unit)
        self.assertNotIn("BFA_MODE=live", unit)
        self.assertIn("WorkingDirectory=/opt/binance-futures-agent/app", live_unit)
        self.assertIn("EnvironmentFile=/etc/binance-futures-agent/env", live_unit)
        self.assertIn("/opt/binance-futures-agent/.venv/bin/python -m bfa.cli agent run-once", live_unit)
        self.assertIn("--top-n 20", live_unit)
        self.assertIn("OnUnitActiveSec=2min", live_timer)
        self.assertIn("Unit=binance-futures-agent-live.service", live_timer)
        self.assertIn("WorkingDirectory=/opt/binance-futures-agent/app", sentinel_unit)
        self.assertIn("EnvironmentFile=/etc/binance-futures-agent/env", sentinel_unit)
        self.assertIn("/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops position-sentinel", sentinel_unit)
        self.assertIn("--execute", sentinel_unit)
        self.assertIn("OnUnitActiveSec=5s", sentinel_timer)
        self.assertIn("Unit=binance-futures-agent-position-sentinel.service", sentinel_timer)
        self.assertIn("WorkingDirectory=/opt/binance-futures-agent/app", pending_watchdog_unit)
        self.assertIn("EnvironmentFile=/etc/binance-futures-agent/env", pending_watchdog_unit)
        self.assertIn("/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops pending-limit-watchdog", pending_watchdog_unit)
        self.assertIn("--execute", pending_watchdog_unit)
        self.assertIn("OnUnitActiveSec=10s", pending_watchdog_timer)
        self.assertIn("Unit=binance-futures-agent-pending-limit-watchdog.service", pending_watchdog_timer)
        self.assertIn("WorkingDirectory=/opt/binance-futures-agent/app", db_maintenance_unit)
        self.assertIn("EnvironmentFile=/etc/binance-futures-agent/env", db_maintenance_unit)
        self.assertIn("/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops db-maintenance", db_maintenance_unit)
        self.assertIn("--execute --batch-size 5000 --max-delete-rows 25000 --clean-raw-feed", db_maintenance_unit)
        self.assertIn("OnUnitActiveSec=1h", db_maintenance_timer)
        self.assertIn("Unit=binance-futures-agent-db-maintenance.service", db_maintenance_timer)
        self.assertIn("WorkingDirectory=/opt/binance-futures-agent/app", outcome_reconcile_unit)
        self.assertIn("EnvironmentFile=/etc/binance-futures-agent/env", outcome_reconcile_unit)
        self.assertIn("/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops reconcile-outcomes", outcome_reconcile_unit)
        self.assertIn("--persist-closed --lookback-hours 72 --limit 500 --summary-only", outcome_reconcile_unit)
        self.assertIn("ReadWritePaths=/opt/binance-futures-agent/data", outcome_reconcile_unit)
        self.assertIn("OnUnitActiveSec=1min", outcome_reconcile_timer)
        self.assertIn("Unit=binance-futures-agent-outcome-reconcile.service", outcome_reconcile_timer)
        self.assertIn("WorkingDirectory=/opt/binance-futures-agent/app", raw_feed_unit)
        self.assertIn("EnvironmentFile=/etc/binance-futures-agent/env", raw_feed_unit)
        self.assertIn("/opt/binance-futures-agent/app/deploy/record-raw-feed-loop.sh", raw_feed_unit)
        self.assertIn("WorkingDirectory=/opt/binance-futures-agent/app", paper_unit)
        self.assertIn("EnvironmentFile=/etc/binance-futures-agent/env", paper_unit)
        self.assertIn("/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops forward-paper-run", paper_unit)
        self.assertIn("--auto-hot-symbols", paper_unit)
        self.assertIn("--top-n 40", paper_unit)
        self.assertNotIn("--symbols HYPEUSDT,SOLUSDT,ZECUSDT", paper_unit)
        self.assertNotIn("agent run-once", paper_unit)
        self.assertIn("OnUnitActiveSec=5min", paper_timer)
        self.assertIn("Unit=binance-futures-agent-paper.service", paper_timer)

    def test_remote_bootstrap_is_path_allowlisted_and_not_auto_enabled(self):
        script = self.read("remote-bootstrap.sh")

        self.assertIn('APP_ROOT="${BFA_DEPLOY_ROOT:-/opt/binance-futures-agent}"', script)
        self.assertIn('ETC_DIR="${BFA_ETC_DIR:-/etc/binance-futures-agent}"', script)
        self.assertIn('UNIT_PATH="/etc/systemd/system/binance-futures-agent.service"', script)
        self.assertIn('LIVE_UNIT_PATH="/etc/systemd/system/binance-futures-agent-live.service"', script)
        self.assertIn('LIVE_TIMER_PATH="/etc/systemd/system/binance-futures-agent-live.timer"', script)
        self.assertIn('SENTINEL_UNIT_PATH="/etc/systemd/system/binance-futures-agent-position-sentinel.service"', script)
        self.assertIn('SENTINEL_TIMER_PATH="/etc/systemd/system/binance-futures-agent-position-sentinel.timer"', script)
        self.assertIn('PENDING_LIMIT_WATCHDOG_UNIT_PATH="/etc/systemd/system/binance-futures-agent-pending-limit-watchdog.service"', script)
        self.assertIn('PENDING_LIMIT_WATCHDOG_TIMER_PATH="/etc/systemd/system/binance-futures-agent-pending-limit-watchdog.timer"', script)
        self.assertIn('DB_MAINTENANCE_UNIT_PATH="/etc/systemd/system/binance-futures-agent-db-maintenance.service"', script)
        self.assertIn('DB_MAINTENANCE_TIMER_PATH="/etc/systemd/system/binance-futures-agent-db-maintenance.timer"', script)
        self.assertIn('OUTCOME_RECONCILE_UNIT_PATH="/etc/systemd/system/binance-futures-agent-outcome-reconcile.service"', script)
        self.assertIn('OUTCOME_RECONCILE_TIMER_PATH="/etc/systemd/system/binance-futures-agent-outcome-reconcile.timer"', script)
        self.assertIn('RAW_FEED_UNIT_PATH="/etc/systemd/system/binance-futures-agent-raw-feed.service"', script)
        self.assertIn('PAPER_UNIT_PATH="/etc/systemd/system/binance-futures-agent-paper.service"', script)
        self.assertIn('PAPER_TIMER_PATH="/etc/systemd/system/binance-futures-agent-paper.timer"', script)
        self.assertIn('refusing non-isolated APP_ROOT', script)
        self.assertIn('refusing non-isolated ETC_DIR', script)
        self.assertIn('python3 python3-venv python-is-python3 sqlite3 ca-certificates', script)
        self.assertIn('install -d -m 0700 "$APP_ROOT/data/raw-feed"', script)
        self.assertIn("tr -d '\\r'", script)
        self.assertNotRegex(script, re.compile(r"systemctl\s+(enable|start|restart)\b"))


if __name__ == "__main__":
    unittest.main()
