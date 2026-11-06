# Free composer compatibility

Gate outcome: **MODEL_CAPABILITY_FAILURE**.

One CITE V1 session used `openrouter/cohere/north-mini-code:free`, the original `adapt` prompt, frozen compact
manifest, OpenCode, and no judge. The model read the manifest and all relevant candidate
trajectories, but spent all six turns reading evidence. It made no file write and returned no
parseable `<notes>` decision. Its final response explicitly said the maximum step budget had
been reached. The tree remained base only because no edit occurred; this is an operational
failure and is not a KEEP_BASE composer decision.

The exact provider model was `cohere/north-mini-code:free` for all
6 requests. Provider telemetry recorded 72822
input, 1408 completion, 908
reasoning, and 0 cache-read tokens at
`$0.00`. Runtime wall time was 14.9
seconds. The model used nine read tools and zero write tools.

The engineering route worked, but this model did not complete the Harness² composer protocol
within the conservative gate. Per the protocol, no unchanged retry and no PAVE session followed.
