# Phase 4 research readiness decision

## Decision

**READY_FOR_LIVE_GATE**

PAVE is directly testable at composer level: k=1/k=3 pools are controlled, P2/P4
indistinguishability is explicit, P3 supplies a non-oracular independent observation, and
harmful/unnecessary edits have deterministic post-decision evaluation. Model behavior remains
unknown without inference.

CITE accepts every verified sufficient repair, uses V0/V1 signals weaker than hidden utility,
exposes both relevant edits, and distinguishes an explicit rejection from operational failure.
The A/B gate is credible; C stays gated until that decision completes.

The compact interface, prompt hashes, repetition identities, model fingerprints, candidate
reconstruction, oracle exclusion and prior-result preservation all passed. Qwen live execution
is operationally blocked only by absent runtime model/credential configuration and by the
protocol's explicit paid gate.

Do not implement full PAVE-R or CITE-R from deterministic evidence.
