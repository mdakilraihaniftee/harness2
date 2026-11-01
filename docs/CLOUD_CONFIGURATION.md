# Cloud configuration checklist

Audit date: 2026-10-31. This checklist records read-only findings; it does not
authorize billing, IAM changes, API enablement, new resources, or inference.

## Current configuration

| Variable | Effective value | Assessment |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | `graphite-setup-513305-e1` | ACTIVE; tested prediction and service-use permissions granted |
| `GOOGLE_CLOUD_LOCATION` | `global` | Supported by the published Gemini 3.5 Flash model |
| `HARNESS2_SOLVER_MODEL` | `google-vertex/gemini-3.5-flash` | Live solver and improver inference succeeded |
| `HARNESS2_IMPROVER_MODEL` | empty | Valid: inherits the solver model |
| `HARNESS2_JUDGE_MODEL` | `gemini-3.5-flash` | LAB supplies `vertex/`; both judge passes succeeded |
| `HARNESS2_RUNS_DIR` | default unless using experiment script | Script assigns a separate experiment root |

No required variable is currently missing or syntactically invalid for the
default OpenCode/Vertex route. The configured project has billing enabled,
`aiplatform.googleapis.com` enabled, and the permissions required by the run.
`HARNESS2_JUDGE_BASE_URL`/`API_KEY` are optional for the default Gemini judge.
`HARNESS2_CODEX_*` are optional and unnecessary for this OpenCode experiment.
ADC refresh works; shell variables override `.env`. No credentials or access
tokens are included in these documents.

The ADC file currently has no quota project recorded (`quota_project_id` is
unset). Confirm the intended quota/billing project before approved execution;
the audit has not changed the credential file.

Google documents the model ID and global location in the
[Gemini 3.5 Flash reference](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash).
The completed experiment establishes access for this account/project at the
time of the run, but does not guarantee future quota or availability.

## Available projects

The current audit also verifies the configured project:

| Project ID | State | Tested prediction/use permissions | Vertex API | Billing |
|---|---|---|---|---|
| `graphite-setup-513305-e1` | ACTIVE | Granted | ENABLED | Enabled |

The earlier audit also returned these projects using ADC; none was modified:

| Project ID | State | Tested prediction/use permissions | Vertex API | Billing |
|---|---|---|---|---|
| `project-01a55f62-85b2-482c-ab4` | ACTIVE | Granted | DISABLED | Disabled |
| `project-85b0f7e1-892b-49eb-bd6` | ACTIVE | Granted | DISABLED | Disabled |
| `khaddo-panda` | ACTIVE | Granted | DISABLED | Disabled |
| `foodkurt-261b2` | ACTIVE | Granted | DISABLED | Disabled |

The obsolete value `harness2-513305` failed the earlier access checks and is no
longer configured. No project, IAM, billing, or API setting was changed by the
audit or experiment.

## Before approving an experiment

- [x] Select and verify the existing project `graphite-setup-513305-e1`.
- [x] Verify `aiplatform.endpoints.predict` on that project. Google maps prompt
  requests to this permission; `roles/aiplatform.user` is a standard role that
  provides it. Review the role's broader scope before granting it.
- [x] Verify `serviceusage.services.use` for the project consuming API quota;
  `roles/serviceusage.serviceUsageConsumer` provides service use. Configure an
  ADC quota project if required by the organization's policy.
- [x] Verify that billing is active and `aiplatform.googleapis.com` is enabled.
  Enabling the API requires `serviceusage.services.enable`, normally handled by
  a project owner or Service Usage Admin. Neither billing nor API settings were
  changed here.
- [x] Confirm access to `gemini-3.5-flash` in `global` with the approved live run.
  Applicable quota and organization policy can still change. A successful small
  generation is no longer pending.
- [x] Approval was given for the completed refinement and both judge passes.
  Any future paid run requires fresh approval.
- [x] Provision and verify a constrained model/auth gateway and isolation launcher.
  Keep long-lived host credentials and raw benchmark tasks outside agent mounts.
- [x] Refresh the read-only audit before starting; the completed experiment used
  a report less than 24 hours old showing billing, enabled API, and permissions
  for the configured project.

References: [Google's ADC/setup requirements](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/gcp-auth),
[inference access control](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/access-control),
and [Service Usage Consumer role](https://docs.cloud.google.com/iam/docs/roles-permissions/serviceusage).

Refresh safely with:

```bash
source .venv/bin/activate
python scripts/audit_reproduction.py --upstream --cloud
harness2-check --bench lab
harness2-check --bench jb
python examples/infer.py --check-only
```

`infer.py --check-only` checks configuration/ADC, not IAM, billing or generation.
The read-only audit performs the additional cloud metadata checks. Its token is
kept in process memory, and raw API error bodies and credential diagnostics are
suppressed. Account/project visibility is limited to the current ADC principal.
