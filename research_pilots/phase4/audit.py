"""Composer prompt-pack, cache, and target-model audit without provider calls."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from harness2.benchmarks.jobbench import JobBenchAdapter
from harness2.benchmarks.lab import LabAdapter
from harness2.core import prompts
from harness2.core.proposer import _call_fingerprint
from harness2.core.spec import resolve_prompts
from harness2.model_config import resolve_run_model_config
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.adapter import PilotAdapter
from research_pilots.evidence import condition
from research_pilots.fixtures import TASK_CITE, base_tree


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _synthetic_model_env() -> dict[str, str]:
    env = dict(os.environ)
    model = os.environ.get("HARNESS2_QWEN_MODEL") or "openrouter/qwen/phase4-synthetic-id"
    env.update(
        {
            "HARNESS2_QWEN_MODEL": model,
            "HARNESS2_QWEN_JUDGE_MODEL": os.environ.get("HARNESS2_QWEN_JUDGE_MODEL")
            or model,
            "OPENROUTER_API_KEY": "non-secret-offline-placeholder",
        }
    )
    return env


def composer_cache_audit(tmp_root: Path) -> dict:
    jb = JobBenchAdapter()
    lab = LabAdapter()
    jb_task = jb.tasks()[0]
    lab_task = lab.tasks()[0]
    pilot = PilotAdapter(tmp_root / "pilot", TASK_CITE, base_tree(), condition("A0_clean", []))
    adapters = {"jobbench": (jb, jb_task), "lab": (lab, lab_task), "research": (pilot, TASK_CITE)}
    packs = {}
    for name, (adapter, task_id) in adapters.items():
        bp = resolve_prompts(adapter, task_id)
        k1 = prompts.aggregate(bp, OPENCODE_SURFACE, k=1)
        k3 = prompts.aggregate(bp, OPENCODE_SURFACE, k=3)
        packs[name] = {
            "task_id": task_id,
            "prompt_pack": bp.prompt_pack,
            "aggregate_k1_sha256": _hash(k1),
            "aggregate_k3_sha256": _hash(k3),
            "repeated_base_failure_instruction": "strongest thing you can act on" in k3,
            "failed_candidate_unsafe_instruction": "treat that edit as UNSAFE" in k1,
            "keep_base_explicit": "KEEP_BASE" in k1,
        }

    qwen = resolve_run_model_config(
        profile="qwen",
        env=_synthetic_model_env(),
        require_judge=True,
    )
    vertex = resolve_run_model_config(
        model="google-vertex/phase4-synthetic-model",
        judge_model="google-vertex/phase4-synthetic-judge",
        env={
            **os.environ,
            "GOOGLE_CLOUD_PROJECT": "phase4-offline-project",
            "GOOGLE_CLOUD_LOCATION": "global",
        },
    )
    sample_root = tmp_root / "cache-sample"
    sample_root.mkdir(parents=True, exist_ok=True)
    (sample_root / "evidence.md").write_text("fixed evidence\n", encoding="utf-8")
    base_key = _call_fingerprint("sample-1", "mission", "system", sample_root)
    repeated_key = _call_fingerprint("sample-2", "mission", "system", sample_root)
    return {
        "schema_version": 1,
        "prompt_packs": packs,
        "hypothesis_prompt_pack": "adapt",
        "prompt_control_finding": (
            "adapt contains both repeated-base and unsafe-failed-candidate statements; tts does not"
        ),
        "core_cache_key_inputs": ["label", "mission", "system", "resolved context path", "context bytes"],
        "core_cache_key_directly_includes_model": False,
        "normal_cross_model_isolation": (
            "RunModelConfig fingerprint changes adapter run roots and therefore context/audit paths"
        ),
        "research_repetition_labels_produce_distinct_keys": base_key != repeated_key,
        "example_cache_keys": [base_key, repeated_key],
        "model_configurations": {
            "qwen_target_offline": qwen.safe_dict() | {"fingerprint": qwen.fingerprint},
            "vertex_control_offline": vertex.safe_dict() | {"fingerprint": vertex.fingerprint},
        },
        "cross_model_fingerprints_distinct": qwen.fingerprint != vertex.fingerprint,
        "live_qwen_preflight": {
            "model_id_present": bool(os.environ.get("HARNESS2_QWEN_MODEL")),
            "credential_present": bool(os.environ.get("OPENROUTER_API_KEY")),
            "judge_not_required_for_composer_gate": True,
        },
    }

