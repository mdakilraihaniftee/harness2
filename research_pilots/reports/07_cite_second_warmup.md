# CITE-R second warm-up

## Current status

**BLOCKED pending explicit paid-call authorization.** No phase-2 live model call has been made.

The deterministic E1 compact context is ready and validated. It presents HA as `inv1` and HB as `dom1`, includes both individually unsuccessful visible trajectories and exact edit contents, and does not expose HAB, its utility, or the hidden required bundle.

## Decision gates

- **E1 compact composer:** PENDING AUTHORIZATION. A valid outcome must include an explicit notes decision, a non-fallback validated tree, actual file diff, and offline classification as A+B, alternative, A only, B only, base, other, invalid, or operational failure.
- **E2 real LLM executor:** NOT_RUN. It is gated on an interpretable E1 result. The existing `U(HAB)=1` is deterministic synthetic evidence only and cannot establish agentic synergy.
- **E3 candidate C:** NOT_RUN. It is gated on interpretable E1 and E2 results. Deterministic apply-all still produces `U(HABC)=0`.

The original-filesystem runs are not valid negative composer evidence: two fell back after metadata errors and the later attempts exhausted their step budget without an explicit decision.

## Authorized command, not executed

The minimal decision gate permits at most two transport/editor attempts and $1 incremental runtime-reported spend:

```bash
.venv/bin/python -m research_pilots.run_phase2_live cite-e1 \
  --approve-paid --max-usd 1 --max-calls 2 --steps 20
```

Do not execute E2 or E3 automatically. Inspect E1 first. If E1 explicitly constructs A+B, the simple CITE synergy-failure hypothesis is unsupported for this interface. If it explicitly rejects a component because its individual rollout failed, that supports a composition investigation but still requires real-executor E2 validation.

