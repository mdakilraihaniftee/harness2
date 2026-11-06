# Offline corrections

## PAVE diagnostic accounting

Diagnostic selection is now an intermediate action. Every trace records the initial action,
selected diagnostic, response, final KEEP/ADAPT decision, query count/cost, correctness and
unresolved status. An unavailable diagnostic yields `UNRESOLVED` for `diagnostic_first`; it is
never counted as a successful final decision.

| Policy | Correct/final binary | Queries | Diagnostic cost units | Unresolved |
|---|---:|---:|---:|---:|
| keep | 12/24 | 0 | 0 | 0 |
| repeat_count | 12/24 | 0 | 0 | 0 |
| source_deduplication | 12/24 | 0 | 0 | 0 |
| independent_check | 14/24 | 4 | 4 | 0 |
| diagnostic_first | 6/6 | 4 | 4 | 18 |

## CITE alternatives and verifier strength

All eight A/B/C bundles were executed. Verified sufficient repairs are
`HAB, HAC`; minimal sufficient repairs are
`HAB, HAC`. HAC is accepted when it succeeds even though
the declared A+B dependency flag is incomplete.

| Condition | Visible feedback | Perfect predictor |
|---|---|---|
| V0 | structural validation and execution completion only | False |
| V1 | partial schema/field checks; amount correctness remains hidden | False |
| V2 | full deterministic diagnostic, retained as high-information control | True |

V0 and V1 remain the main controls. V2 is explicitly an oracle-like high-information control.

## Deliverable extraction

The earlier JobBench regex mixed source filenames with outputs. The corrected inventory
separates provided source files, explicit output filenames, filename-free descriptions,
ambiguous requirements and temporary files. Legacy inventory SHA-256:
`a9789155fa9212c5998617f801b92853d5a9eec1b5ea576aaeb1429f7c031fba`. Corrected inventory is written separately and does
not overwrite it.
