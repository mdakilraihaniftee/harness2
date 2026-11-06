# Phase 6 research decision

Decision: **STILL_OPERATIONALLY_BLOCKED**.

Phase 6 obtained stronger behavioral evidence but not the first strictly valid composer
decision. Nemotron demonstrably read the evidence, composed A+B, wrote a valid harness, and
achieved hidden deterministic utility 1.0. The response protocol failed. A formatting-only
retry then exhausted its bounded tool budget. These are operational/model-protocol failures,
so they cannot support or refute either research hypothesis.

Across Phase 6 there were 28 provider requests: seven Gemma 429 responses and 21
Nemotron responses. Provider-reported cost was `$0.00`. Account usage
and remaining limit were unchanged. There were no PAVE runs, judges, paid fallbacks, cloud
changes, or model downloads.

The next smallest justified experiment is a single composer gate using a free or local model
with demonstrated instruction-following for file edits and exact tagged output, while retaining
the same frozen CITE context and strict parser. Do not rerun either Phase 6 model unchanged and
do not implement PAVE-R or CITE-R yet.
