# Multi-model design

`ModelSpec` holds provider, model ID, optional endpoint, credential environment-variable name,
and non-secret options. `RunModelConfig` holds the execution harness and four roles. Both are
frozen dataclasses. Serialization contains no credential value; endpoint identity omits URL
credentials, query, and path and adds a stable digest.

Resolution precedence is:

1. Explicit CLI role options (with `--model` as solver/improver convenience).
2. The selected TOML profile.
3. Existing environment variables.
4. Existing defaults.

Selector defaults to the resolved improver, preserving the published behavior. Judge never
inherits `--model`; it remains independent. Legacy bare judge IDs are interpreted using the
existing Vertex convention.

The provider parser splits once. Thus `openrouter/qwen/team/model` becomes provider
`openrouter`, model ID `qwen/team/model`. OpenCode receives provider-prefixed IDs; a custom
OpenAI-compatible route receives `openai/<model>` plus its scoped base URL. Codex receives the
bare model ID because its configured Responses provider owns transport.

## Harness registry

Only `opencode`/`oc` and `codex`/`cx` are registered. The registry records aliases, model
selection mechanism, editable surface, and runtime capabilities. Claude Code, OpenClaw, and
other HarnessAudit runtimes are not adapters in this repository and are not advertised.

## Credentials and concurrency

Every provider subprocess starts from a copy of the process environment with known provider
keys and endpoint overrides removed. Only the selected route's key/reference and endpoint are
restored. The global environment is never mutated to switch models. Vertex continues to use
ADC and project/location variables; no dummy key is installed globally. The separate isolated
LAB gateway safeguard remains unchanged.

## Isolation

The canonical, secret-free configuration is hashed to 16 hexadecimal characters. New run,
rollout, audit, judge, and library data live beneath:

```text
<benchmark-runs>/model-config-<fingerprint>/...
```

The hash covers schema, harness, every role model, endpoint identity, and options. Benchmark,
mode, k, seed, prompt pack, and task stream remain represented by the existing namespace,
BenchSpec, and identity file. Different role configurations cannot share the outer root.
Legacy paths remain untouched and can be read by judge/report fallback.

## Scope decisions

OpenCode is the portable provider path. WorkBuddy's installed Harbor route is generated
specifically for Vertex, so non-Vertex WorkBuddy requests fail before inference instead of
silently using the old model. Codex permits OpenAI, custom Responses endpoints, and the existing
Vertex gateway representation, but this machine lacks the Codex binary. No new HTTP client or
native harness was added.
