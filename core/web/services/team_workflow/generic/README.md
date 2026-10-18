# User-defined team workflows

The service is the sole flow/run state owner. The existing Team namespace supplies formal/developer storage roots; atomic JSON snapshots and cross-process locks enforce revisions. User definitions and each run's frozen copy are distinct. New HTTP endpoints are additive version-one contracts and do not modify retained research routes or require a question ID.

- `models.py`: bounded public contracts, unique field/step IDs and input validation.
- `store.py`: Team authority, validated path components, atomic writes and CAS locks.
- `service.py`: explicit run commands, sequential transitions, frozen inputs and durable dispatch receipts. An assigned output executes its configured Agent; an unassigned output delivers prior results.
- `native.py`: existing Agent-scoped hidden workspace Sessions, stable create/submission identity, canonical completion and verified restart-resume chains. Stop targets the effective Turn. Only references and lifecycle records are stored; Session remains transcript authority.
- `runtime.py`: one owned reconciliation worker. Reads do not dispatch. Startup waits for native Session recovery; delayed callbacks are fenced by the lifespan stop flag under the admission lock. Shutdown closes this producer before native Session workers.

Retry may create a new attempt only after canonical evidence permits it. Unknown Session identity or active-state uncertainty fails visibly and prevents duplicate execution or false stop success. Flow/run lists remain readable while execution is warming; artifact projection waits for the owner. Membership and Agent availability are checked again before dispatch. No raw model invocation or changes to ordinary Session core are introduced.

Tests use temporary Team storage and a substituted native port. Those tests prove orchestration and adapters, not real model output quality or a live application's restart acceptance.

## Opt-in failure recovery

`Flow.failureRecovery` optionally binds a saved `repairFlowId`, `directorAgentId`,
`reviewerAgentId`, `replaySafety` (`unknown` by default), `maxAttempts` (1–3,
default 3), `maxRepairAttempts` (1–3, default 2), and
`repairTimeoutSeconds` (60–86400, default 1800). Existing flows retain their
manual failure/retry behavior. This is the first source adapter for platform
recovery: ordinary Sessions, research Ledger tasks and other evolution runs do
not automatically acquire this policy.

The repair flow must have only one text/paragraph input, `incident`. Its first
executable step belongs to the director; its final step belongs to an independent
reviewer who does not implement or diagnose the candidate. At least one developer
step with a third Agent identity must sit between them. Human approval steps are
not allowed inside the automatic repair child; deployment approval is owned by
the source run. It cannot recursively opt into recovery. Source start
validates live Team membership and freezes this definition. Dispatch and replay
recheck membership. No tool grant, workspace scope, deployment permission, or
candidate integration permission is added by configuring a role.

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
| Definition and opt-in | Team flow JSON / `service.save_flow` | Frozen by source start; later edits affect new runs |
| Issue, budget, dispatch intent, deployment decision | Parent run JSON / service + recovery under the same cross-process run lock | Existing run GET/list, owned runtime scan; no second registry |
| Repair execution | Child run JSON / existing service executor | Parent reads exact child identity and native references |
| Transcript and effective Turn result | Native Session Journal / native Session owner | `native.snapshot`; never copied into a parallel transcript |
| Recovery diagnostics | Bounded runtime-scene events / recovery transitions | Derived evidence only; IDs, status, reason and counts, no prompts |

Contract change is additive v1: optional flow/run fields and a new command action;
there is no data migration or new production dependency. Disabling the policy on
a saved definition affects new runs; use the existing original run `stop` command
to revoke an in-flight recovery. Deployment and rollout remain operator decisions.
Focused regressions: `tests/test_generic_team_workflows.py` and
`tests/test_generic_workflow_recovery.py`. The test matrix owns this domain
separately from research workflows. Runtime code requires a Launcher refresh
before formal use; unit/HTTP tests do not claim a live multi-Agent acceptance run.
