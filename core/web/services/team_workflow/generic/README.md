# User-defined team workflows

The service is the sole flow/run state owner. The existing Team namespace supplies formal/developer storage roots; atomic JSON snapshots and cross-process locks enforce revisions. User definitions and each run's frozen copy are distinct. New HTTP endpoints are additive version-one contracts and do not modify retained research routes or require a question ID.

- `models.py`: bounded public contracts, unique field/step IDs and input validation.
- `store.py`: Team authority, validated path components, atomic writes and CAS locks.
- `service.py`: explicit run commands, sequential transitions, frozen inputs and durable dispatch receipts. An assigned output executes its configured Agent; an unassigned output delivers prior results.
- `native.py`: existing Agent-scoped hidden workspace Sessions, stable create/submission identity, canonical completion and verified restart-resume chains. Stop targets the effective Turn. Only references and lifecycle records are stored; Session remains transcript authority.
- `binding.py`: explicit recovery-role opt-in, live authorization checks, policy fingerprints, expiry and CAS revocation over the existing source flow.
- `result_contract.py`: bounded validation of opt-in business outcomes after canonical native Turn success; default text results remain compatible.
- `recovery.py`: bounded failure escalation, frozen repair recipes, child-run coordination and safe replay decisions.
- `research_source.py`: read-only formal Ledger references, bounded retry lineage and native command replay; `supervision.py` projects these facts into the existing repair coordinator.
- `session_source.py`: read-only ordinary Session task references and verified native regenerate/resume lineage; `source_adapter.py` selects the existing source contract without creating another coordinator.
- `runtime.py`: one owned reconciliation worker. Reads do not dispatch. Startup waits for native Session recovery; delayed callbacks are fenced by the lifespan stop flag under the admission lock. Shutdown closes this producer before native Session workers.

Retry may create a new attempt only after canonical evidence permits it. Unknown Session identity or active-state uncertainty fails visibly and prevents duplicate execution or false stop success. Flow/run lists remain readable while execution is warming; artifact projection waits for the owner. Membership and Agent availability are checked again before dispatch. No raw model invocation or changes to ordinary Session core are introduced.

Tests use temporary Team storage and a substituted native port. Those tests prove orchestration and adapters, not real model output quality or a live application's restart acceptance.

## Opt-in failure recovery

`Flow.failureRecovery` is the sole stored authorization for the new role binding;
there is no second role registry. Binding requires the canonical, ready Personal
Assistant and distinct existing `assistantAgentId`, `directorAgentId`,
`developerAgentId` and `reviewerAgentId` identities. All roles and executable
source-step owners must be available Team members with resolved tool policies.
The binding records their policy fingerprints, a `bindingId`, expiry and the
saved `repairFlowId` revision. Binding creates no Agent or Session and grants no
tools, workspace scopes or permissions. `automaticLocalIntegration` and
`automaticDeployment` remain fixed to `false`.

The typed HTTP contracts share `/teams/{team_id}/workflows/{flow_id}`:

| Method / suffix | Request / response | Behavior |
| --- | --- | --- |
| `PUT /recovery-binding` | `RecoveryBindingRequest` / `RecoveryBindingStatus` | Requires `expectedRevision` CAS and explicit `acknowledgeAutomaticRecovery=true`; validates roles and the saved repair recipe before binding |
| `GET /recovery-binding` | No body / `RecoveryBindingStatus` | Read-only readiness, identity, expiry and reason projection; no provisioning or dispatch |
| `POST /recovery-binding/revoke` | `RecoveryBindingRevoke` / `RecoveryBindingStatus` | Requires `expectedRevision` CAS; clears the existing source-flow binding and wakes reconciliation |

The policy retains `replaySafety` (`unknown` by default), `maxAttempts` (1–3,
default 3), `maxRepairAttempts` (1–3, default 2), and
`repairTimeoutSeconds` (60–86400, default 1800). Existing flows without a policy
retain manual failure/retry behavior. Ordinary Sessions, research Ledger tasks
and other evolution runs do not automatically acquire this policy.

The Personal Assistant exposes only the closed manage actions
`workflow_recovery_bind`, `workflow_recovery_revoke` and `workflow_start` for this
handoff, through its existing manage tool. Its existing approval requirement
still applies to every call. Assistant identity comes from the canonical native
Session, never a caller-supplied `assistantAgentId`; start requires a ready binding
owned by that assistant, and revoke/overview cannot cross assistant ownership.
The workflow overview returns binding status and at most 20 matching run-status
summaries, with no input values, transcripts, private objects or secrets.

