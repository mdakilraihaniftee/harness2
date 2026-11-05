# Test report

Audit environment: Python 3.12.16, OpenCode 1.14.18, Bun 1.3.11. Codex binary unavailable.

| Check | Result | Detail |
|---|---|---|
| Repository unit suite | PASS | 38/38, including 22 multi-model tests |
| Research pilot suite | PASS | 26/26 |
| Deterministic demo | PASS | 2 tasks completed, 0 failed |
| Ruff | PASS | Harness², research pilots, tests, isolated launcher |
| Git whitespace | PASS | `git diff --check` |
| Vertex profile dry-run | PASS | Exact LAB stream printed; nothing executed |
| Profile inspection | PASS | Offline list and validation |
| `harness2-check` LAB/OpenCode | PASS | 1,143 tasks; ADC refreshed; no model call |
| `harness2-check` JobBench/OpenCode | PASS | 65 tasks; ADC refreshed; no model call |
| OpenAI live agent session | NOT_TESTED | Credential absent; separate approval required |
| OpenRouter/Qwen live agent session | NOT_TESTED | Credential/model ID absent; approval required |
| Anthropic live agent session | NOT_TESTED | Credential/model ID absent; approval required |
| Custom endpoint live session | NOT_TESTED | Endpoint/model absent |
| Codex integration | BLOCKED | Configured binary is absent |

The deterministic tests cover profile parsing, CLI precedence, provider parsing, multi-slash
OpenRouter IDs, provider configs, Vertex legacy behavior, credential isolation, missing keys,
runtime restrictions, role separation, fingerprint stability, cache isolation, legacy layout,
judge mapping, OpenCode/Codex argv construction, research defaults, and secret redaction.

Reproduction:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s research_pilots/tests -v
.venv/bin/python -m harness2.cli.demo
.venv/bin/ruff check harness2 research_pilots tests scripts/lab_agent_live_sandbox.py
git diff --check
```
