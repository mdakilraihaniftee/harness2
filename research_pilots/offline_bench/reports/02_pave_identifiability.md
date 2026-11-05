# Experiment 1: PAVE-R evidence identifiability

Two benchmark contexts were used: `data_entry_keyers/task1`, `bankruptcy-restructuring/draft-restructuring-support-agreement`.
The instructions and source layouts are real; execution records and versioned artifact
contracts are `DERIVED_BENCHMARK_TASK` plus `SYNTHETIC_REPLAY`, not original trajectories.

Across 12 paired conditions,
**8 pairs were byte-identical** between a
genuine shift and an evidence defect. No controller can identify hidden cause from those bytes.
Complete original evidence and independent diagnostics break ambiguity; recurrence alone does
not. Provenance IDs state shared source only and never state which source is correct.

The exact transformations were: one truthful execution record for `complete_original_evidence`;
one unlabeled contract-version error for `isolated_misleading_observation`; three byte-equal
unlabeled errors for `repeated_misleading_observation` and `no_independent_diagnostic`; those
same three errors labeled with one factual source ID for `repeated_shared_provenance`; and one
error plus a separately sourced contract probe for `independent_diagnostic`.

| Benchmark | Task | Condition | Cause identifiable | Genuine/defect visible SHA-256 prefix |
|---|---|---|---|---|
| jb | `data_entry_keyers/task1` | complete_original_evidence | yes | `6b0d9f3644bb` / `46d227634a69` |
| jb | `data_entry_keyers/task1` | isolated_misleading_observation | no | `49c98565b4eb` / `49c98565b4eb` |
| jb | `data_entry_keyers/task1` | repeated_misleading_observation | no | `4116c8cb4f60` / `4116c8cb4f60` |
| jb | `data_entry_keyers/task1` | repeated_shared_provenance | no | `2c16da240902` / `2c16da240902` |
| jb | `data_entry_keyers/task1` | independent_diagnostic | yes | `e4aa8d31c6fc` / `fc39d7ed11e0` |
| jb | `data_entry_keyers/task1` | no_independent_diagnostic | no | `4116c8cb4f60` / `4116c8cb4f60` |
| lab | `bankruptcy-restructuring/draft-restructuring-support-agreement` | complete_original_evidence | yes | `6b0d9f3644bb` / `46d227634a69` |
| lab | `bankruptcy-restructuring/draft-restructuring-support-agreement` | isolated_misleading_observation | no | `49c98565b4eb` / `49c98565b4eb` |
| lab | `bankruptcy-restructuring/draft-restructuring-support-agreement` | repeated_misleading_observation | no | `4116c8cb4f60` / `4116c8cb4f60` |
| lab | `bankruptcy-restructuring/draft-restructuring-support-agreement` | repeated_shared_provenance | no | `2c16da240902` / `2c16da240902` |
| lab | `bankruptcy-restructuring/draft-restructuring-support-agreement` | independent_diagnostic | yes | `e4aa8d31c6fc` / `fc39d7ed11e0` |
| lab | `bankruptcy-restructuring/draft-restructuring-support-agreement` | no_independent_diagnostic | no | `4116c8cb4f60` / `4116c8cb4f60` |

| Policy | Correct binary decisions | False adaptations | Missed adaptations | Diagnostic queries |
|---|---:|---:|---:|---:|
| keep | 12/24 | 0 | 12 | 0 |
| repeat_count | 12/24 | 6 | 6 | 0 |
| source_deduplication | 12/24 | 4 | 8 | 0 |
| independent_check | 14/24 | 0 | 10 | 0 |
| diagnostic_first | 4/24 | 0 | 0 | 24 |

Source deduplication prevents the repeated-single-source false adaptation, but necessarily
misses the matching genuine shift. Independent diagnostics are therefore information, not
just reweighting. The negative control changes the environment while preserving original
harness validity; its correct action is KEEP.

Oracle boundary: policies receive only `visible_evidence`; `correct_action_hidden` is joined
afterward for analysis. No official score or LLM decision is present.

## Decision

**REFINE — INFORMATION ACQUISITION REQUIRED**. A complex provenance graph is not justified by these controls. The
smallest useful future study is a paired compact-manifest composer test with and without one
permitted independent diagnostic, holding task, candidates, model, and prompt fixed.