The repair flow must have only one text/paragraph input, `incident`. Its first
executable step belongs to the director; its final step belongs to an independent
reviewer who does not implement or diagnose the candidate. At least one developer
step with a third Agent identity must sit between them. Human approval steps are
not allowed inside the automatic repair child; deployment approval is owned by
the source run. It cannot recursively opt into recovery. Source start
validates live Team membership and freezes this definition. Dispatch and replay
recheck membership and, for a new binding, live authorization. Revocation,
rebinding, expiry, assistant unavailability or a recorded role/source-owner policy
change fences automatic child admission and replay. Changing only the saved
repair recipe makes the binding unavailable for new source starts; existing runs
still use their frozen recipe while the live binding remains valid. Native stop
and settled termination continue to require native evidence.

Policies without `bindingId` are reported as `legacy` and retain their frozen-run
semantics: changing or disabling their saved definition affects future runs;
stop the original run to cancel its in-flight recovery. Newly bound runs instead
recheck the source flow's current binding, so revocation or rebinding also blocks
their subsequent automatic child/replay dispatch.

## Business result contracts

Executable steps default to `resultContract=text`, preserving existing text
completion behavior. `outcome_v1` opts into strict JSON validation after successful
native completion, using the exact assistant Turn result. It accepts only
`taskStatus` (`succeeded`/`failed`), `problemCode` and nonempty bounded `evidenceRefs`;
duplicate or unknown fields, malformed JSON and invalid bounds fail validation.
A failed outcome requires a bounded `problemCode`; success cannot carry a
nonempty problem code. A declared business failure or invalid outcome becomes a
failed attempt with `failureOrigin=result_contract` (invalid output uses
`business_result_invalid`), allowing the same bounded recovery policy to handle
native success whose business result failed. This validation does not assert
that the reported effects occurred in a real application.
The namespaced `taskStatus` avoids interpreting a business outcome as the native
runtime's reserved top-level `status` control result. No ordinary Session
formatting or completion semantics are changed.

## Recovery execution and evidence

`recovery.py` counts distinct persisted failed attempts at the original node,
using the native `terminalProblemCode` (fallback: terminal status). A changed code
resets the consecutive streak; it never refunds the node's total attempt budget.
Existing attempt exhaustion or three consecutive failures, whichever comes first,
queues repair. Read-only/idempotent operations may retry before this threshold;
unknown side effects require an operator's existing explicit retry decision.
Native `safe_new_attempt` proves settled execution, not replay safety.

The parent persists an issue ID and child dispatch intent before creating a
repair run through the existing store/executor. Restart and uncertain creation
reuse that identity. The child remains the native Session/Turn execution owner;
the parent retains references and recovery state. Failed repairs consume the
same bounded budget across scans/restarts. Timeout blocks further dispatch and
requests the existing child stop; termination still follows native evidence.

The last reviewer must return strict JSON with `verdict` (`passed`/`failed`),
`deploymentRequired` (boolean), `effectVerified` (boolean), and nonempty bounded
`evidenceRefs`. The coordinator reads this from the exact reviewer's successful
native Turn; developer output and delivery success cannot stand in for it. The
reviewer must check actual effects, including whether a code change has loaded.
This verdict is evidence for **safe replay**, not an independent Git promotion
capability; code changes still use the existing isolated candidate, quality gate
and integration owner. The original step must then succeed before `resolved`.

If deployment is needed, the source stays failed with
`recovery.status=awaiting_deployment`. The existing commands endpoint accepts an
additive `confirm_deployment` action with `expectedRevision` and a nonempty
`evidenceRef`; it records the user's confirmation and queues a new reviewer-only
verification run. It does not deploy or declare the repair effective. Only that
fresh check can permit replay. Unknown side effects remain at
`awaiting_replay_decision` until the user explicitly retries. Original run stop
cancels recovery and propagates stop to its existing child. A child cannot be
manually retried/revised outside its parent's bounded recovery budget.

| Fact | Authority / writer | Readers / refresh |
| --- | --- | --- |
| Definition and execution recipe | Team flow JSON / `service.save_flow` | Frozen by source start; saved recipe edits affect new starts, while existing runs retain their frozen recipe |
| New role binding authorization | Source flow `failureRecovery` / `binding.py` through `service.save_flow` CAS | Live checks of binding identity, expiry and policy fingerprints fence child/replay dispatch; no second registry |
| Legacy opt-in without `bindingId` | Frozen source-run flow / existing start path | Saved-policy edits affect future runs; original run stop cancels existing recovery |
| Issue, budget, dispatch intent, deployment decision | Parent run JSON / service + recovery under the same cross-process run lock | Existing run GET/list, owned runtime scan; no second registry |
| Repair execution | Child run JSON / existing service executor | Parent reads exact child identity and native references |
| Transcript and effective Turn result | Native Session Journal / native Session owner | `native.snapshot`; never copied into a parallel transcript |
| Recovery diagnostics | Bounded runtime-scene events / recovery transitions | Derived evidence only; IDs, status, reason and counts, no prompts |

