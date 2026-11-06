# CITE composer replay design

| Condition | Feedback | Candidate pool | Manifest hash |
|---|---|---|---|
| CITE_V0 | V0 | dom1, inv1 | `a964bed173a8ae80` |
| CITE_V1 | V1 | dom1, inv1 | `3f54dc8000d8e531` |
| CITE_V2 | V2 | dom1, inv1 | `8cf9a85bd6b133d0` |

The first gate exposes A and B in separate INV/DOM candidates; each individual rollout fails
and the verified combination succeeds. The composer never sees HAB utility or a reference
patch. V0 provides structural completion only, V1 partial semantic checks, and V2 is a
high-information control.

| Harness | Edits | Valid | Declared dependency complete | Hidden utility | Cost |
|---|---|---|---|---:|---:|
| H0 | base | True | False | 0 | 0 |
| HA | A | True | False | 0 | 1 |
| HB | B | True | False | 0 | 1 |
| HC | C | True | False | 0 | 1 |
| HAB | A,B | True | True | 1 | 2 |
| HAC | A,C | True | False | 1 | 2 |
| HBC | B,C | True | False | 0 | 2 |
| HABC | A,B,C | True | True | 0 | 3 |

All successful alternatives are acceptable. Edit C is prepared only for a later interference
test after one valid A/B decision; larger pools remain inactive.
