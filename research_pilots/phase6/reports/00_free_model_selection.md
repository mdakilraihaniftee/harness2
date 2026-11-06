# Free model selection

| Candidate | OpenCode catalog | Endpoint zero-price/tools | Eligible |
|---|---|---|---|
| `openrouter/google/gemma-4-26b-a4b-it:free` | True | True | True |
| `openrouter/nvidia/nemotron-3.5-lightning:free` | True | True | True |
| `openrouter/recursive/flint-v1.0:free` | True | False | False |

Selection followed the required order. The first choice,
`openrouter/google/gemma-4-26b-a4b-it:free`, passed authenticated model and endpoint metadata
checks but returned HTTP 429 for all seven attempted provider requests, before inference. It was
classified `MODEL_UNAVAILABLE` for this experiment.

The clearly different fallback `openrouter/nvidia/nemotron-3.5-lightning:free` had exact-zero
model and endpoint pricing, one NVIDIA endpoint, `tools` plus `tool_choice`, and an installed
OpenCode catalog entry. All 21 Nemotron responses reported the same exact model and zero cost.
No mutable router or paid fallback was used.
