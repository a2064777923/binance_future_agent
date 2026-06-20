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
        self.assertIn("BFA_REQUIRE_PROTECTIVE_ORDERS=true", text)
        self.assertIn("BFA_MARKET_HEAT_NARRATIVE_ENABLED=true", text)
        self.assertIn("BFA_LIVE_AUTO_HOT_SYMBOLS=false", text)
        self.assertIn("BFA_LIVE_AUTO_HOT_TOP_N=40", text)
        self.assertIn("BFA_FORWARD_PAPER_AUTO_HOT_SYMBOLS=true", text)
        self.assertIn("BFA_FORWARD_PAPER_TOP_N=40", text)
        self.assertIn("BFA_FORWARD_PAPER_GUARD_ENABLED=true", text)
        self.assertIn("BFA_FORWARD_PAPER_GUARD_MIN_TOTAL_OUTCOMES=30", text)
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
        self.assertIn("OnUnitActiveSec=5min", live_timer)
        self.assertIn("Unit=binance-futures-agent-live.service", live_timer)
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
        self.assertIn('PAPER_UNIT_PATH="/etc/systemd/system/binance-futures-agent-paper.service"', script)
        self.assertIn('PAPER_TIMER_PATH="/etc/systemd/system/binance-futures-agent-paper.timer"', script)
        self.assertIn('refusing non-isolated APP_ROOT', script)
        self.assertIn('refusing non-isolated ETC_DIR', script)
        self.assertIn("tr -d '\\r'", script)
        self.assertNotRegex(script, re.compile(r"systemctl\s+(enable|start|restart)\b"))


if __name__ == "__main__":
    unittest.main()
