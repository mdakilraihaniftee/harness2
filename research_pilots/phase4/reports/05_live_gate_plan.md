# Minimal live gate plan

Target: Qwen through the `qwen` OpenRouter profile, OpenCode harness, one controlled CITE A/B
compact-manifest composer stage, `adapt` prompt pack, no solver regeneration and no judge.

Current preflight: model ID present = `True`; credential present =
`True`. Put both values in the ignored `.env`; do not paste the
credential into a report or command history. The command remains blocked until both exist and
the exact model appears in the frozen OpenCode model catalog.

Prepare the local TLS socket once (no provider call):

```bash
cd /home/ai5377/harness2
GATE_DIR="$PWD/runs/phase4-qwen-gate"
mkdir -p "$GATE_DIR"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -keyout "$GATE_DIR/key.pem" -out "$GATE_DIR/cert.pem" \
  -subj '/CN=openrouter.ai' -addext 'subjectAltName=DNS:openrouter.ai'
```

Start the trusted host gateway in terminal 1. It loads the ignored `.env`, retains the real key
on the host, permits only the configured Qwen model and stops accepting provider turns after
the 20-step composer bound:

```bash
cd /home/ai5377/harness2
GATE_DIR="$PWD/runs/phase4-qwen-gate"
.venv/bin/python -m research_pilots.phase4.openrouter_gateway \
  --max-requests 20 --unix-socket "$GATE_DIR/openrouter.sock" \
  --cert "$GATE_DIR/cert.pem" --key "$GATE_DIR/key.pem" \
  --ready-file "$GATE_DIR/ready"
```

After `ready` exists, run the separately authorized gate in terminal 2:

```bash
cd /home/ai5377/harness2
GATE_DIR="$PWD/runs/phase4-qwen-gate"
export HARNESS2_GATEWAY_CA="$GATE_DIR/cert.pem"
export HARNESS2_GATEWAY_SOCKET="$GATE_DIR/openrouter.sock"
export HARNESS2_MODELS_SNAPSHOT="$HOME/.cache/opencode/models.json"
export OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=4096
.venv/bin/python -m research_pilots.phase4.live_gate cite-e1 \
  --approve-paid --model-profile qwen --sample-id gate-001 \
  --max-usd 1 --max-calls 2 --steps 20
```

Expected work: one composer session. The transport-session cap is 2, the gateway provider-turn
cap is 20, and the declared incremental spend cap is $1.00; spend is known from provider
telemetry after a session, so no second session starts after the cap is reached. The sandbox has
no network namespace and sees only a dummy credential plus the allowlisted Unix socket. There
is no external judge, full benchmark execution or cloud change. Success requires manifest
access, a cache miss, explicit decision, valid tree, no fallback and no step exhaustion. Any
interface failure stops retries.
