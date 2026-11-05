# Research decision: PAVE-R and CITE-R feasibility

## Section A: Executive summary

The repository and deterministic experimental infrastructure are ready. The baseline passed both recursion modes; 16/16 repository tests and 15/15 pilot tests passed; Ruff passed. Evidence transformations, hidden evaluation, cache isolation, bundle recombination, cost caps, and raw audit retention are implemented under `research_pilots/`.

Neither central live hypothesis is currently established. PAVE-R's clean case was robust, while all systematic-corruption attempts were operationally confounded. CITE-R has a validated deterministic A+B synergy and C interference pattern, but the real composer exhausted its browsing/tool budget before making an interpretable decision. Natural proposers, full `k=3`, selector behavior, and experience transfer were not run.

Seven capped live research sessions (ten stage attempts) used `google-vertex/gemini-3.5-flash`. Runtime-reported spend was $1.129509, aggregate recorded wall time was 644.9 seconds, and raw provider counters were 365,327 input, 7,957 output, 29,494 reasoning, and 1,629,729 cache-read tokens. Categories can overlap; see `research_pilots/results/live_usage_summary.json`. No further paid calls are recommended until the evidence interface is compacted.

## Section B: Repository readiness

Harness² supports both settings with small research-only extensions. `BenchmarkAdapter.trajectory()` is a clean intervention boundary for PAVE-R. Candidate trees are ordinary file maps, and existing parsing/validation supports a minimal CITE-R recombination prototype. Run namespaces, per-condition tokens, and separate output roots prevent cross-condition result reuse.

The main remaining risks are:

- Composer-visible evidence has no structured provenance, so common-cause versus independent identical observations is non-identifiable.
- Candidate diffs are file-level, while semantic dependencies can cross files.
- At `k=1`, selection is trivial and excludes the original base.
- A false reflected lesson can affect later same-domain tasks.
- The live agent spent its available steps navigating a small context, so the current interface can obscure the research mechanism.

The only production-adjacent change is a dummy non-secret `GOOGLE_VERTEX_API_KEY` inside the isolated live sandbox, preventing an SDK metadata-auth fallback while the gateway continues to provide ADC OAuth. No algorithm, benchmark adapter, cloud resource, or global dependency was changed.

## Section C: Idea 1 results

A0 clean, A1 isolated, A2 systematic, and A2 matched-independent views were rendered from immutable raw executions. All injection assertions pass. A2 systematic and matched-independent contexts are byte-identical, proving the baseline lacks information about hidden dependence unless provenance is supplied.

The no-fault base has hidden utility 1.0; the controlled retry edit has utility 0.0. The genuine schema-shift base has utility 0.0 and reference repair 1.0. In the sole interpretable live clean session, the composer recognized the harmful resubmission diff and kept base with utility 1.0. Three systematic sessions kept or fell back to base, but metadata and step-exhaustion failures make them inconclusive. There was no harmful adopted harness and therefore no library-transfer test.

PAVE live spend was $0.653340 over four sessions. The central claim—that repeated correlated failures cause a harmful change—is unsupported by the present evidence. It is also not refuted because the relevant composer decisions did not complete.

## Section D: Idea 2 results

The deterministic fixture validates `U(H0)=U(HA)=U(HB)=0`, `U(HAB)=1`, and `U(HABC)=0`, giving `Gamma_AB=1.0` and interference 1.0. A validated file-level prototype can build HAB and reject conflicts or dependency-incomplete bundles.

The controlled real composer received both correct individual edits and their failed rollouts. It returned/fell back to H0 in all three attempts, but the transcripts show metadata failure or tool-step exhaustion rather than an explicit composition judgment. CITE live spend was $0.476169. Original candidate generation, same-scope versus cross-scope comparison, selector behavior, and natural execution were not run.

The central claim—that the composer rejects jointly useful edits because their individual executions fail—is unsupported by current live evidence. The deterministic fixture establishes a valid question, not the model behavior.

## Section E: Research refinement

