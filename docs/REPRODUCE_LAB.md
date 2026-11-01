# Reproduce one official LAB task

This procedure runs the released Harness² CLI and LAB adapter. It preserves
their prompts, recursion, selection, reflection, and grading behavior. The
additional scripts record the inputs and gate paid stages. It is a small
workflow reproduction, not a reproduction of aggregate paper results.

## Frozen experiment

| Setting | Value |
|---|---|
| Specification | `experiments/lab_one_task.json` |
| Task | `antitrust-competition/analyze-antitrust-hsr-strategy` |
| Benchmark / executor | LAB / OpenCode (`oc`) |
| Budget / mode | k=1 / parallel |
| Workers / task limit | 1 worker / 1 task in the selected domain |
| Order | Sorted; no seed. The script checks the exact expected task before proceeding |
| Solver / improver | Effective `.env` values; currently `google-vertex/gemini-3.5-flash` for both |
| Judge | Currently `gemini-3.5-flash` (`vertex/` added by the LAB adapter) |
| LAB revision | `b58a28ae9fde5ee4b810e53b4fd0a1915325a35d` plus release overlays/patch |
| OpenCode revision | `23fb5e0516c99ac04a1aa46c193efda2e1b9bb24` plus release compatibility patch |
| Default output | `runs/reproduction/lab-one-task-v1/` |

The preparation script saves models, project/location, exact task and source
hashes, dependency commits and diff fingerprints, installed package versions,
release assets and installed runner hashes, the sanitized task prompt, practice
profile, and actual starting harness text in `manifest.json` and `prompts/`.
It refuses to reuse that directory if these inputs change. Use a new output
directory after changing the project, code, models, or experiment specification.
Model sampling is not deterministic even with identical recorded inputs.

## Prepare and inspect now — no paid calls

```bash
cd /home/ai5377/harness2
source .venv/bin/activate
python scripts/reproduce_lab.py prepare
python scripts/reproduce_lab.py check-isolation
```

The official dry-run invoked by `prepare` is equivalent to:

```bash
export HARNESS2_RUNS_DIR="$PWD/runs/reproduction/lab-one-task-v1"
harness2 --bench lab --substrate oc --k 1 --mode parallel \
  --only-domains antitrust-competition --max-tasks 1 --workers 1 --dry-run
```

Its exact task line is:

```text
1  antitrust-competition  antitrust-competition/analyze-antitrust-hsr-strategy
```

`prepare` saves the full output to `dry-run.txt`. Baseline/refined scores, model
token counts, and model runtime remain unavailable until approved execution.

## Isolation and rubric access

The bundled `scripts/lab_agent_sandbox.py` is an executable Bubblewrap profile.
It unshares namespaces, drops capabilities, creates separate `/proc`, `/dev`,
and `/tmp`, clears inherited environment variables, and mounts only runtime
dependencies and the staged agent workspace. Dependencies are read-only;
`documents/` is remounted read-only. The main repository, raw LAB task tree,
host `.env`, host ADC, other run workspaces, and Docker socket are not mounted.

The profile unshares the network namespace and has **no network**. This enforces
the official guide's GitHub/Hugging Face restriction, also denying direct-IP
egress. The probe confirms blocked rubric/credential/canary reads and blocked
network connections. These negative controls are useful checks, not a complete
proof against every sandbox escape or network bypass.

The profile was verified on this host outside the assistant's tool sandbox.
Nested Bubblewrap/network namespaces can fail inside that outer sandbox. The
launcher fails rather than running the agent without isolation.

Live execution uses `scripts/lab_agent_live_sandbox.py` together with
`scripts/vertex_gateway.py`. The agent remains in a network-less Bubblewrap
namespace and reaches only a mounted Unix TLS socket. The host gateway accepts
only `generateContent`/`streamGenerateContent` paths for the configured project
and location, replaces the sandbox placeholder with a short-lived ADC token,
and forwards to Vertex. Host ADC, `.env`, raw task/rubric files, and arbitrary
IP/HTTPS egress remain unavailable to the agent. A local models.dev snapshot is
mounted read-only so OpenCode does not need registry access.

A reviewed launcher must implement this interface:

```text
/absolute/path/to/reviewed-launcher --workspace /absolute/staged-workspace -- COMMAND ARGS...
```

It must enforce the same filesystem restrictions, block arbitrary outbound
networking, and permit the configured model/auth route. Run `check-isolation`
with `--agent-launcher` to test it. Review the gateway's enforcement and logs
as well; passing the negative controls alone does not establish a secure policy.
The script requires both a passing probe and reachable model transport before
running any agent. The model-transport probe is an unauthenticated HTTPS GET,
not a generation request or an entitlement test.

