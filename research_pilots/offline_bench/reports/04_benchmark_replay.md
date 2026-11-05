# Experiment 3: benchmark-native context replay

| Benchmark | Task | Evidence variants | Transformation placement | Candidate reconstruction |
|---|---|---:|---|---|
| jb | `data_entry_keyers/task1` | 3 | PASS | PASS |
| lab | `bankruptcy-restructuring/draft-restructuring-support-agreement` | 3 | PASS | PASS |

The real adapters supplied task instructions, source paths, leak rules, and editable OpenCode
surface. `harness2.core.context.build` constructed normal contexts. Compact manifests retained
candidate IDs/scopes, exact diffs, original paths, and optional factual source IDs. All
references were accessible, all candidates reconstructed exactly, and hidden markers were
absent.

No sampled task had a suitable native saved trajectory. Consequently the suite used
**6 explicitly labeled synthetic replay views** and zero real
saved trajectories. These are technical-feasibility contexts, not completed LAB/JobBench runs.
Provenance categories are stored per task and are not interchangeable.
