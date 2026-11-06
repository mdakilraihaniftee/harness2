# Composer interface diagnosis

Phase 5's Cohere run used nine reads in six steps and never wrote. The Phase 6 manifest still
contained the complete task, visible execution records, and exact reconstructable patches.

The first neutral navigation instruction told the model to treat the manifest as authoritative
and avoid redundant source reads. Hash: `539f23e646937e73acd6d6741469d15b00844047e08e904bcedd25dc60ea6662`. Nemotron nevertheless made 16 reads,
then wrote the exact A+B harness and an answer without the required `<notes>` wrapper.

The formatting retry prohibited reads of referenced evidence, permitted only destination
harness reads, and required literal notes tags and concrete decision verbs. Its exact text was:

```text
# RESEARCH NAVIGATION POLICY

`context/EVIDENCE_MANIFEST.md` is the authoritative, complete index for this controlled
composer decision. Its candidate patches are exact and reconstructable. After reading that
manifest, do not read referenced trajectories, artifacts, diffs, or candidate harness files;
read only destination files under `context/harness/` that you choose to edit. Proceed directly
to the composition decision and apply any chosen edits. Your final answer and
`output/answer.md` must literally start with `<notes>` and end with `</notes>`. Inside, choose
one literal verb (`kept`, `revised`, or `dropped`) for each line; never copy the placeholder
`kept|revised|dropped`. This controls navigation and protocol formatting only; every original
evidence-weighing and edit adoption rule remains unchanged.
```

Hash: `a6c7f3d6ae3ffb0060a82d814b375e75a2bde3bae37bf6a353ab0cf6c7312321`. The retry still made 20 reads, no writes, and reached the fixed budget.
The interface is compact, but these free models did not reliably follow its navigation and
output protocol. Output-token limits were not reached; navigation consumed the model steps.
