# Cost and free-model audit

Status: **PASS for the selected route**.

The requested Qwen route `openrouter/qwen/qwen3-coder:free` returned HTTP 404 from the
authenticated exact-model endpoint and was absent from OpenCode 1.14.18's installed catalog.
It was not called. The configured `openrouter/qwen/qwen3-coder-flash` has positive input,
output, and cache prices and was excluded.

The fixed fallback `openrouter/cohere/north-mini-code:free` was present in both the authenticated provider catalog
and installed OpenCode catalog. Its advertised pricing was `{'completion': '0', 'prompt': '0'}`, and it
advertised `tools` plus `tool_choice`. The gateway required the exact model, rejected a `models`
fallback list, disabled provider fallback, applied zero prompt/completion/image/request ceilings,
requested provider usage telemetry, and capped the experiment at 26 provider requests.

The key reported `is_free_tier=True`, limit
`100`, and unchanged remaining limit
`99.92198202`. This is a finite key-level limit; no account
or billing setting was changed. Six generation requests reported total provider cost `$0.00`.

Preferred-route blocker: provider metadata request returned HTTP 404.
