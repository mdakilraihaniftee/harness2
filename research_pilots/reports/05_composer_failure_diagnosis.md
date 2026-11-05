# Phase 2 composer failure diagnosis

## Conclusion

The original runs did not establish either research failure. They failed for three operational reasons: an expired local gateway certificate before the recorded paid series, a secondary Google SDK metadata lookup in two initial stages, and repeated exhaustion of the OpenCode step budget while browsing filesystem evidence. No run produced an explicit `<notes>` decision in the required grammar. The earlier description of the clean PAVE run as an interpretable decision was therefore too generous: it returned a valid unchanged tree, but its response ended while planning another diff.

The saved evidence has one important forensic limitation. `record_agent_usage.py` retained `step-finish` token/cost records but discarded tool invocation events after forwarding them to the parent process. The audit retained only final assistant text and the harvested final harness. Consequently, exact tool-call counts and complete read sequences cannot be recovered retrospectively. This report names only actions stated in the saved response and reports the exact retained step-event counts separately.

Structured findings are in `research_pilots/results/phase2/original_failure_diagnosis.json`.

## Attempt-level findings

| Attempt group | Provider attempts / retained step events | Recoverable actions and reads | Write / decision | Stage result | Last meaningful action |
|---|---:|---|---|---|---|
| Expired-certificate preflight | 6 / `0,0,0,0,0,0` | None; TLS failed before inference | No / no | No research stage | Certificate error before inference; $0 |
| PAVE A0 clean | 1 / `13` | Glob failed on a dependency/network path; response then describes `ls`, recursive listing, and diffs of DOM/INV candidates. Candidate diffs were read successfully. | No surviving edit / no parseable decision | Valid unchanged tree | Planned another INV comparison |
| PAVE A2 initial | 2 / `10,10` | Tool stream not retained; final responses empty | No / no | Fallback | Secondary metadata lookup warning |
| CITE initial | 2 / `11,11` | Tool stream not retained; final responses empty | No / no | Fallback | Secondary metadata lookup warning |
| PAVE A2 retry 1 | 2 / `10,9` | Response planned reads of current harness and `invoice_rules`; success of those reads is not retained | No surviving edit / no | Valid unchanged tree | Reasoned about the maximum-step instruction |
| CITE retry 1 | 1 / `11` | Planned `context/deliverables/base1/` read; no result retained | No surviving edit / no | Valid unchanged tree | Requested the next read |
| PAVE A2 retry 2 | 1 / `20` | Tool names and paths unrecoverable | No surviving edit / no | Valid unchanged tree | “Please acknowledge the limit and summarize.” |
| CITE retry 2 | 1 / `21` | Tool names and paths unrecoverable | No surviving edit / no | Valid unchanged tree | “STOP! DO NOT CALL ANY TOOLS!” |

`step-finish` events are not asserted to equal tool calls. The configured OpenCode limits were 10 steps initially, 8 in retry 1, and 20 in retry 2; administrative/final events make the retained counts differ from those limits.

## Failure taxonomy

- **Authentication/provider environment:** The old certificate failure occurred before inference. Fresh research certificates fixed TLS. The metadata warning came from a secondary SDK path attempting metadata authentication; the isolated sandbox's non-secret dummy `GOOGLE_VERTEX_API_KEY` prevented that fallback in later retries. No later transcript contains the metadata warning.
- **Tool-call exhaustion:** Confirmed by the final responses in both 20-step retries and the retry-1 maximum-step text.
- **Excessive navigation:** Confirmed in the only descriptive traces. The clean PAVE response was still enumerating and diffing candidates at termination; CITE retry 1 had not progressed beyond requesting base deliverables.
- **Missing or inaccessible files:** Not supported. All mission-listed paths exist in the saved contexts. Reads explicitly described in the clean trace succeeded. Glob's attempted dependency fetch failed, but shell listing/diff provided access.
- **Invalid harness edits:** None. No final tree changed, no validation rejection was recorded, and the two initial failures used fallback before an edit was accepted.
- **Context/token exhaustion:** No provider context-window or output-token error was recorded. The evidence supports step exhaustion, not token exhaustion.
- **Ordinary reasoning failure:** Not assessable because no response completed the required decision format.

## Instrumentation correction

`research_pilots/record_agent_trace.py` now preserves the raw ignored JSONL event stream plus sanitized tool name, status, input path/arguments, output-presence, error, step usage, cost, and runtime for future phase-2 calls. It does not change the model, tools, prompt policy, or executor. New calls remain gated by explicit paid authorization.

