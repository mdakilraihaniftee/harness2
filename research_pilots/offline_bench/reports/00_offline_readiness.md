# Offline research readiness

## Status

**PASS — zero-inference execution is available.** Git revision `5e1f7913b6f0d61fe165a84a3f0a2e946b01c720`, branch `main`,
selection seed `17`. Installed task discovery returned exactly **1,143 LAB** and
**65 JobBench** tasks without launching a solver or judge.

## Installed benchmark boundaries

| Benchmark | Installed path | Local revision | Adapter | Tasks | Offline capability |
|---|---|---|---|---:|---|
| LAB | `/home/ai5377/harness2/dependencies/harvey-labs` | `b58a28ae9fde5ee4b810e53b4fd0a1915325a35d` | `LabAdapter` / OpenCode surface | 1,143 | Task/source discovery; artifact name/format checks; official semantic judge unavailable offline |
| JobBench | `/home/ai5377/harness2/dependencies/job-bench-eval` | `fa03a17f9ff662f136798a274e10011c3aa00fd0` | `JobBenchAdapter` / OpenCode surface | 65 | Task/source discovery; file/schema/parse checks; official rubric judge unavailable offline |

WorkBuddy is intentionally excluded. No benchmark was downloaded.

## Configuration and protection

`model_profiles.toml` defines `existing_vertex`, `gpt`, `qwen`, and `mixed`; profiles are
resolved only with synthetic identifiers/placeholder values in the integrity experiment.
`OfflineGuard` blocks `Proposer.call`, OpenCode/Codex substrate execution, every installed
benchmark adapter's judge method, and socket connection attempts. A blocked attempt fails the
suite. The runner reports its own counters, all of which must remain zero.

## Reused research infrastructure

- `research_pilots.manifest`: compact evidence rendering, hidden-marker checks, exact edits,
  path validation, and reconstruction.
- `research_pilots.bundles`: relative file edits, conflict rejection, and tree validation.
- `research_pilots.evidence`: immutable reference-record rendering conventions.
- `research_pilots.fixtures`: PAVE deterministic execution and reference A/B/C interaction.
- `harness2.core.context`, `tree`, `schedule`, `library`, and deterministic demo: real context,
  editable surfaces, recursion modes, selection/reflection, and experience reuse.

## Evidence boundaries

Installed instructions and source layouts are official benchmark inputs. Derived artifact
contracts are not official tasks or scores. Replay trajectories are explicitly synthetic.
Hidden deterministic utility is stored only in result records and never in composer-visible
context. No external evaluation API is available or needed for the declared derived checks.

## Reproduction commands

The complete suite and each isolated experiment use the same mandatory fail-closed guard:

```bash
.venv/bin/python -m research_pilots.offline_bench.run --offline --all
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment inventory
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment pave
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment cite
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment replay
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment models
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment demo
```

Partial runs write `experiment_<name>_summary.json`; they do not replace the aggregate
`experiment_summary.json` produced by `--all`.
