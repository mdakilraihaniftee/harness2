# Baseline smoke test

## Status

PASS. The unmodified deterministic Harness² workflow executes in both parallel and sequential modes, changes a harness, executes the changed tree, selects an output, reflects an experience, and transfers that experience to the next task.

## Commands executed

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/harness2-demo --output research_pilots/runs/baseline_demo --k 1 --mode both
```

Final repository test result: 16 passed, 0 failed, 0 skipped, 0 blocked in 8.971 seconds. The saved log is `research_pilots/results/logs/repository_tests.log`.

The deterministic demo completed two accounting tasks with 0 failures, 14 executions, and 16 editor calls. Its top-level record is `research_pilots/runs/baseline_demo/demo.json`.

## Inspected behavior

For `ledger-1`, the base script summed only positive amounts and produced `Total: 105.25`. INV and DOM both identified that credits were omitted. The adopted final removed the positive-only filter in `scripts/summarize.py` and produced `Total: 85.15`.

Both modes recorded the required `k=1` budget:

- Rollouts: `base1`, `inv1`, `dom1`, and `agg1`/`c1` (`R=4`).
- Editor stages: `inv1`, `dom1`, and `agg1`/`c1` (`P=3`).
- No fallback and no stage error.

At `k=1`, selection was correctly marked trivial: it adopted the one composed final without a selector model call. Reflection recorded the cue “When a ledger includes credits and debits,” the signed-sum lesson, and the supporting script/trajectory evidence. `ledger-2` started with one library entry in each mode, confirming cross-task transfer.

## Invariants

| Invariant | Result | Evidence |
|---|---|---|
| Pipeline executes | PASS | 2/2 demo tasks completed |
| Harness is modified | PASS | `scripts/summarize.py` filter removed |
| Modified harness executes | PASS | final total changed from 105.25 to 85.15 |
| Output can be selected | PASS | `selection.json`, trivial final selection at `k=1` |
| Reflection works | PASS | experience fields stored for both modes |
| Library transfer works | PASS | one prior entry visible before `ledger-2` |
| Budget accounting works | PASS | `R=4`, `P=3` in parallel and sequential summaries |

This smoke test establishes repository readiness only; it provides no evidence for either PAVE-R or CITE-R.

