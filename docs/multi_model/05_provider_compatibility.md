# Provider compatibility

“Runtime compatible” means the installed harness contains the route and deterministic command
construction passed. It does not mean the account serves a particular model. “Live verified”
requires an actual agentic tool/edit session.

| Provider | Harness | Configuration | Credentials | Runtime | Live | Limitation |
|---|---|---|---|---|---|---|
| Google Vertex | OpenCode | PASS | PASS (ADC + project) | PASS | PASS (saved existing composer sessions) | New routing change not re-billed/retested |
| OpenAI | OpenCode | PASS | FAIL (unset) | PASS | NOT_TESTED | Exact account model/tool capability unknown |
| OpenRouter/Qwen | OpenCode | PASS | FAIL (unset) | PASS | NOT_TESTED | Set provider-reported multi-segment ID |
| Anthropic | OpenCode | PASS | FAIL (unset) | PASS | NOT_TESTED | Direct API route unverified live |
| Custom OpenAI-compatible | OpenCode | PASS | FAIL (unset) | PASS | NOT_TESTED | Endpoint must support agent tool calls, not text only |
| Existing gateway | Codex | PASS | configured separately | BLOCKED | NOT_TESTED | Codex binary absent |
| Non-Vertex providers | WorkBuddy/Harbor | FAIL | NOT_TESTED | FAIL | NOT_TESTED | Installed route is Vertex-specific |

The pinned OpenCode source has loaders for OpenAI Responses, Anthropic, OpenRouter, and Google
Vertex. Model catalogs are provider/account dependent, so the compatibility report uses
environment-referenced GPT/Qwen identifiers instead of names copied from papers.
