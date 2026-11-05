# Harness² repository audit

Audit date: 2026-11-05 (US/Eastern)

## Checkout and environment

- Repository: `/home/ai5377/harness2`
- Commit at start: `5e1f7913b6f0d61fe165a84a3f0a2e946b01c720`
- Branch: `main`
- Initial status: clean. All pilot work was isolated under `research_pilots/`, except the minimal live-sandbox authentication guard in `scripts/lab_agent_live_sandbox.py`.
- Python: 3.12.16 from `.venv`
- Test convention: standard-library `unittest`; Ruff is installed in `.venv`.
- Live path: OpenCode substrate through the existing local Vertex gateway; model `google-vertex/gemini-3.5-flash`. Application Default Credentials and model connectivity were validated before paid calls. No cloud resources were created or changed.

The requested files were inspected: `README.md`, `pyproject.toml`, demo entry points, all named `harness2/core` modules, tests, and benchmark adapters. The checkout is internally consistent with its current documentation; this audit follows the checked-out implementation rather than assuming an older upstream interface.

## Important implementation points

| Concern | Actual source and behavior |
|---|---|
| Scheduling and base runs | `harness2/core/schedule.py::_roll_bases` creates shared `base1..basek` executions. The adapter owns execution and run-directory reuse. |
| Parallel recursion | `harness2/core/recursion.py::run_parallel` produces `k` INV and `k` DOM trees from shared base evidence, executes all `2k`, composes `k` independent `agg` trees from the candidate pool, and executes those finals. |
| Sequential recursion | `harness2/core/recursion.py::run_sequential` performs `k` rounds. Each round proposes INV and DOM relative to the current checkpoint, executes both, composes `c<t>`, executes it, and carries that tree forward. |
| Stage failure handling | `harness2/core/recursion.py::_run_stage` gives an invalid editor result one feedback retry. After two invalid attempts, it records the error and returns the supplied fallback tree. |
| Execution | `harness2/core/recursion.py::_roll_many` writes candidate trees and calls the benchmark adapter. Batch execution is used when available; failures become explicit dead `RunView`s. |
| Evidence tree | `harness2/core/context.py::build` writes `task.md`, source, base rollouts, deliverables, current harness, candidate pool, prior decisions, and optional library. `obs_trunc` is per observation; the trajectory is otherwise written in full. |
| Deliverables | `BenchSpec.proposer_deliverables` selects `names` or `contents`. Pool entries contain a harness diff, full candidate harness, rendered rollout, and produced artifact. Clean artifacts can contradict a trajectory only when their contents expose the relevant state. |
| Composition prompt | `harness2/core/prompts.py` tells the composer that repeated base failure is strong evidence and a single candidate outcome is weak, while also allowing it to leave the base tree unchanged. Composition is an editor session, not a deterministic patch vote. |
| Selection | `harness2/core/selection.py::selection_pool` includes exactly the `k` composed finals and deliberately excludes base and proposal rollouts. At `k=1`, the sole final is adopted trivially without an LLM selector call. A composed final can still equal the base tree. |
| Experience library | `harness2/core/library.py::Library` is scoped by run, mode, and domain. It starts empty and stores the full adopted tree only when reflection supplies nonempty `cue`, `lesson`, and `evidence`. Earlier same-domain tasks become context for later tasks, so a false admitted lesson can transfer. |
| Budget | `harness2/core/ledger.py::Ledger.assert_identity` enforces unique labels and `R=4k`, `P=3k`. Retries increase `session_attempts` but not the number of logical stages. Selection and reflection are outside this ledger. |
| Tree safety | `harness2/core/tree.py::validate` enforces surface paths, always-on limits, Python compilation, skill triggers, script references, hooks, and subagent policy. |
| Resume identity | `harness2/core/runmark.py` fingerprints the adopted harness. Resume checks the completion mark, summary, chosen output/delivery, and harness fingerprint. Run namespaces include benchmark, substrate, mode, `k`, seed/tag, task, and label. |

## Actual data flow

1. `schedule` loads the task/domain, obtains the base harness, and creates the shared base runs.
2. INV and DOM editor sessions receive contexts made by `context.build`; proposed trees are parsed and validated.
3. Candidate trees are executed by the adapter and their trajectories and artifacts are added to the aggregate/composition context.
4. The composer edits the original/current tree with access to candidate diffs and outcomes; its result is validated and executed.
5. Selection compares only composed finals. At `k=1`, selection is mechanical.
6. Reflection sees the complete round and may create an experience record. A valid record and the adopted full harness are appended to the per-domain library.

For parallel and sequential recursion the logical budget is the same: `k` base rollouts + `2k` candidate rollouts + `k` final rollouts = `R=4k`; `2k` proposal sessions + `k` composition sessions = `P=3k`.

## Evidence and identity findings

- Full base trajectories and candidate trajectories are composer-visible. A renderer defect can therefore repeat in multiple files.
- Candidate deliverables remain separately visible and can rebut a bad trajectory only if they contain an independent state signal. The pilot deliberately uses an artifact that does not reveal transaction state.
- The prompt treats recurrence as evidence but also explicitly warns that candidates are weak single observations. It does not carry structured provenance or a common-cause model.
- Production truncation safeguards were not changed. The research adapter transforms `trajectory()` output only.
- Each evidence condition has a unique cache token and directory. The same immutable raw execution can safely be rendered into several contexts without reusing a condition's final result.
- Systematic and matched-independent corruption have identical visible context bytes in this pilot. No baseline method can infer their different hidden causes without provenance or an external diagnostic signal.

## Confirmed and false assumptions

Confirmed:

- Candidate edits can be retained by composition even when an individual rollout is weak or failed; there is no hard success filter before composition.
- The composer can keep the base by returning an unchanged tree.
- Invalid patches are retried once, then safely fall back.
- Experience can affect later same-domain tasks.
- File-level recombination is mechanically feasible for non-conflicting edits and can reuse existing validation.

False or narrower than expected:

- Selection cannot choose the original base directly; the base is absent from the selection pool.
- `k=1` does not exercise an LLM selector and cannot test recurrence across base rollouts.
- The stage ledger does not include selection or reflection calls.
- Fixed seeds do not make live model sessions deterministic.
- Repeated visible errors alone do not reveal whether their failures share a source.

## Risks and available capabilities

The main research risks are evidence non-identifiability, false library transfer, semantic dependencies hidden behind file-level diffs, and live agents consuming their tool-step budget browsing a large file context before deciding. The latter occurred in the warm-up.

The repository is ready for deterministic recursion, both recursion modes, synthetic adapters, context-level evidence interventions, hidden offline evaluation, tree validation, resume checks, and capped live editor sessions. A full natural proposer/selector experiment is technically available but was not justified after the controlled live composer runs became operationally inconclusive.

