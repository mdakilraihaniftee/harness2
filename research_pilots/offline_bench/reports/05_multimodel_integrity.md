# Experiment 4: multi-model configuration integrity

| Profile | Solver | Improver | Selector | Judge | Configuration verified | Invocation constructed | Real tool call | Real edit |
|---|---|---|---|---|---|---|---|---|
| existing_vertex | `google-vertex/gemini-3.5-flash` | `google-vertex/gemini-3.5-flash` | `google-vertex/gemini-3.5-flash` | `google-vertex/gemini-3.5-flash` | true | true | false | false |
| gpt | `openai/offline-gpt-synthetic-id` | `openai/offline-gpt-synthetic-id` | `openai/offline-gpt-synthetic-id` | `openai/offline-gpt-judge-synthetic-id` | true | true | false | false |
| qwen | `openrouter/qwen/offline-synthetic-id` | `openrouter/qwen/offline-synthetic-id` | `openrouter/qwen/offline-synthetic-id` | `openrouter/offline-judge-synthetic-id` | true | true | false | false |
| mixed | `openrouter/qwen/offline-synthetic-id` | `openai/offline-gpt-synthetic-id` | `openai/offline-gpt-synthetic-id` | `openai/offline-gpt-judge-synthetic-id` | true | true | false | false |

All fingerprints were distinct: `True`. Model changes preserve
the exact 12-task selection and the same model-independent manifest hashes while isolating run
roots/caches. Provider environments retained only each selected provider credential. Hidden
oracles remained excluded.

Synthetic model IDs and placeholder credential strings were used. Invocation construction is
an argv/configuration assertion only. OpenAI, OpenRouter/Qwen, and mixed routes remain
`NOT_TESTED` live; no tool call or edit is claimed.
