# Multi-model Harness²

Harness² can now select the execution harness independently from provider/model roles. The two
real harnesses are OpenCode (`opencode`/`oc`) and Codex (`codex`/`cx`). OpenCode is the primary
multi-provider route. The editable c1–c8 harness tree remains distinct from the execution
harness.

## Inspect before running

These commands are offline and perform no inference:

```bash
harness2-models list
harness2-models validate --profile existing_vertex
harness2 --bench lab --model-profile existing_vertex --print-config --dry-run
harness2 --bench lab --model-profile existing_vertex --k 1 --mode parallel \
  --max-tasks 1 --dry-run
```

`--print-config` is secret-free and includes the stable fingerprint. A real run requires all
roles plus credentials; `--dry-run` prints the task stream without calling a model.

## Profiles and precedence

Profiles are TOML in `model_profiles.toml`, or a path selected with
`HARNESS2_MODEL_PROFILES`/`--model-profiles-file`. Precedence is CLI, profile, legacy env,
defaults. CLI flags are `--harness`, `--model`, `--solver-model`, `--improver-model`,
`--selector-model`, `--judge-model`, and `--model-profile`. `--substrate oc|cx` remains
compatible; a conflicting `--harness` is rejected.

`--model` sets solver and improver. Selector follows the improver unless explicitly set. Judge
is always independent.

## Provider setup

OpenAI: set `OPENAI_API_KEY` and use the exact ID reported for the account. If OpenAI is the
JobBench judge, also set `OPENAI_BASE_URL` to the endpoint documented for your account:

```bash
export HARNESS2_GPT_MODEL='openai/<verified-id>'
export HARNESS2_GPT_JUDGE_MODEL='openai/<verified-judge-id>'
harness2-models validate --profile gpt
```

Qwen via OpenRouter: set `OPENROUTER_API_KEY` and preserve the full multi-segment ID:

```bash
export HARNESS2_QWEN_MODEL='openrouter/qwen/<verified-id>'
export HARNESS2_QWEN_JUDGE_MODEL='openrouter/<verified-judge-id>'
harness2-models validate --profile qwen
```

Vertex: run `gcloud auth application-default login`, set project/location, then use
`google-vertex/<verified-id>`. The `existing_vertex` profile preserves the saved setup and ADC;
it does not alter cloud resources.

Anthropic: set `ANTHROPIC_API_KEY` and select `anthropic/<verified-id>`. The pinned OpenCode
loader exists, but no direct Anthropic call was authorized or verified here.

Custom endpoint: set `HARNESS2_CUSTOM_MODEL=custom/<model>`,
`HARNESS2_CUSTOM_BASE_URL`, and `HARNESS2_CUSTOM_API_KEY`, then use `custom_local`. Text-only API
compatibility is insufficient: live verification must prove tools, tool results, editing, and
event parsing.

## Workflows

Same supported model for solver/improver, independent judge:

```bash
harness2 --bench jb --harness opencode --model 'openai/<verified-id>' \
  --judge-model 'openai/<verified-judge-id>' --k 1 --mode parallel --dry-run
```

Qwen solver, GPT improver:

```bash
harness2 --bench jb --harness opencode \
  --solver-model 'openrouter/qwen/<verified-id>' \
  --improver-model 'openai/<verified-id>' \
  --judge-model 'openai/<verified-judge-id>' --k 1 --mode parallel --dry-run
```

Controlled research comparison on identical tasks/harness:

```bash
harness2 --bench lab --harness opencode --solver-model 'google-vertex/<verified-id>' \
  --improver-model 'openai/<verified-id>' --judge-model 'google-vertex/<judge-id>' \
  --seed 17 --k 1 --mode parallel --dry-run
harness2 --bench lab --harness opencode --solver-model 'google-vertex/<verified-id>' \
  --improver-model 'openrouter/qwen/<verified-id>' --judge-model 'google-vertex/<judge-id>' \
  --seed 17 --k 1 --mode parallel --dry-run
```

The differing improver produces a different model boundary, so rollouts, proposals, judge
caches, and experience libraries cannot collide.

## Judging and legacy runs

Pass the same profile/role flags to `harness2-judge` and `harness2-report`. Judge IDs are mapped
to LAB/JB conventions without changing solver IDs. If a fingerprinted path is absent, these
readers can find the original legacy layout; old data is never renamed.

## Research pilots and live authorization

PAVE-R/CITE-R deterministic fixtures remain provider-independent. Their paid entry points now
accept `--model-profile` or `--improver-model`, record the model already present in proposer
audit/results, and still require `--approve-paid` plus existing caps. Do not invoke them merely
to validate configuration.

A future authorized smoke test should use one harmless temporary workspace and one provider:
confirm authentication, actual model identity, a tool call/result, an allowed file edit,
trajectory parsing, usage metadata, and the fingerprinted output root. Do not run a benchmark
sweep or judge. OpenAI, OpenRouter/Qwen, direct Anthropic, custom endpoints, and Codex remain
unverified live. See `05_provider_compatibility.md` for exact statuses.

## First one-task end-to-end command set

The preview is no-cost and selects exactly one task by combining one domain with the per-domain
cap:

```bash
.venv/bin/harness2 --bench lab --harness opencode --model-profile existing_vertex \
  --seed 17 --k 1 --mode parallel --only-domains antitrust-competition \
  --max-tasks 1 --dry-run
```

After separate paid authorization, remove only `--dry-run` to execute. Then evaluate the same
fingerprinted experiment:

```bash
.venv/bin/harness2-judge --bench lab --harness opencode \
  --model-profile existing_vertex --seed 17 --k 1 --mode parallel
.venv/bin/harness2-judge --bench lab --harness opencode \
  --model-profile existing_vertex --seed 17 --k 1 --mode parallel --bases
.venv/bin/harness2-report --bench lab --harness opencode \
  --model-profile existing_vertex --seed 17 --k 1 --mode parallel
```

These evaluation commands can invoke the configured judge and therefore are also paid. No
command in this section was run beyond the preview/readiness checks during implementation.
