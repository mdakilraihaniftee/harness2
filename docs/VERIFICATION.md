# Setup verification — 2026-10-31

The local installation supports offline development and the complete one-task
LAB workflow. An approved paid reproduction completed through a constrained
Vertex gateway; no cloud resources were created or changed.

## Results

| Status | Check | Evidence / limit |
|---|---|---|
| PASS | Official upstream comparison | Upstream HEAD `1cfe254e8d25b15f37048c3730134686abe60335`; local HEAD `ae0d8e0c2c6aa670059b0cd4cbc8c9e1e2330ffd` includes that revision |
| PASS | Setup and experiment guides | `docs/SETUP.md`, `docs/BENCHMARKS.md`, and `docs/EXPERIMENTS.md` match upstream byte for byte |
| PASS | Framework source | `git diff <upstream-sha> -- harness2 third_party` is empty; official algorithm and runner sources preserved |
| PASS | Local changes preserved | README additions, its existing `## new` heading, development extra, examples, editor settings, and `.env` retained |
| PASS | Tests | All 10 pre-existing tests pass; 4 new reproduction/approval/usage regression tests pass; 14 total |
| PASS | Ruff | `.venv/bin/ruff check .` passes |
| PASS | Official local demo | `harness2-demo --output runs/audit-20261031/demo --k 2`: 2 tasks, 0 failures, both recursion modes |
| PASS | Release provenance | `scripts/check_provenance.py`: all 47 release-asset hashes match |
| PASS | LAB readiness | `harness2-check --bench lab`: 1,143 tasks, supported pins, patches, imports, document tools, ADC |
| PASS | JobBench readiness | `harness2-check --bench jb`: 65 tasks installed, supported pins, patches, judge imports, ADC |
| PASS | Real inference path | `examples/infer.py` uses `Proposer` → `Bun/OpenCode run` → `google-vertex` provider → authenticated Google API fetch; its runtime contains no mock response |
| PASS | Inference setup-only check | `examples/infer.py --check-only` passes with network access; it never tests generation or model entitlement |
| PASS | Environment syntax | Project, location, solver, judge are set; blank improver intentionally inherits solver |
| PASS | Git ignores | `.env`, `.env.*` except `.env.example`, `runs/`, environments, common credential directories/files and private-key extensions ignored; no matching sensitive files tracked |
| PASS | ADC | Existing ADC refresh succeeds with network access; tokens are never printed or saved by the audit |
| PASS | Read-only cloud inventory | Four visible projects; IAM permission, Vertex API, and billing metadata inspected without modifying resources |
| PASS | Configured project access | `graphite-setup-513305-e1` is ACTIVE and grants prediction/service-use permissions |
| PASS | Configured project readiness | Vertex API and billing are enabled; live Gemini inference succeeded |
| PASS | One-task dry-run | Exactly `antitrust-competition/analyze-antitrust-hsr-strategy`, k=1, parallel, 1 worker, sorted order without a seed |
| PASS | Offline OS isolation | Bubblewrap probe outside the tool sandbox hides `.env`, host ADC, task rubric, and a sibling canary; staged workspace remains writable |
| PASS | Offline rubric egress restriction | Network namespace denies GitHub/Hugging Face and direct-IP TCP probes; no network sharing or host Docker socket |
| PASS | Live isolated executor | Unix-socket Vertex gateway reachable while ADC, `.env`, task rubric, public HTTPS, and direct-IP egress remain blocked to the agent |
| PASS | Paid one-task experiment | Approved k=1 parallel run completed 1/1 with a non-base aggregate harness selected |
| PASS | Initial/refined scoring | Initial 41/50 (82%); refined 43/50 (86%); both graded, neither all-pass |
| PASS | Usage/runtime capture | Agent event tokens, executor metrics, stage timings, and runtime cost estimates saved under `runs/reproduction/lab-approved-005/` |
| BLOCKED | Exact billed total | Judge usage is not exposed by the unmodified LAB judge; cloud billing records are required for an invoice-equivalent total |

`harness2-check` deliberately does not inspect API enablement, billing, inference
permission, or model availability. Those properties were verified separately by
the read-only cloud audit and the approved live run.

The host tool sandbox restricts network and nested namespace operations. ADC
and Bubblewrap were verified outside it using reviewed read-only probes. The
Bubblewrap launcher itself runs agents with a separate network namespace.

## Reproduce the audit

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
ruff check .
python scripts/check_provenance.py
harness2-demo --output runs/audit-20261031/demo --k 2
harness2-check --bench lab
harness2-check --bench jb
python examples/infer.py --check-only
python scripts/audit_reproduction.py --upstream --cloud
python scripts/reproduce_lab.py prepare
python scripts/reproduce_lab.py check-isolation
```

The last probe needs a host that permits Bubblewrap namespaces. None of these
commands performs paid inference. Repeating the official demo resumes its
completed tasks; use a fresh output directory for a new execution.

The audit saves pinned upstream guide snapshots, SHA-256 hashes, diffs, safe
environment metadata, project inventory, and cloud read statuses under
`runs/audit-20261031/`. That directory is ignored by Git and should be reviewed
before sharing because it contains project identifiers and local paths.

The official sources are the pinned [README](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/README.md),
[setup guide](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/docs/SETUP.md),
[benchmark guide](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/docs/BENCHMARKS.md),
and [experiment guide](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/docs/EXPERIMENTS.md).
The added local scripts orchestrate these entry points; they do not change
Harness²'s method or benchmark scoring code.

Continue with the [cloud checklist](CLOUD_CONFIGURATION.md) and
[one-task experiment procedure](REPRODUCE_LAB.md).