Contract change is additive v1: optional flow/run fields, typed binding endpoints
and the deployment-confirmation command; there is no data migration or new
production dependency. Deployment and rollout remain operator decisions.
Focused regressions: `tests/test_generic_team_workflows.py`,
`tests/test_generic_workflow_recovery.py`, `tests/test_generic_workflow_binding.py`
and `tests/test_generic_workflow_result_contract.py`, plus
`web/src/api/genericTeamWorkflows.test.ts` for the typed API adapter. The test matrix owns this domain
separately from research workflows. Runtime code requires a Launcher refresh
before formal use; unit/HTTP tests do not claim a live multi-Agent acceptance run.

## Isolated native rehearsal (2026-10-18)

Launcher task instance `43f3e81c` completed source run
`run-359b9fc6d13071c5c3dc23469fcdb4fa66c873ae`: three successful native
Turns reported the same `fixture_missing` business failure; the coordinator
queued director, developer and independent reviewer Sessions, then replayed the
source check. The fourth source attempt completed and recovery became `resolved`.
All execution and review evidence remains in those native Session journals;
the parent run holds their exact Session/Turn references. The fixture was a
temporary marker file, not a production code change or deployment.

The developer's marker write required one exact-call native approval, accepted
by the test operator within the authorized isolated rehearsal. No durable or
Session-wide grant was added. This proves the recovery sequence and original
step acceptance; it does not prove unattended mutation approval, automatic Git
integration or platform-wide failure-source coverage. The earlier denied-write
rehearsal remained blocked after independent review, without false resolution.

## Explicit research-node supervision

An additive `research` step declares `researchSource: {runId, nodeId}`. A source
supervisor flow has exactly this one step, no fields, owner, instruction or
business-result contract. Save it through the existing flow API, bind the four
roles through the existing recovery-binding endpoint, then start it with empty
values and a stable idempotency key. Unbound or legacy opt-in cannot supervise a
research node. The ordinary workflow editor excludes these API-only recipes and
their runs; no source-authoring UI or platform-wide automatic opt-in is added.

The native formal Ledger is the source task authority. A supervisor stores only
derived attempt identities, problem codes and repair state, with no second
transcript or source-task writer. It observes only the exact Team/run/node,
walks the native `retry_of_node_run_id` chain (maximum 120 attempts), and rejects
disconnected or corrupt lineages. Repeated scans do not create attempts or
consume retry budget. Three consecutive distinct attempts with the same known
retryable problem code, or exhaustion of the native retry allowance, queue one
existing director/developer/reviewer repair child. Different problem codes do
not count as the same failure. Unknown problems, human decisions, invalid budget
contracts and unsettled executions are excluded from automatic repair/replay.
The shared research archive switch also blocks repair admission and replay,
including when archive mode is enabled after the native runtime was configured;
success/cancellation observations remain read-only.

Before the repair threshold, the native research scheduler continues owning its
retries. After independent repair verification, safe replay uses the existing
formal `RETRY_NODE` command with a durable attempt-scoped key, exact run-version
CAS, and native readiness/resource-budget checks. The adapter separately checks
the retry-count allowance because the canonical command handler does not enforce
that count. It reads the frozen `input_snapshot_json.budgetPolicy` and the
operator's widening `safety_limits_json` delta; legacy limits are dual-read.
Infrastructure ancestry is uncharged only when the existing taxonomy says so.
Missing limits do not grant capacity. Exhausted allowance waits for an existing
native operator budget decision; recovery never refunds, extends or relabels it.
An explicit retry of the supervisor retries admission after that decision. It
cannot override an `unknown` replay-safety classification.

Replay intent is durable before native submission. An interrupted response
recovers the same native command receipt, including after the source has moved.
The source is checked at repair admission and immediately before each native
repair Turn submission. If the native scheduler advances independently, the
obsolete child is stopped; a successful source node resolves the issue. A repair
verdict or command receipt alone cannot resolve it. Only one live supervisor per
native source is accepted across flows/request keys, and a stopped predecessor's
repair execution must settle before a replacement is admitted. Stopping the
supervisor stops its repair child, while the native research task remains under
its original owner.

These contracts are covered by temporary real Ledger/CommandService tests and
supervisor integration tests. They are local verification, not a deployed
multi-Agent research acceptance run.

## Ordinary Session failure supervision

An additive `Step.kind=session` accepts only a `sessionSource` containing exact
`sessionId`, anchor `turnId` and `agentId`. Like a research source, it must be the
flow's sole step, with no inputs, owner, instruction or result contract override.
It requires the existing explicit four-role recovery binding. Ordinary Sessions
do not acquire supervision automatically. The current source Agent must remain
an active member of the selected Team, and its actual Session owner must match.
Companion bindings remain outside this ordinary-session adapter.

