# Local development and inference

For the current official-workflow audit, cloud access checks, and guarded LAB
experiment, see [verification](VERIFICATION.md), [cloud configuration](CLOUD_CONFIGURATION.md),
and [the reproduction procedure](REPRODUCE_LAB.md).

Run commands from the repository root. The main environment is `.venv`;
benchmark environments under `dependencies/` are selected automatically.

## Setup

The existing Python 3.12 environment can be reused:

```bash
source .venv/bin/activate
uv pip install -e '.[render,dev]'
```

For a fresh checkout, first create it with `uv venv --python 3.12 .venv`.
Copy `.env.example` to `.env` only if `.env` does not already exist. Shell
environment variables take precedence over `.env`. VS Code is configured to use
this interpreter and discover the unittest suite.

## Test without credentials

```bash
python -m unittest discover -s tests -v
ruff check .
uv pip check
harness2-demo --output runs/demo --k 2
python examples/quickstart.py custom
python examples/quickstart.py inspect runs/quickstart/custom
```

These demos use deterministic editors and execute real Python subprocesses.
They do not call a language model. In the custom example, the adopted word-count
script returns `Words: 7` and `Words: 10` for the two notes. The demo prints
the before/after harness diff and the lesson stored for subsequent tasks.
Repeating a command resumes completed work; use a new output directory when
changing the example, models, or task selection.

## Basic model inference

Set these values in `.env` using model IDs your project can access:

```dotenv
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
HARNESS2_SOLVER_MODEL=google-vertex/your-model-id
HARNESS2_IMPROVER_MODEL=
HARNESS2_JUDGE_MODEL=your-bare-judge-model-id
```

The project ID is the project selector's ID in Google Cloud, not a login code,
project display name, or project number. An empty improver model uses the solver.
The judge is only needed for benchmark evaluation.

```bash
gcloud auth application-default login
python examples/infer.py --check-only
python examples/infer.py --prompt "What is 17 + 25? Reply with just the number."
```

`--check-only` validates the local OpenCode channel, project configuration, and
ADC refresh without calling a model. It requires network access for ADC refresh;
it does not verify model availability or quota. A real inference uses the model
API and may incur costs. The script uses Harness²'s `Proposer` channel to run an
OpenCode agent session, with one transport attempt and at most eight agent steps
by default. One session may make several model requests. It is an agent
inference example, not the benchmark recursion workflow.

The response prints to the terminal. `response.txt`, `result.json`, and the
prompt/response audit files are saved in a new `runs/inference/<run>/` directory.
Overrides are available through `--model provider/model`, `--timeout 120`,
`--steps 8`, and `--output runs/my-inference`.

To exercise recursion with a real improver and the local word-count executor:

```bash
python examples/quickstart.py custom --live --k 1 --mode parallel
```

This saves results under `runs/quickstart/custom-live/` by default. It uses
several agent sessions and therefore more API calls than the basic inference.

## Add new work

Start with `WordCountAdapter` in `examples/quickstart.py`. Change its task inputs,
`task_prompt`, starting harness, and `execute` method to run your own work. Keep
`delivered`, `trajectory`, and `deliverable_text` aligned with your executor's
files. The `BenchmarkAdapter` protocol in `harness2/core/spec.py` describes the
full interface; the adapters in `harness2/benchmarks/` show real agent executors.

Use `ScriptedEditor` while developing offline, then use `Proposer` with a
configured model for real edits. Keep reference answers and grading criteria out
of execution and improvement context. Score only after adoption. Run the local
tests and Ruff after changing code.

## Setup audit (2026-10-31)

| Component | Verified state |
|---|---|
| Main package | Editable install in Python 3.12.16; rendering and development extras installed |
| Local workflows | Ledger and word-count examples run in both recursion modes; tests pass |
| OpenCode | Pinned checkout, patch, node dependencies, and Bun 1.3.11 present |
| LAB | Dependencies, runner patch, document tools, and task selection checks pass |
| JobBench | Dependencies, runner patch, judge imports, and task selection checks pass |
| Google authentication | Existing ADC refresh succeeds with network access |
| Live configuration | Project is now `harness2-513305`; metadata access returns HTTP 403 and tested permissions are absent; see the current cloud audit |
| WorkBuddy | Not installed; current account gets permission denied from Docker |
| Codex executor | Optional; endpoint, bridge, and executor setup have not been configured |

No live model inference or grading has been verified. Installed model defaults
and passing readiness checks do not prove access to those models.

After setting the project, recheck the installed benchmarks:

```bash
harness2-check --bench lab
harness2-check --bench jb
harness2 --bench lab --k 1 --mode parallel \
  --only-domains antitrust-competition --max-tasks 1 --dry-run
```

Remove `--dry-run` to run the selected task with models, then evaluate and report:

```bash
harness2-judge --bench lab --k 1 --mode parallel
harness2-report --bench lab --k 1 --mode parallel
```

For JobBench, select one domain as well as `--max-tasks 1`: the task limit applies
**per domain**. For example, use `--bench jb --only-domains technical_writers`.

WorkBuddy additionally needs Docker access (`docker info` must succeed) before
running `harness2-setup wb --subset office`. See [benchmark setup](SETUP.md) and
[the WorkBuddy guide](BENCHMARKS.md#workbuddy-bench) for the optional installation.
The optional Codex executor is covered in [SETUP.md](SETUP.md#codex-executor).
