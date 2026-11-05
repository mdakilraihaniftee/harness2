# Experiment 2: CITE-R edit-interaction discoverability

The reference invoice fixture and two derived real-benchmark contexts were exhaustively
evaluated by declared local deterministic evaluators. Hidden utility was not supplied to
baselines; only the separately shown visible-check matrix and structural metadata were used.

### `reference_invoice_fixture`

`Gamma_AB=1.0`, `Interference_C=1.0`.

| Tree | Structurally valid | Dependencies complete | Execution completed | Visible check passes | Hidden utility |
|---|---|---|---|---|---:|
| H0 | PASS | no | yes | no | 0 |
| HA | PASS | no | yes | no | 0 |
| HB | PASS | no | yes | no | 0 |
| HC | PASS | no | yes | no | 0 |
| HAB | PASS | yes | yes | yes | 1 |
| HAC | PASS | no | yes | yes | 1 |
| HBC | PASS | no | yes | no | 0 |
| HABC | PASS | yes | yes | no | 0 |

### `jb:data_entry_keyers/task1`

`Gamma_AB=1.0`, `Interference_C=1.0`.

| Tree | Structurally valid | Dependencies complete | Execution completed | Visible check passes | Hidden utility |
|---|---|---|---|---|---:|
| H0 | PASS | no | yes | no | 0 |
| HA | PASS | no | yes | no | 0 |
| HB | PASS | no | yes | no | 0 |
| HC | PASS | no | yes | no | 0 |
| HAB | PASS | yes | yes | yes | 1 |
| HAC | PASS | no | yes | no | 0 |
| HBC | PASS | no | yes | no | 0 |
| HABC | PASS | yes | yes | no | 0 |

### `lab:bankruptcy-restructuring/draft-restructuring-support-agreement`

`Gamma_AB=1.0`, `Interference_C=1.0`.

| Tree | Structurally valid | Dependencies complete | Execution completed | Visible check passes | Hidden utility |
|---|---|---|---|---|---:|
| H0 | PASS | no | yes | no | 0 |
| HA | PASS | no | yes | no | 0 |
| HB | PASS | no | yes | no | 0 |
| HC | PASS | no | yes | no | 0 |
| HAB | PASS | yes | yes | yes | 1 |
| HAC | PASS | no | yes | no | 0 |
| HBC | PASS | no | yes | no | 0 |
| HABC | PASS | yes | yes | no | 0 |


The necessary A+B repair was generated in all 3 instances. A, B, and C
were individually valid; A+B succeeded; A+B+C exhibited measured interference. The explicit
conflicting-edit negative control was rejected: `True`.

Budgets 1–3 miss the pre-registered fourth probe A+B; budget 4 finds it because the permitted
validator supplies an observable signal. This is `COMPOSITION_LIMITED_AT_LOW_BUDGET`, not
generation- or execution-limited. However, simple dependency-aware compatible merging plus the
visible validator solves every controlled case, so the controls do not justify a sophisticated
new method.

## Decision

**REFINE — TRIVIAL STRUCTURAL SOLUTION**. The interaction is real, but tiny deterministic enumeration is already
a strong upper bound. Real composer behavior and LLM token efficiency remain
`REQUIRES_MODEL_INFERENCE`.