The adapter reads native Journal and state through their existing read paths;
it does not call completion APIs that repair stale sessions or Agent-directory
provisioning APIs. No native admission, worker, journal, persist or projection
code is changed. Only bounded attempt identities, failure codes and recovery
references enter the supervisor; prompts, answer text and raw errors stay in
the native Session. Source artifacts expose empty-content native chat pointers,
and never call the generic dispatch completion adapter. The native Journal reader's lock sidecar remains a lock,
not another transcript or execution authority.

Persisted queued/running/stopping state and existing read-only chat-turn WorkRun
snapshots fence old terminal events even before the local worker flag is set or
when the worker belongs to another process. Observation never reconciles runs.

Task identity follows verified native `branch_rebase` regeneration markers,
including the first-message case where the branch view has no alias. It checks
the real replaced turns, anchor and next native user event. Startup-resume turns
remain part of one business attempt. A normal follow-up, edited prompt, branch
selection, broken lineage or unsettled source cannot be counted as the same
failure. Within one Team, duplicate supervisors from different retry anchors of
the same logical task are rejected. Parsing is bounded to 30,000 events, 120 business attempts and
32 resume children per attempt.

The existing coordinator escalates after three consecutive same-code terminal
failures or the binding's task `maxAttempts` is exhausted, whichever comes first.
Repeated scans do not create attempts. Tool/provider retries within a Turn do
not create business attempts; a model's failure wording is not a failed Turn.
Native budget/context limits, human gates, cancellation and credential/permission
failures remain outside automatic repair. Source movement cancels obsolete repair
dispatch, and saved source-reference changes invalidate the original binding.

Even after a valid repair verdict, this source waits at
`awaiting_replay_decision` with `source_replay_requires_user`. Native regenerate
deduplicates the same request key, but has no expected-Turn/head CAS and reuses
positional API message IDs; automatically calling it could supersede a newer
running Turn. Retry in the original Session, where the existing user action owns
that decision. The supervisor observes the real retry and resolves only after
the same native task completes successfully with actual assistant evidence.
It cannot turn a changed branch's earlier success into recovery.

The typed API preserves `sessionSource`; both native source kinds stay outside
the ordinary workflow editor. Existing generic workflows and research-source
replay keep their prior contracts. Local journal fixtures, disk read-invariance,
coordinator and transport tests cover this adapter; formal runtime rollout still
requires the user's deployment/restart decision.

## Scoped code repair through the existing candidate owner

`POST /teams/{team_id}/workflows/{flow_id}/runs` accepts optional
`localIntegration` with `acknowledge=true`, 1–8 exact `allowedFiles`, matching
`teamId`, and `validForSeconds` of 60–3600. Omission preserves ordinary recovery.
The source needs an existing four-role binding. Configured self-evolution slots
must already match director/observer, developer/executor and reviewer/reviewer.
No roles, tools or permissions are provisioned. Binding readiness alone still
does not authorize local integration.

Only the trusted HTTP control operator can issue this run-scoped delegation;
client operator headers do not grant it. The source Run privately freezes the
grant, with an expiry no later than the recovery binding. Its request scope is
part of the start idempotency fingerprint. Background work derives the same
scope and deadline, without manufacturing an operator context or renewing it.

At the existing failure threshold, the parent persists one deterministic
`codeRepairRunId` and frozen source reference before dispatch. This mode enters
the existing autonomous candidate pipeline instead of also executing the generic
repair recipe. Its director observes/plans, developer edits an isolated candidate,
and independent reviewer verifies the frozen candidate through the existing native
Session receipt and quality gate before the sole Git integration owner merges.
Only bounded native references and problem codes enter the goal; original inputs,
prompts and answers are not copied into another transcript.

Duplicate scans and lost responses reuse the exact WorkRun. A busy candidate
owner waits within the parent repair timeout. Final merge holds flow, parent Run,
then child-grant locks and rechecks the source, binding, policies and deadline.
Stop/revoke/source movement fences new admission. Cancellation preserves actual
integration/cleanup receipts; a stopped snapshot does not prove an executing
developer returned. Source retry and replacement supervision wait for its exact
execution-settled evidence. An authoritative missing child after dispatch has
been blocked is safe; an unreadable/quarantined snapshot remains blocked.

Actual integration moves the parent to `awaiting_deployment`, including when
candidate cleanup is pending. This is a Git fact, not runtime-effect evidence.
Existing user `confirm_deployment` then schedules only the existing reviewer,
whose real effect verdict controls safe replay. Ordinary Session replay still
requires its native user action. Failed/interrupted code execution blocks rather
than starting another potentially overlapping candidate. Persistent multi-round
evolution and a supervision configuration UI remain separate capabilities.
