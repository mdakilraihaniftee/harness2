"""No-network coverage for multi-model routing and experiment isolation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness2 import config
from harness2.cli import _common as C
from harness2.core.proposer import _opencode_usage
from harness2.harness_registry import resolve_harness
from harness2.model_config import (
    parse_model_ref,
    provider_environment,
    redact,
    resolve_run_model_config,
)
from harness2.substrate.codex import CodexSubstrate
from harness2.substrate.opencode import OpencodeSubstrate


class MultiModelTests(unittest.TestCase):
    def profile_file(self, body: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix="h2-model-test-"))
        path = root / "profiles.toml"
        path.write_text(body, encoding="utf-8")
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        return path

    @staticmethod
    def env(**extra) -> dict[str, str]:
        base = {
            "HARNESS2_SOLVER_MODEL": "google-vertex/gemini-test",
            "HARNESS2_IMPROVER_MODEL": "google-vertex/gemini-test",
            "HARNESS2_JUDGE_MODEL": "gemini-judge",
            "GOOGLE_CLOUD_PROJECT": "test-project",
        }
        base.update(extra)
        return base

    def test_01_model_profile_parsing(self):
        path = self.profile_file(
            '[profiles.p]\nharness="opencode"\nsolver="openai/gpt-test"\n'
            'improver="openrouter/qwen/org/model"\njudge="openai/judge-test"\n'
        )
        got = resolve_run_model_config(profile="p", profiles_path=path, env=self.env())
        self.assertEqual(got.solver.ref, "openai/gpt-test")
        self.assertEqual(got.improver.model_id, "qwen/org/model")

    def test_02_cli_override_precedence(self):
        path = self.profile_file(
            '[profiles.p]\nsolver="openai/profile"\nimprover="openai/profile"\n'
        )
        got = resolve_run_model_config(
            profile="p", profiles_path=path, solver_model="openai/cli", env=self.env()
        )
        self.assertEqual(got.solver.model_id, "cli")
        self.assertEqual(got.improver.model_id, "profile")

    def test_03_provider_identifier_parsing(self):
        got = parse_model_ref("openai/model-name")
        self.assertEqual((got.provider, got.model_id), ("openai", "model-name"))

    def test_04_openrouter_multisegment_identifier(self):
        got = parse_model_ref("openrouter/qwen/team/model:free")
        self.assertEqual(got.model_id, "qwen/team/model:free")

    def test_05_qwen_provider_configuration(self):
        got = resolve_run_model_config(
            model="openrouter/qwen/verified-id",
            judge_model="openai/judge",
            env=self.env(OPENROUTER_API_KEY="secret", OPENAI_API_KEY="judge"),
        )
        self.assertEqual(got.solver.provider, "openrouter")
        self.assertEqual(got.selector.ref, got.improver.ref)

    def test_06_openai_provider_configuration(self):
        got = resolve_run_model_config(
            model="openai/verified-id", judge_model="openai/judge", env=self.env()
        )
        self.assertEqual(got.solver.credential_env, "OPENAI_API_KEY")

    def test_07_vertex_legacy_backward_compatibility(self):
        got = resolve_run_model_config(env=self.env())
        self.assertEqual(got.solver.ref, "google-vertex/gemini-test")
        self.assertEqual(got.judge.ref, "google-vertex/gemini-judge")

    def test_08_provider_credential_isolation(self):
        source = {
            "PATH": "/bin",
            "OPENAI_API_KEY": "openai-secret",
            "OPENROUTER_API_KEY": "router-secret",
            "ANTHROPIC_API_KEY": "anthropic-secret",
        }
        got = provider_environment(parse_model_ref("openai/model"), source)
        self.assertEqual(got["OPENAI_API_KEY"], "openai-secret")
        self.assertNotIn("OPENROUTER_API_KEY", got)
        self.assertNotIn("ANTHROPIC_API_KEY", got)

    def test_09_missing_credential_error(self):
        with self.assertRaisesRegex(config.ConfigError, "OPENAI_API_KEY"):
            provider_environment(parse_model_ref("openai/model"), {}, require_credential=True)

    def test_10_unsupported_runtime_combination(self):
        with self.assertRaisesRegex(config.ConfigError, "Codex solver"):
            resolve_run_model_config(
                harness="codex",
                solver_model="openrouter/qwen/model",
                improver_model="openai/editor",
                judge_model="openai/judge",
                env=self.env(),
            )

    def test_11_solver_improver_separation(self):
        got = resolve_run_model_config(
            solver_model="openrouter/qwen/model",
            improver_model="openai/editor",
            judge_model="openai/judge",
            env=self.env(),
        )
        self.assertNotEqual(got.solver.ref, got.improver.ref)

    def test_12_selector_and_judge_separation(self):
        got = resolve_run_model_config(
            model="openai/common",
            selector_model="anthropic/selector",
            judge_model="google-vertex/judge",
            env=self.env(),
        )
        self.assertEqual(got.selector.provider, "anthropic")
        self.assertEqual(got.judge.provider, "google-vertex")

    def test_13_fingerprint_stability_and_secret_exclusion(self):
        kwargs = dict(model="openai/model", judge_model="openai/judge")
        one = resolve_run_model_config(env=self.env(OPENAI_API_KEY="one"), **kwargs)
        two = resolve_run_model_config(env=self.env(OPENAI_API_KEY="two"), **kwargs)
        self.assertEqual(one.fingerprint, two.fingerprint)
        self.assertNotIn("one", json.dumps(one.safe_dict()))
        vertex_a = resolve_run_model_config(env=self.env(GOOGLE_CLOUD_PROJECT="project-a"))
        vertex_b = resolve_run_model_config(env=self.env(GOOGLE_CLOUD_PROJECT="project-b"))
        self.assertNotEqual(vertex_a.fingerprint, vertex_b.fingerprint)

    def test_14_cross_model_cache_isolation(self):
        a = resolve_run_model_config(model="openai/a", judge_model="openai/j", env=self.env())
        b = resolve_run_model_config(model="openai/b", judge_model="openai/j", env=self.env())
        aa = C.make_adapter("lab", None, "oc", run_config=a)
        bb = C.make_adapter("lab", None, "oc", run_config=b)
        self.assertNotEqual(aa.spec.runs_root, bb.spec.runs_root)

    def test_15_legacy_run_layout_remains_constructible(self):
        adapter = C.make_adapter("lab", None, "oc")
        self.assertNotIn("model-config-", str(adapter.spec.runs_root))

    def test_16_benchmark_judge_mapping(self):
        got = resolve_run_model_config(
            model="openai/solver", judge_model="google-vertex/judge", env=self.env()
        )
        self.assertEqual(C.judge_runtime_id(got, "lab"), "vertex/judge")
        self.assertEqual(C.judge_runtime_id(got, "jb"), "google/judge")

    def test_17_opencode_command_uses_selected_model(self):
        with mock.patch.object(config, "BUN", Path("/bun")), mock.patch.object(
            config, "OPENCODE_DIR", Path("/oc")
        ):
            argv = OpencodeSubstrate().run_argv("task", Path("/work"), "openrouter/qwen/a/b")
        self.assertEqual(argv[argv.index("--model") + 1], "openrouter/qwen/a/b")

    def test_18_codex_uses_bare_runtime_model(self):
        argv = CodexSubstrate().exec_argv("task", Path("/work"), "gpt-runtime-id")
        self.assertEqual(argv[argv.index("--model") + 1], "gpt-runtime-id")

    def test_19_research_default_model_remains_legacy(self):
        got = resolve_run_model_config(env=self.env())
        self.assertEqual(got.improver.ref, self.env()["HARNESS2_IMPROVER_MODEL"])

    def test_20_secret_redaction(self):
        raw = {
            "Authorization": "Bearer abc.def",
            "url": "https://host/path?token=abc&x=1",
            "nested": {"api_key": "secret"},
        }
        shown = json.dumps(redact(raw))
        for secret in ("abc.def", "token=abc", "secret"):
            self.assertNotIn(secret, shown)

    def test_harness_substrate_conflict_is_clear(self):
        with self.assertRaisesRegex(config.ConfigError, "conflicts"):
            resolve_harness("opencode", "cx")

    def test_usage_counters_remain_separate(self):
        event = {
            "part": {
                "type": "step-finish",
                "tokens": {
                    "input": 10,
                    "output": 2,
                    "reasoning": 3,
                    "cache": {"read": 7, "write": 1},
                },
            }
        }
        got = _opencode_usage(json.dumps(event))
        self.assertEqual(got["input_tokens"], 10)
        self.assertEqual(got["cache_read_tokens"], 7)
        self.assertEqual(got["model_steps"], 1)


if __name__ == "__main__":
    unittest.main()
