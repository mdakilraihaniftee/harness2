# Phase 5: zero-paid composer validation

Phase 5 reuses the frozen Phase 4 contexts. Generated results and traces are ignored by Git.
The read-only audit is safe to repeat and sends no inference request:

```bash
cd /home/ai5377/harness2
.venv/bin/python -m research_pilots.phase5.audit --read-only-provider-audit
.venv/bin/python -m research_pilots.phase5.finalize
```

The completed experiment used the fixed model
`openrouter/cohere/north-mini-code:free`. The preferred
`openrouter/qwen/qwen3-coder:free` was unavailable, while the configured Qwen Flash route was
paid and excluded. The gate used six provider requests at reported cost $0.00, exhausted its
six model steps before an explicit decision, and stopped before PAVE.

The live command is retained for review and reproducibility. Do not rerun the same model/context
unchanged: Phase 5's stop rule prohibits consuming more free quota after this failure. A future
free-model compatibility attempt must first update the exact model allowlist, pass the read-only
zero-pricing audit and tests, and use a fresh sample ID.

```bash
GATE_DIR="$PWD/runs/phase5-free-gate"
mkdir -p "$GATE_DIR" && chmod 700 "$GATE_DIR"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -keyout "$GATE_DIR/key.pem" -out "$GATE_DIR/cert.pem" \
  -subj '/CN=openrouter.ai' -addext 'subjectAltName=DNS:openrouter.ai'

.venv/bin/python -m research_pilots.phase5.zero_cost_gateway \
  --max-requests 26 --unix-socket "$GATE_DIR/openrouter.sock" \
  --cert "$GATE_DIR/cert.pem" --key "$GATE_DIR/key.pem" \
  --ready-file "$GATE_DIR/ready" --events "$GATE_DIR/provider-events.jsonl"
```

In a second terminal, after the gateway is ready:

```bash
export HARNESS2_GATEWAY_CA="$PWD/runs/phase5-free-gate/cert.pem"
export HARNESS2_GATEWAY_SOCKET="$PWD/runs/phase5-free-gate/openrouter.sock"
export HARNESS2_MODELS_SNAPSHOT="$HOME/.cache/opencode/models.json"
export OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=4096

.venv/bin/python -m research_pilots.phase5.live \
  --approve-free-inference --sample-id free-001 --steps 6 --max-sessions 4 \
  --gateway-events "$PWD/runs/phase5-free-gate/provider-events.jsonl"
```

The gateway keeps the real OpenRouter credential on the host. The OpenCode sandbox sees a dummy
credential and only the mounted TLS Unix socket. No judge or full Harness² recursion is invoked.
