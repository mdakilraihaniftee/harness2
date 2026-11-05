# Compact evidence manifest validation

## Status

Deterministic interface validation: **PASS**. Live interface validation: **PENDING AUTHORIZATION**.

The final read-only readiness check passed with network access: ADC refresh works, the configured project is active, required prediction/service-usage permissions are granted, Vertex AI is enabled, and billing is enabled. Model availability remains intentionally untested because that would require a model call. The first sandboxed check failed only because DNS/network access was restricted, not because the credentials were invalid. No cloud resource was changed.

The implementation is research-only: `research_pilots/manifest.py`, deterministic context preparation in `research_pilots/prepare_phase2.py`, and the paid gate in `research_pilots/run_phase2_live.py`. Original context files remain present and authoritative.

## Contents and safety

Each manifest contains the task instruction, base identifier, candidate ID and INV/DOM scope, changed paths, exact full `before` and `after` contents for every changed file, visible trajectory, visible errors, original trajectory/artifact/diff/full-harness paths, and an opaque evidence-condition token. Provenance source IDs appear only in the explicitly provenance-enabled PAVE condition.

The manifests exclude hidden utilities, reference repairs, required bundles, known successful combinations, hidden labels, and causal claims. Automated reconstruction applies each embedded edit record to the base and exactly reproduces the corresponding candidate tree.

The only composer-policy addition is:

> Read `context/EVIDENCE_MANIFEST.md` first. It faithfully consolidates every base rollout and candidate's identifier, scope, exact changed-file contents, visible execution result, and paths to the original evidence. Reading every entry in that manifest satisfies the inventory and inspect-each-candidate-once requirements. Open the referenced original files only when the manifest leaves a material ambiguity. All composition and evidence-weighing rules above are unchanged.

All other aggregate prompt text, candidates, trajectories, artifacts, model settings, evaluation logic, and editable harness files remain unchanged. This is a `COMPACT_MANIFEST` interface intervention, not PAVE-R or CITE-R.

## Measured manifests

| Context | Characters | Estimated tokens | Candidates | Provenance visible |
|---|---:|---:|---:|---|
| CITE E1 | 2,669 | 668 | 2 | No |
| PAVE clean | 5,457 | 1,365 | 6 | No |
| PAVE isolated | 5,461 | 1,366 | 6 | No |
| PAVE systematic | 5,610 | 1,403 | 6 | No |
| PAVE systematic + provenance | 6,069 | 1,518 | 6 | Yes |

These are below the suggested 2,000–4,000-token target because the synthetic fixtures and patches are very small. No essential content was truncated to reach that size. Full manifests and metadata are in `research_pilots/results/phase2/manifests/`.

## Deterministic acceptance checks

| Check | Result |
|---|---|
| Correct candidate IDs | PASS |
| Candidate-to-file mappings | PASS |
| Exact reconstruction from manifest edits | PASS |
| Original evidence preserved byte-for-byte | PASS |
| Hidden-oracle marker exclusion | PASS |
| Distinct opaque condition tokens | PASS |
| Size bounded and reported | PASS |
| Every referenced workspace path exists | PASS |
| Provenance shown only when enabled | PASS |
| Paid runner requires explicit flag and cap | PASS |

The next decision gate is one CITE E1 composer stage with the same model, 20-step setting used by the last original-filesystem retry, original aggregate policy, and controlled A/B pool. A scientifically valid result additionally requires a valid non-fallback tree and a parseable `<notes>` decision; `_run_stage`'s acceptance of any unchanged harvested tree is not sufficient by itself.

