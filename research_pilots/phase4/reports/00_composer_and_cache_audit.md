# Composer and cache audit

Repository revision: `322b6f933f3948c9bfeaa85613c55dcc6d602bab`.

| Adapter | Example task | Pack | Aggregate k=1 hash | Repeated-base rule | Unsafe-failed-edit rule |
|---|---|---|---|---|---|
| jobbench | `biostatisticians/task1` | `tts` | `0b21e48b03fbde75412a74a6604a19274cd9df075b09433cc139866a80995bee` | False | False |
| lab | `antitrust-competition/analyze-antitrust-hsr-strategy` | `adapt` | `62eb1aabe9bbb4c14ed08c5b7089d83fedbfdc6280ab4c43ff04e7e41366b816` | True | True |
| research | `invoice/compound-shift` | `adapt` | `01c5e7a32e12106c9c636513574acd28e401461e23019c7b99e5e930b141767f` | True | True |

The PAVE/CITE hypotheses target `adapt`: it explicitly says repeated failures across the base
set are strongest evidence and that edits associated with non-delivery are unsafe. JobBench's
`tts` pack uses variance and product inspection language instead. A `tts` result cannot reject
an `adapt`-prompt hypothesis and is retained only as a prompt-pack control.

`Proposer` cache keys hash label, mission, system, resolved context path and context bytes. The
model is not directly in the private call fingerprint; normal runs remain isolated because the
model configuration fingerprint changes run roots. Phase 4 additionally hashes experiment,
condition, task, sample, model fingerprint, prompt hash and frozen-reference hash into every
sample identity. Two sample labels produced distinct core cache keys: 
`True`.

The offline Qwen configuration fingerprint is
`1dcf401222edb5b3`. Resolution used the
configured model ID when present, a synthetic fallback otherwise, and a non-secret placeholder
credential; no provider was contacted.
