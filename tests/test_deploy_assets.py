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
            "X_BEARER_TOKEN",
            "TELEGRAM_BOT_TOKEN",
        ):
            self.assertRegex(text, rf"(?m)^{key}=$")
        self.assertIn("BFA_MODE=dry_run", text)
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

    def test_deployment_docs_preserve_dry_run_first_posture(self):
        docs = (DOCS / "deployment.md").read_text(encoding="utf-8")

        self.assertIn("BFA_MODE=dry_run", docs)
        self.assertIn("Preview mode", docs)
        self.assertIn("Live activation is a separate", docs)
        self.assertNotIn("BFA_MODE=live", docs)
        self.assertNotIn("ssh root@", docs)

    def test_systemd_unit_uses_project_isolated_paths(self):
        unit = self.read("systemd", "binance-futures-agent.service")

        self.assertIn("WorkingDirectory=/opt/binance-futures-agent/app", unit)
        self.assertIn("EnvironmentFile=/etc/binance-futures-agent/env", unit)
        self.assertIn("/opt/binance-futures-agent/.venv/bin/python -m bfa.cli ops health-check", unit)
        self.assertIn("ReadWritePaths=/opt/binance-futures-agent /etc/binance-futures-agent", unit)
        self.assertNotIn("BFA_MODE=live", unit)

    def test_remote_bootstrap_is_path_allowlisted_and_not_auto_enabled(self):
        script = self.read("remote-bootstrap.sh")

        self.assertIn('APP_ROOT="${BFA_DEPLOY_ROOT:-/opt/binance-futures-agent}"', script)
        self.assertIn('ETC_DIR="${BFA_ETC_DIR:-/etc/binance-futures-agent}"', script)
        self.assertIn('UNIT_PATH="/etc/systemd/system/binance-futures-agent.service"', script)
        self.assertIn('refusing non-isolated APP_ROOT', script)
        self.assertIn('refusing non-isolated ETC_DIR', script)
        self.assertIn("tr -d '\\r'", script)
        self.assertNotRegex(script, re.compile(r"systemctl\s+(enable|start|restart)\b"))


if __name__ == "__main__":
    unittest.main()
