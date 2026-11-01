"""Tests for the safe one-task LAB example wrapper."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from examples import run_single_lab


class SingleLabExampleTests(unittest.TestCase):
    def test_execute_requires_explicit_paid_approval(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            run_single_lab.main(["--execute"])
        self.assertEqual(error.exception.code, 2)

    def test_show_result_prints_scores_artifact_and_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            run_id = "lab-oc-agg1/example/task/agg1"
            artifact = output / "lab/results/oc" / run_id / "workspace/output/answer.txt"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("visible deliverable")
            (output / "results.json").write_text(
                json.dumps(
                    {
                        "summaries": {"summary.json": {"task_id": "example/task", "status": "ok"}},
                        "refined_scores": {
                            "judged.json": [
                                {"run_id": run_id, "n_passed": 9, "n_criteria": 10}
                            ]
                        },
                        "initial_scores": {
                            "base_judged.json": [
                                {"score": {"n_passed": 7, "n_criteria": 10}}
                            ]
                        },
                    }
                )
            )
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = run_single_lab.show_result(output, 100)
            self.assertEqual(code, 0)
            self.assertIn("Initial score: 7/10 (70%)", stream.getvalue())
            self.assertIn("Refined score: 9/10 (90%)", stream.getvalue())
            self.assertIn("visible deliverable", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