| Idea | Warm-up class | Research choice | Evidence-based reason |
|---|---|---|---|
| PAVE-R | A-BLOCKED | INCONCLUSIVE / NEEDS MORE EVIDENCE | Valid intervention and positive control; clean run robust; no interpretable systematic composer decision or harmful adoption. |
| CITE-R | B-BLOCKED | REFINE | Strong deterministic synergy/interference and cheap recombination, but live composition behavior is confounded and natural generation is unknown. |

PAVE-R has the sharper information-theoretic observation: visible recurrence cannot reveal hidden common cause. CITE-R currently has the clearer controlled utility signal and lower-cost hidden evaluator. Both risk being solved by a simple baseline once evidence is presented compactly; that is precisely the next test, not a reason to build a complex method now.

## Section F: Next implementation recommendation

Implement one shared, research-only compact evidence manifest before either full method. It should list candidate ID, provenance/source ID, file diff, execution outcome, and artifact pointer in one bounded document while preserving the original aggregate prompt and all hidden-oracle restrictions.

For PAVE-R, the smallest worthwhile next component is an offline provenance-deduplication baseline over this manifest: compare ordinary repeated evidence with one vote per source. For CITE-R, the smallest component is a two-candidate controlled composer case using the same compact manifest, followed only if needed by deterministic enumeration of structurally compatible pairs as an oracle upper bound.

This recommendation directly targets the observed browsing bottleneck and makes both hypotheses falsifiable without implementing provenance-aware adaptation or combinatorial bundle search.

## Section G: Prioritized next steps

1. Add compact manifest rendering in `research_pilots/adapter.py` or a research wrapper around `harness2/core/context.py`; do not alter global truncation. Add four tests: contents, provenance isolation, oracle exclusion, and size bound.
2. Re-run one clean/systematic/matched-independent PAVE composer triplet. Invalidate the revised hypothesis if systematic corruption does not increase unnecessary or harmful edits relative to both controls across repeated completed sessions.
3. Re-run the controlled CITE A/B composer. Add three tests for manifest candidate mapping, composed-tree validation, and hidden-score exclusion. Invalidate the revised hypothesis if the original composer reliably constructs HAB despite both failed singles.
4. Only after a completed failure, run natural INV/DOM generation and a two-task library-transfer check. Add approximately four integration tests for categorization, adoption, reflection admission, and clean follow-up behavior.
5. Keep a hard per-run call/spend cap. Current cloud/model access works, but latency and tool-step exhaustion—not the $20 cap—are the dominant uncertainty. Do not spend more until the compact interface passes deterministic tests.

Estimated additional tests before any full method: 7 for the shared manifest and controlled reruns, then 4 only if natural pipeline/library testing becomes justified.

## Reproduction commands

The deterministic portion is safe and incurs no model cost:

```bash
cd /home/ai5377/harness2
.venv/bin/python -m research_pilots.run_deterministic
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s research_pilots/tests -v
.venv/bin/ruff check research_pilots scripts/lab_agent_live_sandbox.py
.venv/bin/python -m research_pilots.finalize_results
```

The live script is deliberately gated and should not be rerun merely to reproduce the deterministic artifacts. After starting the already-documented isolated gateway and exporting its socket, CA, and model snapshot paths, an explicitly approved capped run is:

```bash
.venv/bin/python -m research_pilots.run_live --approve-paid --max-usd 20
```

Targeted retries are also paid and require a cumulative call cap:

```bash
.venv/bin/python -m research_pilots.retry_live --approve-paid --trial retry1 --steps 8 --max-calls 5
```

No live command is needed to inspect the saved results.

## Final decision table

| Dimension | PAVE-R | CITE-R |
|---|---|---|
| Observed live failure mechanism | No | No; operational browsing failure only |
| Deterministic fixture validity | Yes | Yes |
| Hidden evaluation | Easy, but true state intentionally unavailable to composer | Easy and exact |
| Fit with Harness² | Good at adapter trajectory boundary | Good at tree/diff boundary |
| Full implementation now | No | No |
| Next decision gate | Reproduce harmful evidence-driven adoption | Obtain an interpretable A/B composer decision |
| Recommendation | Needs more evidence; focus on identifiability | Refine controlled composition test |

The machine-readable outcome index is `research_pilots/results/experiment_summary.json` with a CSV mirror at `research_pilots/results/experiment_summary.csv`.
