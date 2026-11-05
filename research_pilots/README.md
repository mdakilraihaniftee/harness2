# Research pilots

This directory contains isolated feasibility experiments for PAVE-R and CITE-R. It does not implement either full method.

Run the no-cost deterministic experiment and checks from the repository root:

```bash
.venv/bin/python -m research_pilots.run_deterministic
.venv/bin/python -m unittest discover -s research_pilots/tests -v
.venv/bin/ruff check research_pilots scripts/lab_agent_live_sandbox.py
.venv/bin/python -m research_pilots.finalize_results
```

`run_deterministic` regenerates synthetic evidence and may temporarily replace the aggregate summary with deterministic-only rows. Run `finalize_results` afterward to rebuild the adjudicated summary from all saved artifacts.

Live runs require the existing isolated Vertex gateway inputs and an explicit paid-call flag:

```bash
.venv/bin/python -m research_pilots.run_live --approve-paid --max-usd 20
```

Do not rerun the paid script merely to inspect results. Saved raw live traces are under the ignored `research_pilots/runs/` tree; normalized, credential-free results are under `research_pilots/results/`.

Start with `reports/04_research_decision.md` for the conclusions and exact limitations.

## Phase 2: compact composer evidence

The no-cost phase-2 preparation and updated result index are reproducible with:

```bash
.venv/bin/python -m research_pilots.prepare_phase2
.venv/bin/python -m unittest discover -s research_pilots/tests -v
.venv/bin/python -m research_pilots.finalize_phase2
```

Start with `reports/05_composer_failure_diagnosis.md` and
`reports/09_updated_research_decision.md`. The phase-2 live gate has not been run. It requires
separate authorization for an explicit incremental cap; `--approve-paid` alone should only be
used after that approval is recorded.
