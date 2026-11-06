# PAVE composer replay design

| Condition | Environment | k | Evidence | Candidates | Context hash |
|---|---|---:|---|---:|---|
| PAVE_P0_K1 | NO_ADAPTATION_NEEDED | 1 | A0_clean | 2 | `a316e4ce41b159cd` |
| PAVE_P1_K1 | NO_ADAPTATION_NEEDED | 1 | A1_isolated | 2 | `d146e8412d6ae287` |
| PAVE_P0_K3 | NO_ADAPTATION_NEEDED | 3 | A0_clean | 6 | `f5319c5f63ce338f` |
| PAVE_P1_K3 | NO_ADAPTATION_NEEDED | 3 | A1_isolated | 6 | `fde0b2aeb6acaf14` |
| PAVE_P2_K3 | NO_ADAPTATION_NEEDED | 3 | A2_systematic | 6 | `67576fcb6794345b` |
| PAVE_P3_K3 | NO_ADAPTATION_NEEDED | 3 | A2_systematic+independent_diagnostic | 6 | `d3618bde44fc5137` |
| PAVE_P4_K3 | NO_ADAPTATION_NEEDED | 3 | A2_matched_independent | 6 | `feda9f4b5ca73108` |
| PAVE_POSITIVE_K3 | ADAPTATION_NEEDED | 3 | A0_clean | 6 | `bc3a39eda6a3e805` |

P0/P1 at k=1 and P0/P1/P2 at k=3 share the task family and per-k candidate pool. P2 and P4
have the same composer-visible rollout content but different hidden generation provenance; no
behavioral difference is expected without visible provenance. P3 adds a factual independent
ledger observation, not a statement of the preferred edit. `PAVE_POSITIVE_K3` supplies a
verified repair in a genuinely shifted environment.

Composer outcomes are classified as KEEP_BASE, EDIT, MERGE, INVALID or OPERATIONAL_FAILURE.
Hidden utility is evaluated afterward, so modification alone is never labeled harmful.
