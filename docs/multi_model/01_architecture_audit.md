# Architecture audit

## Snapshot

Audit date: 2026-11-05. Repository: branch `main`, commit
`5e1f7913b6f0d61fe165a84a3f0a2e946b01c720`. The worktree already contained the
user-owned `.vscode/settings.json`, the isolated LAB launcher adjustment, and the untracked
`research_pilots/` work; none was discarded. Python is 3.12.16 and Ruff is 0.17.3. The pinned
OpenCode checkout is `23fb5e0516c99ac04a1aa46c193efda2e1b9bb24`, package version 1.14.18,
run with Bun 1.3.11. The configured Codex release is 0.144.6, but its local binary is absent.

The legacy deployment uses `.env`, Application Default Credentials, a Google Cloud project,
`google-vertex/gemini-3.5-flash` for solver/improver, and a bare Gemini judge ID. The research
pilots use the same OpenCode/Vertex path through an isolated gateway and retain their explicit
paid-call gates.

## Before-change call graph

```text
.env / module globals
  ├─ SOLVER_MODEL_OC ──> JB runner MODEL_ID / LAB --model / WB generated route
  ├─ SOLVER_MODEL_CX ──> Codex BENCHMARK_MODELS / LAB --model / WB CODEX_MODEL
  ├─ IMPROVER_MODEL ───> BenchSpec ChannelSpec ──> Proposer ──> OpenCode --model
  │                                            └─> selector/reflection (usually shared)
  └─ JUDGE_MODEL ──────> benchmark-specific mapping ──> external evaluator
```

The recursion algorithm correctly kept benchmark, editable harness surface, and execution
substrate separate. The gap was deployment state: globals were read at import time and again
inside benchmark launchers. A CLI model could therefore not safely replace every real
invocation. Run labels named benchmark/substrate/mode/k/seed but not the full role model set.

## Implemented call graph

```text
CLI > TOML profile > legacy environment > defaults
                 │
                 v
          immutable RunModelConfig ──> secret-free fingerprint
            │       │       │   │              │
            │       │       │   └─ judge mapper│
            │       │       └──── selector      └─ runs/.../model-config-<hash>/
            │       └──────────── improver ──> ChannelSpec ──> Proposer/OpenCode
            └──────────────────── solver ────> adapter instance ──> real launcher argv/env
```

## HarnessAudit findings

HarnessAudit keeps framework, native harness, model, and judge as independent runner fields;
passes the model through a run context into the native adapter; and scopes artifacts by harness
and model. Its adapter and runtime registries are explicit rather than inferred from strings.
Harness² now adopts those narrow principles—explicit registry, invocation propagation, and
model-scoped artifacts—without copying HarnessAudit's benchmark framework. Harness² still owns
editable c1–c8 trees and Propose–Probe–Compose.

## Configuration gaps and disposition

| Gap | Before | Disposition |
|---|---|---|
| Role selection | Solver/improver/judge globals; selector implicit | Typed solver, improver, selector, judge specs |
| CLI overrides | No end-to-end model flags | Added model, role, profile, harness, and print flags |
| Provider secrets | Broad inherited environments | All known provider secrets scrubbed; selected credential restored |
| Provider/model parsing | Slash presence check | First slash only; multi-segment OpenRouter IDs preserved |
| Resume identity | Partial JSON guard | Stable secret-free model boundary plus identity file |
| Legacy results | Original layout only | Judge/report read fallback; no old path renamed |
| Harness discovery | Tuple of substrate aliases | Registry contains only real OpenCode and Codex adapters |
| Model discovery | None | Offline `harness2-models` list/validate |
| WorkBuddy portability | Vertex-specific generated Harbor routes | Explicit Vertex-only validation; no false multi-provider claim |
| Codex runtime | Configured source path | BLOCKED locally because binary is absent |
| Usage normalization | Provider-specific, partial | Existing accounting retained; no fabricated universal counters |

## Model-bearing calls

| Role | Selection | Actual launcher | Credential | Output/resume |
|---|---|---|---|---|
| Solver/JB OC | `RunModelConfig.solver` | runner `MODEL_ID` | selected provider env | JSONL + output; run marker |
| Solver/LAB OC | same | `run_opencode.py --model` | selected provider env | metrics/events + output; marker |
| Solver/Codex | same, bare runtime ID | Codex runner/`--model` | configured Responses gateway | Codex JSON events; marker |
| Improver/composer | `improver` | `Proposer`, OpenCode `--model` | selected provider env | audit reply/workspace cache |
| Selector/reflection | `selector`, defaults to improver | separate `Proposer` when different | selected provider env | selection/reflection records |
| Judge | `judge` | LAB/JB/WB evaluator mapping | ADC or selected judge env | judge cache below model boundary |

Hidden benchmark rubrics and scores remain outside adaptation context.
