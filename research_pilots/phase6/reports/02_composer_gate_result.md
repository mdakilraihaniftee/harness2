# Composer gate result

Final gate classification: **STILL_OPERATIONALLY_BLOCKED**.

- Gemma: 7 requests, all HTTP 429, zero tokens, `$0.00`; `MODEL_UNAVAILABLE`.
- Nemotron 12-step gate: 12 requests, correct valid A+B harness, hidden deterministic utility
  1.0, but invalid final response syntax; `MODEL_PROTOCOL_FAILURE`.
- Nemotron 8-step formatting retry: 9 provider requests, explicit merge analysis in the terminal
  response, no harness writes before tools were disabled; `STEP_BUDGET_EXHAUSTED`.

Neither Nemotron run was a cache hit. No operational fallback, model mismatch, judge call, paid
request, or hidden-oracle disclosure occurred. Gateway caps were 35 Nemotron requests total;
21 were used. The first run used the original 12-step allowance. The final retry was fixed at
8 OpenCode steps and was not expanded.