The experiment's temporary Bun wrapper routes **all** executor and improver
OpenCode launches through the chosen launcher and records usage events without
changing the JSON stream forwarded to Harness². This changes invocation plumbing
in the research script only; framework and vendored source files remain intact.
The native LAB judge runs as trusted host-side code after adoption, with access
to grading criteria. It is not exposed as an agent tool.

## End-to-end execution

Resolve the [cloud checklist](CLOUD_CONFIGURATION.md) and obtain explicit cost
approval for refinement and both evaluations. The paid stages require
`--approve-paid`, and a recent cloud audit must verify billing, Vertex API
enablement, and the tested inference/use permissions for the selected project.

Then these are the complete commands, with a fresh output root:

Trusted-host terminal A (create a local TLS certificate once, then run the
gateway; the key and all run outputs are Git-ignored):

```bash
cd /home/ai5377/harness2
source .venv/bin/activate
mkdir -p runs/reproduction/lab-approved-001/gateway
openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
  -keyout runs/reproduction/lab-approved-001/gateway/key.pem \
  -out runs/reproduction/lab-approved-001/gateway/cert.pem \
  -subj /CN=aiplatform.googleapis.com \
  -addext subjectAltName=DNS:aiplatform.googleapis.com
chmod 600 runs/reproduction/lab-approved-001/gateway/key.pem
python scripts/vertex_gateway.py \
  --project graphite-setup-513305-e1 --location global \
  --metadata-port 18347 --vertex-port 18443 \
  --unix-socket runs/reproduction/lab-approved-001/gateway/vertex.sock \
  --cert runs/reproduction/lab-approved-001/gateway/cert.pem \
  --key runs/reproduction/lab-approved-001/gateway/key.pem \
  --ready-file runs/reproduction/lab-approved-001/gateway/ready
```

Terminal B:

```bash
cd /home/ai5377/harness2
source .venv/bin/activate
export EXPERIMENT_DIR="$PWD/runs/reproduction/lab-approved-005"
export LAB_AGENT_LAUNCHER="$PWD/scripts/lab_agent_live_sandbox.py"
export HARNESS2_GATEWAY_CA="$PWD/runs/reproduction/lab-approved-001/gateway/cert.pem"
export HARNESS2_GATEWAY_SOCKET="$PWD/runs/reproduction/lab-approved-001/gateway/vertex.sock"
export HARNESS2_MODELS_SNAPSHOT="$HOME/.cache/opencode/models.json"

python scripts/audit_reproduction.py --upstream --cloud
harness2-check --bench lab
python scripts/reproduce_lab.py prepare --output "$EXPERIMENT_DIR" \
  --agent-launcher "$LAB_AGENT_LAUNCHER"
python scripts/reproduce_lab.py check-isolation --output "$EXPERIMENT_DIR" \
  --agent-launcher "$LAB_AGENT_LAUNCHER"

python scripts/reproduce_lab.py run --output "$EXPERIMENT_DIR" \
  --agent-launcher "$LAB_AGENT_LAUNCHER" --approve-paid
python scripts/reproduce_lab.py judge --output "$EXPERIMENT_DIR" \
  --agent-launcher "$LAB_AGENT_LAUNCHER" --approve-paid
python scripts/reproduce_lab.py judge-bases --output "$EXPERIMENT_DIR" \
  --agent-launcher "$LAB_AGENT_LAUNCHER" --approve-paid
python scripts/reproduce_lab.py report --output "$EXPERIMENT_DIR"
python scripts/reproduce_lab.py collect --output "$EXPERIMENT_DIR"
```

Start `scripts/vertex_gateway.py` in a separate trusted-host terminal before
`check-isolation`; its project/location, socket, certificate, and key must match
the exported paths. Stop if any command fails. The default offline launcher can
test isolation but intentionally cannot complete the `run` stage.

For clarity, the two native evaluation commands used by the script are:

```bash
export HARNESS2_RUNS_DIR="$EXPERIMENT_DIR"
# Both commands below use the paid judge and require prior approval.
harness2-judge --bench lab --substrate oc --k 1 --mode parallel
harness2-judge --bench lab --substrate oc --k 1 --mode parallel --bases
harness2-report --bench lab --substrate oc --k 1 --mode parallel
```

`--bases` evaluates the original reference execution recorded by the same
refinement run; it does not launch a new baseline executor. The CLI report
covers refined outputs only. Compare `base_judged.json` with `judged.json` for
the initial/refined comparison. LAB reports criteria passed / total criteria
(partial credit) and whether all criteria pass. Failed grading remains
unscored. With a single task, report both raw counts and the percentage.

