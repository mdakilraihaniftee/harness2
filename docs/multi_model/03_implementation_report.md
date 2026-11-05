# Implementation report

## Implemented

- Immutable model/run configuration and stable secret-free fingerprint.
- Provider routes for OpenAI, OpenRouter (including Qwen IDs), Vertex, Anthropic, and custom
  OpenAI-compatible endpoints through pinned OpenCode.
- Independent solver, improver, selector, and judge selection.
- Real launcher propagation for JobBench and LAB; preserved Codex and WorkBuddy paths with
  explicit compatibility validation.
- Provider credential isolation for solver, proposer/composer, selector/reflection, and judges.
- Model-aware run, cache, judge, audit, and experience-library roots.
- Backward-compatible CLI aliases and read access to legacy judge/report directories.
- Offline profile inspection with honest credential/runtime/live status.
- PAVE-R/CITE-R live entry points accept a profile or improver override while retaining the
  original Vertex default, paid approval gates, fixtures, prompts, hidden oracles, and results.

## Configuration files

`model_profiles.toml` contains the previously exercised Vertex profile. GPT and Qwen profiles
use environment references so the repository never guesses a current model ID. Set, for
example, `HARNESS2_GPT_MODEL=openai/<id-reported-by-provider>` or
`HARNESS2_QWEN_MODEL=openrouter/qwen/<id-reported-by-provider>` without editing source.

## Usage and cost

Existing recursion and proposer accounting is unchanged: attempts, wall time, and provider
cost when OpenCode reports it are retained. Existing research usage files retain input,
output, reasoning, and cache counters. Providers that do not report a field remain
unavailable; no cost or token value is estimated by this change.

## Deliberately not implemented

- No native Claude Code/OpenClaw adapter.
- No network model catalog lookup and no guessed GPT/Qwen ID.
- No automatic rewriting of WorkBuddy Harbor model adapters.
- No paid or network-backed smoke test.
- No modification of old result artifacts.
