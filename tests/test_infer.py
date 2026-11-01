"""Check that the inference example validates setup before starting paid sessions."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from examples import infer
from harness2.core.proposer import ProposerError, Reply


class InferenceTests(unittest.TestCase):
    def test_missing_vertex_project_stops_before_credentials_or_model_calls(self):
        with (
            patch.object(infer.config, "VERTEX_PROJECT", ""),
            patch.object(infer.subprocess, "run") as credentials,
            patch.object(infer, "Proposer") as proposer,
            contextlib.redirect_stderr(io.StringIO()) as error,
        ):
            code = infer.main(["--model", "google-vertex/test-model"])
        self.assertEqual(code, 1)
        self.assertIn("GOOGLE_CLOUD_PROJECT", error.getvalue())
        credentials.assert_not_called()
        proposer.assert_not_called()

    def test_check_only_never_constructs_a_proposer_or_output_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "should-not-exist"
            with (
                patch.object(infer, "check_ready"),
                patch.object(infer, "Proposer") as proposer,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = infer.main(["--check-only", "--output", str(output)])
            self.assertEqual(code, 0)
            proposer.assert_not_called()
            self.assertFalse(output.exists())

    def test_success_saves_response_and_uses_selected_model(self):
        reply = Reply("inference", "42", True, attempts=1)
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(infer, "check_ready"),
                patch.object(infer, "Proposer") as proposer,
                contextlib.redirect_stdout(io.StringIO()) as out,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                proposer.return_value.call.return_value = reply
                code = infer.main(["--model", "test/model", "--output", tmp])
            self.assertEqual(code, 0)
            self.assertEqual(out.getvalue().strip(), "42")
            self.assertEqual((Path(tmp) / "response.txt").read_text(), "42\n")
            result = json.loads((Path(tmp) / "result.json").read_text())
            self.assertEqual((result["model"], result["response"]), ("test/model", "42"))
            self.assertEqual(proposer.call_args.args[0].model, "test/model")
            self.assertEqual(proposer.call_args.kwargs["attempts"], 1)

    def test_failed_credentials_do_not_expose_token_output(self):
        with (
            patch.object(infer.config, "VERTEX_PROJECT", "test-project"),
            patch.object(infer.OpencodeSubstrate, "preflight"),
            patch.object(
                infer.subprocess,
                "run",
                return_value=Mock(
                    returncode=1, stdout="sensitive-token", stderr="sensitive-diagnostic"
                ),
            ),
            contextlib.redirect_stderr(io.StringIO()) as error,
        ):
            code = infer.main(["--model", "google-vertex/test-model", "--check-only"])
        self.assertEqual(code, 1)
        self.assertIn("ADC refresh failed", error.getvalue())
        self.assertNotIn("sensitive", error.getvalue())

    def test_failed_model_session_returns_nonzero(self):
        with (
            patch.object(infer, "check_ready"),
            patch.object(infer, "Proposer") as proposer,
            contextlib.redirect_stderr(io.StringIO()) as error,
        ):
            proposer.return_value.call.side_effect = ProposerError("model unavailable")
            self.assertEqual(infer.main(["--model", "test/model"]), 1)
        self.assertIn("model unavailable", error.getvalue())


if __name__ == "__main__":
    unittest.main()
