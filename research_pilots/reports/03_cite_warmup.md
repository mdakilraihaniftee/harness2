# CITE-R warm-up: joint edits and interference

## Classification

**B-BLOCKED — inconclusive.** A deterministic synergy and interference pattern is real in the controlled executor, and file-level recombination is feasible. The real composer did not complete enough substantive reasoning to attribute its failure to composition rather than the tool-step interface. Natural candidate generation was not tested.

## Controlled interaction

The compound shift requires both a schema/tool-guidance edit A and a domain conversion edit B. Candidate C applies the conversion a second time.

| Harness | Request behavior | Utility |
|---|---|---:|
| H0 | legacy `amount=12.34` | 0.0 |
| HA | v2 `amount_cents=12.34` | 0.0 |
| HB | legacy `amount=1234` | 0.0 |
| HC | legacy converted value | 0.0 |
| HAB | v2 `amount_cents=1234` | 1.0 |
| HABC | v2 `amount_cents=123400` | 0.0 |

Thus `Gamma_AB = U(HAB)-U(HA)-U(HB)+U(H0) = 1.0` and `Interference_C = U(HAB)-U(HABC) = 1.0`. The full hidden checks and requests are in `research_pilots/results/cite/interaction_matrix.json`.

This establishes the intended interaction in the deterministic synthetic executor. It does not establish that a natural LLM solver could not compensate within one run or that original INV/DOM proposers would generate A and B.

## Controlled real composer

The real Harness² aggregate stage was shown the base, HA as an INV candidate, HB as a DOM candidate, their actual failed trajectories, base evidence, and the normal composer instructions. The successful HAB bundle and oracle score were not revealed.

Three runs all returned or fell back to H0, producing utility 0.0:

- Initial: $0.193642, 86.5 seconds, two attempts, metadata lookup failure.
- Retry 1: $0.093736, 39.8 seconds, stopped while asking to inspect base deliverables.
- Retry 2: $0.188791, 80.7 seconds, ended with “STOP! DO NOT CALL ANY TOOLS!” after step exhaustion.

The outcome is not B-PASS: the composer never produced a substantive rejection of A or B, never cited their individual failure as the reason, and never reached a reliable composition decision. The observed failure is currently an operational context-browsing bottleneck. Raw results and responses are under `research_pilots/runs/live/cite/controlled_composer/` and `research_pilots/runs/live/audit*`.

## Generation, composition, execution, and selection

| Failure category | Evidence |
|---|---|
| Generation failure | UNKNOWN — natural INV/DOM proposer run NOT_RUN |
| Composition failure | UNKNOWN — controlled pool present, but composer run confounded |
| Execution failure | Deterministically absent for HAB; controlled HAB succeeds |
| Selection failure | NOT_RUN — no successful live final existed and `k=1` selection would be trivial |
| Same-scope vs cross-scope | NOT_RUN |

## File-level recombination feasibility

`research_pilots/bundles.py` extracts additions, deletions, and modifications relative to one base, rejects incompatible same-file edits, applies compatible edits atomically, and invokes the existing `tree.validate` once on the merged result. Tests cover A+B, additions/deletions, same-file conflicts, and a dependency-incomplete untriggered skill. This is sufficient for a research prototype, not proof of semantic independence: two different files can still encode a non-atomic dependency.

The deterministic apply-all control HABC fails, which demonstrates why a structural merge-all rule is insufficient for this fixture. Offline exhaustive/oracle selection identifies HAB, but that is only an analysis upper bound and is not a deployable unlabeled selector.

## Decision

Do not implement full CITE-R bundle search. First run the original composer over a compact candidate manifest that surfaces the two diffs and outcomes without requiring long filesystem navigation. If the composer then sees A and B, explicitly rejects them due to their failed individual rollouts, and misses HAB reproducibly, the proposed composition failure is supported. If it merges them, shift the research focus to candidate generation or deprioritize the idea.

