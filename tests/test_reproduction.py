"""Regression checks for approval guards, immutable experiments, and usage capture."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import reproduce_lab as reproduction


class ReproductionTests(unittest.TestCase):
    def test_paid_stages_require_explicit_approval_before_preparation(self):
        for stage in ("run", "judge", "judge-bases"):
            with (
                self.subTest(stage=stage),
                patch.object(reproduction, "manifest") as prepare,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                reproduction.main([stage])
            self.assertEqual(error.exception.code, 2)
            prepare.assert_not_called()

    def test_changed_manifest_preserves_previous_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            identity = {
                "task_prompt": "original",
                "prompt_profile": {},
                "base_harness_snapshot": {},
            }
            reproduction.persist_manifest(output, identity)
            reproduction.persist_manifest(output, identity)
            with self.assertRaisesRegex(ValueError, "fresh --output"):
                reproduction.persist_manifest(output, dict(identity, task_prompt="different"))
            self.assertEqual((output / "prompts/task.md").read_text(), "original")
            self.assertEqual(json.loads((output / "manifest.json").read_text()), identity)

    def test_cloud_guard_rejects_disabled_api_and_inaccessible_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "audit.json"
            reproduction.dump(
                report,
                {
                    "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                    "cloud": {
                        "adc": "PASS",
                        "projects": [
                            {
                                "project_id": "test-project",
                                "vertex_api": "DISABLED",
                                "billing_enabled": True,
                                "granted_permissions": [
                                    "aiplatform.endpoints.predict",
                                    "serviceusage.services.use",
                                ],
                            }
                        ],
                    },
                },
            )
            with patch.object(reproduction.config, "VERTEX_PROJECT", "test-project"):
                with self.assertRaisesRegex(ValueError, "Cloud audit"):
                    reproduction.require_cloud_audit(report)
            with patch.object(reproduction.config, "VERTEX_PROJECT", "inaccessible-project"):
                with self.assertRaisesRegex(ValueError, "Cloud audit"):
                    reproduction.require_cloud_audit(report)

    def test_usage_capture_forwards_response_but_stores_only_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher = root / "launcher"
            launcher.write_text(
                f"#!{sys.executable}\nimport os,sys\nos.execv(sys.argv[4],sys.argv[4:])\n"
            )
            launcher.chmod(0o700)
            fake_bun = root / "local-agent"
            event = {"part": {"type": "step-finish", "tokens": {"input": 10}, "cost": 0.1}}
            fake_bun.write_text(
                f"#!{sys.executable}\nprint('private-response-text')\nprint({json.dumps(event)!r})\n"
            )
            fake_bun.chmod(0o700)
            record = reproduction.ROOT / "scripts/record_agent_usage.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(record),
                    "--launcher",
                    str(launcher),
                    "--bun",
                    str(fake_bun),
                    "--telemetry",
                    str(root / "usage"),
                    "--",
                    "run",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("private-response-text", completed.stdout)
            usage_file = next((root / "usage").glob("*.json"))
            self.assertNotIn("private-response-text", usage_file.read_text())
            usage = json.loads(usage_file.read_text())
            self.assertEqual(usage["usage_events"][0]["tokens"]["input"], 10)


if __name__ == "__main__":
    unittest.main()