## Measurements and cost

At k=1 the official ledger expects four executor rollouts (base, general
candidate, domain candidate, composition) and three improvement stages.
Reflection is an additional session outside that ledger. Retries and judging
can add calls; a rollout or session can itself contain many model requests.

| Artifact | Recorded information |
|---|---|
| `manifest.json`, `prompts/` | Models, project/location, task identity, hashes, sanitized task prompt, actual base prompt and practice/work profile |
| `dry-run.txt` | Exact task selection and output namespace |
| `isolation.json` | Launcher path/hash, file isolation controls, egress probes, model transport reachability |
| `lab/adapt/**/context/`, `lab/adapt/_audit/` | Actual stage context, missions, model responses, edits, decisions, reflections |
| `lab/results/oc/**/config.json` and `metrics.json` | Executor settings, runtime, input/output/reasoning tokens and runtime-reported cost |
| `agent-usage/*.json` | Usage-only events and wall time for executor **and improver** Bun invocations, including retries that emit usage |
| `*-timing-*.json` | Completed orchestration/evaluation stage elapsed time and exit code |
| `lab/adapt/lab-oc-agg1/judged.json` | Refined selected-output scores |
| `lab/adapt/lab-oc-agg1/base_judged.json` | Initial-harness reference scores |
| `results.json` | Collected metrics, scores, summed agent token counters, and agent token-cost estimate when model IDs match the price snapshot |

Judge token usage and cost are not exposed by the unmodified LAB judge. They
remain unknown in `results.json`; use billing records or a separately approved
measurement change for a full cost total. Runtime-reported zero cost can mean
missing pricing metadata. Treat it as an estimate, not proof of free inference.
Failed/aborted requests may lack usage events. Summed per-agent wall times are
not elapsed wall time when stages run concurrently.

The checked standard/global price is **$1.50 per million input tokens and $9.00
per million output/reasoning tokens**. For planning only, 1M input plus 200k
output/reasoning tokens across all calls would cost about **$3.30** before other
services. This is an illustrative scenario, not a predicted usage total or
spending cap. Prices, caching, retries, and judge usage affect actual cost.
The collector's agent estimate counts cached inputs at the full input price
and excludes all judge usage and other services. Recheck
[Google's standard pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)
before approving execution.

## Completed run: `lab-approved-005`

The approved run completed on 2026-10-31 with 1/1 tasks OK and selected the
non-base `agg1` harness (`harness_fingerprint=847e351a8973c2e5`). Isolation
passed immediately before execution. The earlier `lab-approved-003` and `004`
compatibility attempts failed before reaching Vertex and recorded no usage
events.

| Measurement | Result |
|---|---:|
| Initial harness | 41/50 (82%) |
| Refined harness | 43/50 (86%) |
| Change | +2 criteria / +4 percentage points |
| Refinement run elapsed | 1,588.448 s |
| Refined judge elapsed | 38.124 s |
| Initial judge elapsed | 44.892 s |
| Four executor rollouts | 2,383,046 total tokens; 1,291.0 summed wall seconds; $6.5957 runtime estimate |
| All recorded agent events | 3,688,259 non-cached input; 16,989,839 cached input; 90,505 output; 146,521 reasoning tokens |
| All OpenCode runtime estimates | $10.21409835 |
| Collector full-input estimate | $33.150381 (intentionally conservative; cached inputs priced as full input) |
| Judge usage/cost | Unknown; unmodified LAB judge does not expose it |

These are runtime estimates, not a cloud invoice. The authoritative artifacts
are `runs/reproduction/lab-approved-005/manifest.json`, `results.json`,
`lab/adapt/lab-oc-agg1/judged.json`, and `base_judged.json`.

## Small Python entry point

Use the example wrapper for one LAB dataset item. With no flags it only prepares
the official dry-run; it does not call a model:

```bash
python examples/run_single_lab.py
```

Display the completed run, including a text preview of its DOCX output:

```bash
python examples/run_single_lab.py --show \
  --output runs/reproduction/lab-approved-005
```

After starting the gateway documented above, a new paid run is explicit:

```bash
python examples/run_single_lab.py --execute --approve-paid \
  --output runs/reproduction/my-single-lab-run
```

Although this selects one dataset task, k=1 parallel recursion still performs
four executor rollouts and three improver stages, then the wrapper runs both
judge passes. It is not a one-request smoke test; `examples/infer.py` serves
that cheaper purpose.
