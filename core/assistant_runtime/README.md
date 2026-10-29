# Launcher assistant runtime

This package adapts the shared native Agent/Session engine for one Launcher
profile. It does not start the Workbench app or own project execution state.
The architectural boundary is [ADR 0012](../../docs/adr/0012-launcher-owns-personal-assistant-runtime.md),
with project transport decided by [ADR 0013](../../docs/adr/0013-launcher-assistant-reuses-native-project-sdk.md).

| Owner | Responsibility |
| --- | --- |
| Electron main | Project registry, own child Job, generation, credential, window and validated IPC |
| `scripts/assistant_host.py` | Fix process role/root before native imports, profile lock, private loopback server |
| `native.py` | Existing Agent/Session provisioning, idempotent submit, native startup recovery and drain |
| `host.py` | Narrow private HTTP transport; no public token, arbitrary Session or generic proxy |
| `actions.py` | Bind the canonical assistant tool to the host's event loop and authorized project IDs |
| `dispatch.py` | Native task associations and bounded receipts; separate native credentials per project |
| `external_management` | Project-bound neutral operator grants, native Agent/Team intents and untrusted API documentation |

## Private protocol 1

Main creates a random `VIBELUTION_ASSISTANT_TOKEN` environment value and a new
`--instance-id`. The child removes the token from its environment before native
workers can start, binds `127.0.0.1:0`, and atomically publishes `ready.json` with
`protocolVersion`, `role`, `instanceId`, `pid`, and `port`. It never writes the
credential into that file. A Windows venv redirector can have a different PID
from its Python child: main validates the generation and authenticated health
inside its own Job, rather than assuming both PIDs must be identical.

Every endpoint requires the bearer value. Browser Origins are rejected. The
renderer receives neither the URL nor the credential. Main accepts a closed
operation union from the exact owned main frame at `/launcher-assistant`.

`--projects-file` contains the complete private snapshot
`{schemaVersion:1,revision,projects:{opaqueRegistrationId:absoluteRoot}}`.
Its version is installed before native startup recovery. Main persists UUID
epochs/tombstones and supplies at most 128 active registrations. A main-only
`PUT /api/assistant/project-registry` updates the same dispatch/management
projection without replacing the Session; the renderer cannot invoke it.
Stale/conflicting snapshots cannot poison a later host generation. Main loads
the persisted registry before creating a host and reconciles only complete,
successful native branch-inventory observations. Registry application is
serialized with host startup/shutdown; its promises require acknowledgement.
The Launcher observation itself does not wait for assistant readiness. Native
inventory failure or malformed rows cannot become an empty permission table.
Actual dynamic lifecycle/Git-freshness acceptance is still pending; an
assistant-only startup validates persisted roots rather than claiming a new
Git inventory scan.

- `GET /health`: protocol and role only.
- `GET /api/assistant`: native assistant identity.
- `GET /api/assistant/session`: its own native Session detail.
- `POST /api/assistant/messages`: `{message, requestId}`; native acceptance and
  journal idempotency, with no new transcript or queue.
- `POST /api/assistant/stop`: `{turnId}`; native expected-turn stop and queue hold.
- `POST /api/assistant/continue`: `{requestId, continuation:{turnId,headId,ledgerSeq,agentId}}`;
  native continuation admission, never an arbitrary message or queued follow-up.
- `GET /api/assistant/events`: existing native SSE, with native Last-Event-ID.
- `GET /api/assistant/config`: existing configuration bootstrap projection.
- `GET /api/assistant/curation` and `POST` `{messageId, action}`: existing native
  curation for the same assistant Session.
- `GET /api/assistant/dispatches`: bounded native task references and receipts.
- `GET /api/assistant/approvals` and `POST /api/assistant/approvals/decision`:
  existing native approvals for this Session; only `accept`/`decline` decisions.
- `POST /api/assistant/shutdown`: main-only graceful owner retirement; it is
  deliberately absent from renderer operations.

The profile OS lock prevents concurrent writers. Main must retain its own
native Job handle with descendant containment and kill-on-close; it must not
register the child in the Workbench process map. Project lifecycle and renderer
close do not stop this owner. Explicit Launcher exit drains native local work,
then reclaims the same Job if the bounded graceful deadline expires.

Project `team_run` uses the same native Team template and generic workflow as
the existing platform adapter. The neutral operator ledger records intent and
ownership, not another execution loop. `team_status` reads the original request;
`status=completed` on the outer management receipt confirms run admission only.
The nested `teamRun.status` reports native progress. Partial materialization
stays unknown; a repeated invocation can continue only a proven complete,
unstarted Team with the identical request and parameters. GET never starts work.

`api_catalog` and `api_describe` require `platform:describe` and the same target
binding/capability. They compile the actual router registry without the web
lifespan or bundled-Agent bootstrap, and reuse the canonical catalog's pure
pagination/schema seams. Registered APIs remain documentation, with only the
explicitly migrated semantic actions advertised as executable. A documentation
entry never enables an unmigrated platform route.
First OpenAPI compilation measured about 7.5 seconds; only this read path has a
20-second budget. Warm catalog/describe use the same cached schema. Real-provider
acceptance requires successful native tool results, not merely a completed
assistant reply.

`session_get` requires the separate `sessions:read` grant and returns only the
native ordinary Session identity, title, owner, pin and status metadata. The
same closed DTO validates the target response and the assistant client. Reads
require the already-open, root-bound directory and canonical registry, Team
roster and Companion bindings without seed, repair, hydration or selection.
Missing authority and hidden/system/Team/Companion/PA classification fail
closed. Titles remain untrusted. This slice does not add transcript access,
transcript writes or permission upgrades for existing grants.

`session_pin` is a separately governed action requiring `sessions:pin` and the
existing native approval gate. It validates the same ordinary visible Session
and delegates only to the canonical pin setter, preserving current selection
and an already-achieved pin timestamp. Existing durable management admission
binds action/request/fingerprint before effects; unknown requests only read back
and never repeat a write. A completed receipt preserves its first confirmation
as historical evidence; `session_get` reports current state after later edits.
Fresh SDK subjects persist the explicit nine-scope request before binding.
Existing states without a scope list keep the legacy eight-scope grant; this
slice does not silently expand permissions or change the subject to gain access.

`session_config_get` uses the same `sessions:read` and ordinary-Session gate,
then reads only that Session's pinned compiled revision through the native
repository. It exposes a closed model identifier, stored context override and
reasoning effort projection with `source=session_agent_config_revision`. It
does not report current Agent configuration, active-Turn settings, provider
defaults or budgets. Missing, damaged or mismatched revisions fail closed;
there is no repair or current-config fallback. Source regression and independent
review are complete. A real-provider source read returned the pinned historical
values while current Agent values differed, with zero target writes. Subsequent
natural-language discovery also reached this read, but its final answer inferred
current equivalence without evidence and its source process did not exit within
the graceful deadline; that complete scenario remains failed. Explicit current
comparison, shutdown diagnosis and rebuilt-package acceptance remain separate.

`session_list` discovers ordinary visible Sessions under the existing
`sessions:read` scope, through a closed SDK query and the opened native directory.
It returns at most six complete identifiers and cleaned title previews; it does
not export messages, previews, debug state or paths. Native runtime-state readers
can decode their stored debug JSON during identity checks, so this is a bounded
output contract, not a claim that those readers never access body-bearing data.
Registry, Team roster and Companion bindings are read without bootstrap or
repair. An established private Session may be excluded without a materialized
runtime; any existing runtime must still pass identity and explicit-field
validation before private filtering. Damaged authority or more than 10,000
candidates fails the whole list. The DAO's preview-search query is always empty;
filtering uses cleaned titles and public IDs. Offset pages observe fresh state
per request and do not promise a snapshot across concurrent changes. Source
validation does not establish new-package real-model acceptance.

`session_config_compare` now returns a closed, read-only comparison of the
Session's stored compiled revision and the owning Agent's current compiled
revision under the same `sessions:read` and visibility gates. The target and SDK
both validate actor binding, revision identities, canonical changed fields and
values. Missing current data never changes historical `session_config_get`.
Neither read projects active-Turn parameters, effective provider defaults or
future submission behavior. A later natural real-provider source turn read the
expected differing revisions without hints or writes and both owned processes
exited naturally. Its core comparison was correct; additional advice in the
answer exceeded that read-only evidence, so the whole answer was not accepted.

Launcher action `index` is now compact navigation with strict query/offset/limit
and at most twelve rows. `describe` owns complete parameters; display-only Schema
titles are omitted at Schema nodes, retaining actual fields named `title` and
all data/constraints. Every current action page and describe fits the native
tool result budget. Source real-provider discovery through query and describe
returned an untruncated historical config result; this does not establish that
arbitrary OpenAPI documentation responses fit the same budget.

`api_catalog` also projects budgeted navigation pages from the unchanged closed
SDK DTO. It keeps complete identity, path, access and capability fields, only
shortens summary text, and returns a complete prefix with the actual row count
and next offset. The model must preserve query/tag when paging and use
`api_describe` for full details. An oversized first entry returns a bounded
error rather than cutting an ID/path. Current production DTO metadata is
bounded by its native generator; arbitrary third-party metadata is not a new
supported source. Actual tool wrapping and the native 4000-character result
budget are covered together. New-package real-provider acceptance is separate.

Launcher `api_describe` exposes a local node view (`viewVersion=1`) over that
same finite SDK response. Its optional `document_pointer`, `offset`, `limit` and
`expected_document_digest` never reach HTTP or the SDK. The default limit is
512; actual pages shrink to the model budget. Complete child pointers retain
schema property names as data, including names that ordinary workflow-result
projection hides. Text passes the existing whole-string cleaning before paging,
and each page applies the same policy again. `textFiltered` reports either
change; offsets/limits consume the cleaned source span so trimmed boundary
whitespace cannot stall continuation. A still-unstable fragment is refused
rather than encoded or silently changed.
`documentDigest` excludes only the top observation timestamp, and
`upstreamTruncated`/`textFiltered` keep both limits visible. A pointer cannot
retrieve schema that the target already omitted. The HTTP/SDK DTO and the
platform assistant's existing documentation action remain unchanged. This is
the first Launcher-only node-view version, before production cutover.

The trusted child directly reuses the closed native project SDK and holds
private per-project capabilities, as the settled transport design in ADR 0013.
Electron supplies the registered-root and permission snapshot; credentials
never enter renderer/model results. There is no generic HTTP capability or
additional forwarding worker. Offline project lifecycle remains pending and
must reuse Electron's native lifecycle engine with a queue and context per
registered project. Stable native command association and recovery are required
before that bridge becomes model-executable. The process-wide default queue or
a Python lifecycle implementation cannot substitute for it. Installing an
independent assistant does not itself start or stop registered projects.

Electron's source-only `projectLifecycleRequests` controller now reserves a
durable request reference before dispatch, then binds it to the actual native
command before intent persistence or execution. The existing queue still owns
join, supersede and close backoff. Joined requests bind to that original command,
not a second executor. Admission failure/cancellation cannot block replacement
work or erase another admitted command's intent; ordinary callers omit the new
optional admission hook and keep their queue behavior.

After recreation, the controller checks current registration and storage-owner
binding and reads only native `results/{commandId}.json`. Missing, partial,
handoff-only, error or timed-out evidence remains unknown and never replays the
operation. `restart_queued` remains queued; it does not prove the project
restarted. Unknown/unregistered projects are refused before allocating request
capacity or reading a reference. The reference store is bounded, has no automatic
garbage collection, and fails closed on corruption, links, ownership changes or
capacity exhaustion. It stores association facts only, not another business
outcome ledger. Files are fsynced before effect admission; Windows Node lacks
directory fsync, so this is not a power-loss durability guarantee.

Electron now constructs the controller at resident-assistant startup, using the
current disk-validated registry and existing deferred target launch settings.
The assistant and ordinary Launcher controls share one canonical native queue
per physical project root. A changed runtime-manager owner is refused rather
than creating a parallel queue. Explicit target environments reach backend,
frontend build, Windows Job, identity, port-owner and retirement helpers without
switching `process.env` or inheriting the assistant's embedded Python.
Graceful shutdown also receives an explicit target token or empty value. Empty
means the existing owner discovers a token only from the identity-verified
loopback target; it cannot fall back to the Launcher's ambient project token.
The target's realtime 409 active-work refusal remains authoritative, without a
process-tree fallback. Global profile/storage roots remain main-owned and
shared across registered projects; this is not per-target operator-profile
switching.

The optional main-control v1 channel reuses the host's private authenticated
connection. Main long-polls short-lived deliveries and settles their public
facts; the broker holds no command executor or durable business state. It bounds
pending deliveries to 32, waits to 20 seconds, and forgets expired deliveries
without replay. Main has four transport workers and an 8 KiB control-response
budget. Host retirement stops deliveries/replies, not admitted native project
commands. A fresh host queries the original main request association.

Only a main-provisioned capability exposes `project_status`, governed
`project_lifecycle` and `project_lifecycle_receipt` through the existing native
action/manage tools. Assistant start, stop and restart dispatch through the
main-owned native lifecycle queue; stop and restart additionally hold the
main-line exclusive fence, so they refuse to run while another lifecycle command
or its settlement evidence is outstanding. Branch instances still return
`prerequisite_required`. Main-project status reports state, not an active-work
count, and cannot prove the project is idle. Branch instances remain owned by
their existing instance supervisor.
There is no force, interrupt, path, URL or generic command parameter.

Earlier temporary verification covered an actual Python HTTP host, Node
main-control modules, native active-work guard and queued-restart settlement,
full host stop/start, and original receipt recovery without another native
execution. The fixture uses
a synthetic native identity and explicit temporary-request authorization; it
is not a real-model or packaged-Electron UI acceptance claim. Real-model joint
acceptance remains incomplete. Platform PA retirement still requires the new
package's functional and data-handoff acceptance.

The renderer refreshes its own display name and character/status preferences
once per authoritative native terminal Turn, including stopped/error and
needs-continue outcomes. It does not treat every idle detail update as another
settings change or add an idle polling loop.
The same terminal boundary invalidates the shared public config query and the
runtime model-config query, so language and model labels can refresh through the
existing lightweight bootstrap. Operator display name and avatar preset now
reuse a bounded, read-only raw configuration snapshot and a closed two-field
`operatorProfile` in status. Existing ConversationView user props consume them
through the same terminal status refresh. Missing/damaged data omits the optional
profile; bio, preferences, file paths, avatar image URLs and credentials never
cross that projection. Current uploaded avatars and background images have a
separate UI-only `operatorAsset` read over the same private IPC. It accepts only
`avatar` or `background`, resolves the current operator selection through the
canonical image owners, and returns bounded PNG/JPEG/WebP data without paths.
The dedicated 16 MiB JSON envelope covers the native 10 MiB wallpaper limit;
ordinary JSON stays at 8 MiB and main control at 8 KiB. Images never enter model
actions or results. A fresh headless Edge page using the actual route/ConversationView and
synthetic private IPC has verified initial display, terminal-driven replacement
without manual refresh, clearing, transparent collapse and narrow-window
geometry. A computed-style and screenshot pixel probe caught and verified the
fix for a root-inherited invalid gradient; the Launcher recipe rebinds the same
canonical formula locally, keeping its 18/44/60 readability values. These page
checks do not establish packaged-Electron or real-provider acceptance.

Acceptance harnesses must preserve the authorized operator `runtime.profile`
and canonical credential references. `safe_local` deliberately redirects remote
routes to local inference; replacing a remote test profile with it does not
prove the remote provider failed. Private-environment sanitation may remove
inherited project roots, but must retain exactly the authorized provider's
credential variable. Preflight compares the effective native route and actual
child credential availability before any model submission. Target source config
is an independent immutable snapshot; Launcher settings may change only its
own private copy. No real operator profile is copied into model context.

## Recovery and authority

Model-facing dispatch resolves task text from the current admitted operator
message in the fixed native Journal. `task` must be an exact source substring;
`task_source: {start_after, end_before}` selects a span with unique short
anchors. Root, actor, Session and Turn come from the trusted native context,
never model parameters. Non-operator or settled admission and ambiguous spans
are refused before a reference or SDK effect is created. Only native IDs,
offsets and hashes are added as `sourceRef` to the existing association, so a
retry after restart can verify and reuse the original text without copying a
second transcript. Damaged references do not prevent querying an existing
native task. Unknown legacy requests lacking source proof cannot be recreated.
Source admission uses a nonblocking lock and Journal I/O runs off the host
event loop; it cannot wait behind shutdown while shutdown drains that worker.

`requestId` and `dispatch_id` are stable across unknown responses. A known native
task is queried, never recreated. The managed gateway retains native hidden
Sessions, per-task capabilities, approval revisions and finite leases. Each
operation reconstructs the existing client to revalidate backend identity after
restart. UI closure does not call the MCP client's cancelling lifecycle.

Only native status is reported; `completionEvidence.businessAcceptance` is not
inferred from `ready`, `idle`, `stopped`, or a gateway `succeeded` projection.
An offline host cannot guarantee work survives beyond its native lease.

## Verification boundary

`tests/test_assistant_runtime_{native,host,actions,dispatch}.py` cover storage
identity, crash recovery, transport auth and task associations. Frontend uses
the existing `ConversationView` with an injected data source and separate cache
keys. A sealed CPython payload has also completed real-provider settings,
dispatch and host-restart receipt acceptance without a project PA; its files
remained unchanged. A managed Windows Electron package has separately completed
real-provider dialogue, native-frame IPC, Live2D appearance, full exit/restart,
identity/preferences/history restoration and graceful Job retirement without a
project. Source-host real-provider acceptance also covers four-role Team run,
assistant restart and original run/status recovery, plus Stop/Continue with
idempotent continuation and stale-snapshot rejection. These are separate
evidence slices; they do not establish the latest full packaged project/Team
lifecycle, complete capability/data migration or platform retirement.

The package builder copies validated distribution RECORD files and static
source resources; no development venv or test dependencies are included. Main
resolves the fixed payload using pinned provenance, hashes its tree in a
Worker, and starts Python with isolated search paths. Tokenizer/Hugging Face
caches belong to the native profile. Global model/Provider deletion and
disabling remain unavailable until a complete cross-project reference guard
and its write coordination boundary are implemented.

The current collapsed-window frontend has also passed real-provider acceptance
in the managed Electron package: name, Live2D character and hidden status apply
after the native terminal Turn without refresh/re-expansion. The same package
preserved literal delegated text and recovered the original successful native
task after a full owned-app restart; target Journal completion and PA count zero
were independently checked. This does not establish the public Launcher entry,
complete legacy data handoff or platform retirement.

`scripts/assistant_migration_inventory.py --project <source>` resolves existing
active storage without bootstrap and fingerprints only declared current PA
identity scopes. It emits no source bodies and has bounded file/registry reads,
link/type/conflict rejection and concurrent-change detection. Its output always
remains `stage=inventory`, `sourceQuiesced=false`, `readyForCutover=false`;
historical Session discovery, native ownership/watermarks, in-flight dispatches,
recovery grants and history import are still pending. It never copies, pauses,
repairs or retires the source.

Fresh native profiles also reuse the existing personal affairs, private memory
append/supersede, private formal-KB search and context compression descriptors.
Their Agent/Session identity remains native; no second ledger or tool executor
is introduced. The affairs singleton binds to the fixed Launcher root only in
that process role. Existing profiles, including empty/custom tool policies,
remain unchanged. Native/ordinary regression covers all six affairs operations,
memory succession and restart persistence in both developer modes. Real
DeepSeek source-host acceptance additionally created one affair and preference,
restarted, completed that original affair and superseded the original episode
without duplicate records. Compression and empty-KB search have contract tests,
not a new real-model execution claim. The current managed Electron package has
since passed the combined real-provider scenario below; the legacy user's data
has not been migrated.

On 2026-10-25, the managed package completed five unique UI requests in an
isolated environment: collapsed-window preference changes applied automatically,
an original literal task recovered as the same successful native task after a
full owned-app restart, the original affair completed and its original memory
episode gained a successor, and one target avatar update used the first different
native candidate and was read back. All processes exited normally, the target
had no PA, and formal configuration hashes and timestamps were unchanged. The
receipt is `e7-788vzjef/joint-acceptance-receipt.json`. An earlier E6 run's formal
configuration hash changed during the run; its record remains failed and its
writer remains unattributed. That observation was narrowed read-only to a main
instance window-size settings write and was not rolled back or silently waived.

The new public native `--assistant` source branch precedes project parsing and
admits only a fixed KnownFolder managed package. A separate pure publisher reuses
the existing build/seal and atomic-file owners to copy and verify immutable
versions before atomically selecting one. The explicit Windows installer calls
that producer and publisher; the ordinary project entry keeps its semantics.
Native admission holds verified files and directory identities through process
creation. Hashes establish integrity, not publisher signatures or protection
against a same-user writer after handoff. These changes are being verified in
Temp; there has been no formal installation, complete API/data handoff or
platform PA retirement.

## Native appearance control

Main may explicitly negotiate `appearanceControlVersion:1` alongside the unchanged
private protocol and project-control capability. Without that provisioned flag,
old hosts do not advertise the three new main actions. Theme get/set and governed
`operator_image_upload` use the existing broker/pump and fixed private IPC; they
have no project SDK proxy, arbitrary command, URL or model-supplied source path.

`launcher_theme_get` / `launcher_theme_set` project only delivery, operation and
optional light/dark into the exact owned assistant frame. The renderer uses the
existing `vibelution.workbench.theme` writer, verifies persistence and document
application, and replies through a closed authenticated-frame ACK. LauncherShell
and the assistant subscribe to the existing same-origin theme events. Project
HTTP origins retain their independent preference. Four pending requests, a
three-second reply deadline and bounded recent tombstones prevent unbounded
resident state; no second theme setting or idle poll is added.

`operator_image_options` / `operator_image_select` read bounded logical resource
names and apply an existing image (or clear it) through the canonical operator
config transaction. Uploaded avatars retain `workspace/user_avatars/...` logical
paths even though their physical operator folder is `avatars/`. Navigation reads
at most 1000 candidates and only small headers; a chosen resource is fully
revalidated before and after application. Legacy `settings_update` permissions
are not expanded by the dedicated image helper.

For upload, a governed tool opens the owned native single-file chooser. Main
reads only that operator-selected regular file, with 5/10 MiB limits and file/
ancestor identity checks, and sends bytes to a fixed private host operation.
The model sees no local source path, base64 or credential. The optional private
POST requires a still-live, claimed, kind-matching delivery and admits it once;
an old generation, expired or replayed chooser cannot enter the writer. A native
stop cancels that Turn's unadmitted chooser; already admitted transactions drain
through their existing owner. Selection has a 120-second budget, project calls
keep their original budget, and no layer automatically repeats an import.

The canonical avatar/background stores remain the only resource writers and
now exclusively create their random names, refusing collision or hardlink
overwrite. The Launcher import adapter reuses Windows verified directory leases
through image storage, config transaction and readback. Its explicit directory
write mode permits child replacement while denying ancestor/root rename;
default source-reader sharing remains unchanged. This is a namespace pinning
boundary, not a sandbox against every action by another same-user writer.
Canonical stores retain random naming, so a repeated intentional import can
create another resource; an image already stored survives config conflicts.

Temp joint verification exercises an actual Python private host, main control
and canonical image/config services, plus host restart and original selected
resource reads, with a synthetic native identity and chooser/renderer seams.
A fresh headless source page separately verifies dark/light persistence,
reload, same-origin event synchronization and image replacement/clearing using
synthetic private IPC. Neither proof is a packaged GUI/real-model acceptance or
a human-interacted native chooser test. DeepSeek remains on hold until explicit
funding confirmation, and platform PA retirement remains gated by complete
function/data acceptance.

## Governed Agent archive

`agent_archive` reuses the native management approval and a separate
`agents:archive` grant. Strict `expected_config_revision` is checked within the
existing Agent archive transaction; the adapter delegates the actual archive
and associated Session sealing to the canonical lifecycle owner. Protected,
private, damaged or busy objects are refused before mutation. Existing durable
intent and receipt owners handle unknown results by readback only; no archive
replay, purge, reset, restore or force is exposed. A completed receipt freezes
the first verified archived observation.

Fresh SDK subjects explicitly request fourteen scopes, including the separate
`legacy:receipts:read` scope. Persisted eight-, nine-, ten- and thirteen-scope
subjects retain those exact grants, and historical grants without
a scope list retain their original eight. No automatic upgrade or subject
rotation is performed.
Temp native-Agent/Session lifecycle and SDK/receipt regressions have passed;
this does not establish real-model or formal-project acceptance. The effective
parameter API now uses the existing-only snapshot path described below.

Archive admission and uncertain-result readback explicitly avoid the repairing
Agent projection. Their dedicated adapter reuses an existing-only config and
sandbox authority resolver, reads bounded strict raw registry/roster snapshots,
and gives the existing Companion store the same non-initializing resolver.
Missing authority is refused without seed/copy/repair. Receipt avatars describe
persisted selections, without hydrating a current UI/default logo. Regression
sentinels prohibit the old getter, save/repair and sandbox initialization, and
verify unchanged registry bytes through stale rejection and restarted readback.

## Directory and effective parameter queries

The native project SDK remains the project transport, as settled in ADR 0013.
The model receives closed actions, rather than arbitrary HTTP or file access.
The management prefix is `/api/v1/launcher-assistant-management`:

| Model action | GET suffix | Required grants | Result boundary |
| --- | --- | --- | --- |
| `task_list` | `/active-tasks` | `tasks:read` | Bounded native active-index entries; index completeness is unknown |
| `source_read` / `source_search` | `/source/read`, `/source/search` | `source:read` | Bounded checkout source text; search is partial and content remains untrusted |
| `team_list` / `team_get` | `/directory/teams[/{team_id}]` | `teams:directory:read` | Ordinary Team summaries and bounded member pages |
| `room_list` / `room_get` | `/directory/rooms[/{room_id}]` | `rooms:read` | Ordinary room metadata, without message projection |
| `session_parameters_get` | `/sessions/{session_id}/parameters` | `sessions:read` and `sessions:parameters:read` | Current effective Agent defaults for future Turns |
| `authorization_status` | `/authorization` | Original subject credentials and operator control | Exact current grants and revision; no automatic local grant update |

The target's active-task index can omit live tasks after index damage. Its
`total` therefore counts indexed entries only; an empty page does not prove the
project is idle. The response reports this coverage explicitly. The new
`tasks:read` grant is added only through the existing explicit authorization
upgrade; neither existing subjects nor newly bound subjects receive it silently.
Older target versions may not support this scope or endpoint.
If a target is rolled back after the grant was upgraded, the old target may
reject the saved scope set; preserve the original subject and report the
connection failure rather than silently discarding grants or creating another.

Source access also requires an explicit grant upgrade. It accepts only relative
paths in the target checkout's allowed source directories and refuses links,
configuration formats and common sensitive filenames. Search scans a bounded
window of each candidate and exposes a continuation cursor; an empty page does
not prove a match is absent. Redaction covers common patterns but cannot detect
all secrets in source text.

Directory pages contain at most six items, stable IDs and explicit offsets;
`archived=true` includes archived items. Private/system sources are filtered
only after classification is validated. Missing, corrupt or ambiguous sources
are refused. Rooms use their canonical formal-workspace owner even in developer
mode. Their co-located JSON is decoded, but rounds/messages are neither searched
nor projected, exported or hydrated. Returned names and descriptions remain
untrusted content.

Effective parameters reuse the saved candidate, already-loaded operator config,
frozen existing model catalog and native reasoning/context/budget resolvers.
The GET pins Agent, roster, Companion binding, workspace routing and the actual
native store revision throughout validation. It never seeds a catalog, repairs
an Agent or substitutes metadata when native resolution fails. The result does
not describe an active Turn or a historical compiled configuration. Ordinary
Session admission, Journal, worker, persistence and SSE remain unchanged.

## Unavailable projects during independent startup

Electron retains the complete persisted schema-1 project snapshot and its
revision when a registered directory is missing or physically rebound. Only
that reconciliation condition may start the native host with
`--projects-suspended`; corrupt or externally changed registries still fail.
Local chat remains available, while project SDK and management admissions are
blocked before intent creation and again after waiting for a project lock.
Previously admitted calls may settle under the existing binding/revocation
checks. Historical dispatch references remain readable without replay.

Main can close the same gate through the private authenticated
`POST /api/assistant/project-registry/suspend` with the closed body `{}`. Its
closed acknowledgement is `{schemaVersion:1, revision, projectsSuspended:true}`.
An unknown acknowledgement retires the owned host. Only a complete validated
snapshot PUT can reopen project admission; no subset, revision rewrite, path
discovery, authorization upgrade or historical-data migration is implied.

The assistant header and tray expose a human-only `openLauncher` window action.
It accepts no project path from the renderer or model, focuses the connected
Launcher, or asks the human to choose an existing project through the native
directory picker. It reuses the existing main-owned control plane and does not
send a model message or start a project runtime by itself.
Management-only attachment skips startup reaping, expired-instance retirement,
old tray restart restoration and automatic shell replacement. Its normal
deferred-restart owner only admits requests created after this attachment;
opening the window does not rewrite or fulfil earlier requests. Ordinary
project/lifecycle startup retains its existing recovery behavior. Once a fresh
explicit lifecycle request executes, its normal supersession of older requests
still applies.

## Explicit upgrade of existing authorization

`authorization_upgrade` is a governed management action. An approved request
must provide the exact sorted `expected_scopes` and disjoint sorted `add_scopes`.
Its existing POST action endpoint requires both operator control and the original
subject capability. It preserves the subject/client/capability, opaque task
associations and existing grants; new read grants do not imply archive or pin.
The protocol remains version 1 with additive endpoints and a new closed action.
Existing actions retain their authentication and response contracts.

The existing Store owns intent and receipt persistence. A subject mutation adds
an immutable proof and increments its grant revision atomically. After lost ACK
or SDK restart, `management_receipt` reads the original request; it never reruns
the grant mutation. A missing proof stays unknown. Historical receipts preserve
their original scope union even after later upgrades. The SDK updates only its
saved scope list after a completed receipt and current-subject verification.
Transport, stored-grant, restart, competing-process and native model-output
budget tests run in isolated environments; real DeepSeek/package acceptance
for these new actions is still pending funding confirmation.

Source inventory also fingerprints the selected old PA's own dispatch events
and default private knowledge namespace without exporting their contents.
That initial inventory alone does not discover target-side dispatches, all
historical Sessions, custom paths or queue ownership. The explicit adapters
below handle retained history, approved paths and observation. Old message IDs are not new native
task capabilities. No old queue, Turn or transcript is copied into the running
Launcher profile; `readyForCutover` remains false until handoff is verified.

The optional `--handoff-preview <explicit-old-pa-agent-id>` emits a separate
schema-1 `handoff_preview`. It uses the inventory's declared PA identity and
registry hash, then reads existing default inbox JSONL for registry targets
(including archived Agents) and that PA's receipts. Custom workspace routes,
missing/corrupt/ambiguous/changed sources and limits produce explicit issues
and `previewComplete=false`. JSONL limits are 256 files, 8 MiB per file,
64 MiB total, 10,000 rows total and 256 KiB per line; stable verification
rereads at most that byte count. The registry has its own 16 MiB limit;
identity adjudication shares the inventory's pure rule without running a
second inventory or reading other source trees.
Reports include identities, delivery/task statuses, evidence counts and source
hashes, without prose, evidence strings or custom metadata. Only an explicit
reply ID with both Agent and Session bindings can supply task evidence;
consumption alone never proves completion. Follow-ups are counted separately.
Canonical top-level Session bindings are adapted only when metadata has no
conflicting binding. Human/system messages with empty source Agent/Session
remain unrelated inbox rows; their IDs still participate in ambiguity checks.
Every row must belong to its declared target inbox. Missing dispatch Session
evidence stays unresolved without substituting a current direct Session.
Legacy IDs remain `legacyMessageId`; `nativeTaskId=null` and
`nativeCorrelation=unresolved` never assert a native task association.
Late receipts are observed by rerunning the preview. This read does not start,
replay, copy, enqueue, repair, pause or retire anything. A complete scan still
has `sourceQuiesced=false` and `readyForCutover=false`.

## Retained history and approved custom sources

`scripts/assistant_migration_inventory.py` keeps its default inventory and
`--handoff-preview` read-only behavior. Explicit `--history-preview <PA>` scans
all retained, provably owned Sessions, including archived and hidden children.
The canonical SQLite root overrides stale legacy JSON. Reads use a temporary
SQLite copy with the native APSW runtime; nonempty WAL/journals, active Turns,
unknown ownership, corrupt sources or limits refuse complete import. Deleted
Session tombstones are respected; purged history is not reconstructed.

`--history-import <PA> --target-profile <absolute-profile> --migration-id <id>`
publishes an immutable archive below `history_archive/migrations`. Original
Journal bytes, event/message/tool IDs, assets, hashes and source scope remain
separate from the new active native Session. Native parsers and projectors are
reused; model `history_list` / `history_read` paginate bounded, untrusted,
read-only projections. New archives become visible only after the final source
and authority checks; the direct offline importer can revalidate an interrupted,
unconfirmed import. Its caller is trusted to supply any required source
authorization; the importer does not acquire that authorization itself. The
online owner's reservation still forbids retrying its ID. Existing v1 archives
remain visible, but have no record proving their final checks
completed. These checks do not freeze the source or establish full handoff.
Existing projection whitespace normalization still
applies; original archive bytes remain exact. No imported Turn is continued,
enqueued or replayed and no ordinary Session core is modified.

`--source-paths <PA>` inspects raw workspace/memory-policy declarations without
getters that initialize, normalize or repair state. External locations are not
read before an exact source/category/root grant. `--path-grants <file>` accepts:

```json
{"schemaVersion":1,"sourceScope":{"projectId":"p","instanceId":"i","agentId":"pa"},"grants":[{"category":"memory","root":"C:/explicit/existing/root","revision":1}]}
```

`--source-import <PA> --target-profile <absolute-profile> --migration-id <id>`
copies approved memory, private knowledge, personal-affairs and asset data to
`history_sources/migrations`. This command preserves sources only. Generic plugins, inbox/outbox
and runnable queues are never activated or copied as execution state. Missing,
unapproved and conflicting paths remain explicit; partial preservation does
not become `sourceComplete=true`.

`--source-config <existing-config>` selects the source's existing formal or
developer-sandbox route without creating a sandbox or initializing config.
Without this option ordinary inventory/import uses the explicit project's
active formal storage route. Config, pointer and physical source identities
are rechecked before publication. Imports reject aliases, links, physical
source/target overlap, extra target files, hash conflicts and changed sources;
stable migration IDs are idempotent. Publication rechecks the final archive
before reporting success. No source is deleted or frozen.

Offline personal-data adapters can import selected episodic memory and personal
affairs into the target assistant's existing native ledgers, preserving source
IDs and lifecycle states. They require a verified source registry and physical
route, an explicit source snapshot and exclusive target host ownership. The
native owner does not recover or admit Session turns during migration. An
unconfirmed shutdown keeps the target locked; a failed directory close cannot
be retried safely in the same process. Metadata-only receipts preserve stable
migration identity and do not overwrite later edits on retry. The source is
not frozen, separate ledger writes can yield a partial result, and reminders
do not yet have a proven single owner. These adapters are not a cutover.

The operator entry `--activate-personal <PA> --source-config <existing-source-config>
--target-profile <existing-profile> --target-config <existing-config-inside-profile>
--migration-id <stable-id>` uses a separate native-role child and the same source
path grants as source import. The child has a private environment and refuses
Python network operations and writes outside the selected target. This is not
an OS sandbox. Check the structured `status`, not only the exit code: `partial`
or `outcomeUnknown` requires reconciliation using the same migration ID and
must not trigger automatic replay. `--activate-knowledge` uses the same explicit
source/target arguments and isolated native owner, but snapshots the source's
canonical knowledge registry and owner references as additional authority.
It does not infer an authorization from a file hash. A KB import may have
partially written before an error; the caller must retain the migration ID and
reconcile an unknown outcome without automatically starting another import.

The separate private-knowledge adapter reuses native private KB ingestion for
provable direct reviews and a bounded, single-source, same-owner reviewed
revision chain without expiry. It activates only the current valid version and
retains the original review and revision evidence in the source archive.
Unsupported chains and future expiry are refused; withdrawn or expired items
are not made active. It requires independently verified canonical source and
owner records. Native ingestion is not atomic, so an uncertain result is retained as
unknown rather than repeated. A trusted caller must supply the source authority;
the model cannot invoke these operator adapters. In developer mode the native
central-promotion policy rejects private KB activation before creating a
migration directory or knowledge base. That policy is not bypassed by this
adapter; the existing knowledge and its archive remain in the source. A
prototype sandbox restore was not accepted because the existing Windows
directory pin does not prevent concurrent insertion of unapproved children.

`--recovery-inventory <PA>` only inspects old workflow recovery bindings and
temporary-grant evidence. Old bindings remain in their source; subsequent
controls and approvals need fresh native authorization. Unresolved paths,
legacy relationships or missing evidence cannot establish quiescence or make
`readyForCutover` true. No old queue, grant or execution lease is transferred.

The internal reminder preview compares the authorized source affairs snapshot
with the target's native affairs ledger and reports missing/conflicting items
and the number due. It neither sends a reminder nor transfers execution: the
legacy Workbench remains the notification owner. A source quiescence fence and
the legacy delivery watermark still have to be established before any reminder
cutover can be declared.

For a Launcher assistant profile with no affairs migration records, the native
host and Electron main can send reminders for that profile's own due affairs.
The private bearer-authenticated endpoints are `POST /api/assistant/reminders/next`
(reserve and return one event), `POST /api/assistant/reminders/submitted` (record
the native submission), `POST /api/assistant/reminders/fallback` (record a
queued fallback after a submitted system notification later fails), and
`POST /api/assistant/reminders/opened` (record a real notification click). The
reservation token stays in Electron main. An existing
`affairs_migrations` directory blocks this sender for the whole profile; it does
not establish legacy takeover. A failed or uncertain attempt is not replayed;
it can therefore remain undelivered. Daily ledgers retain receipts and fail
closed at their capacity; automatic retention cleanup is not implemented.
If the system notification fails, Electron queues one reminder dialog at a
time. A late failure after a submitted system notification changes that receipt
to the queued fallback; submission alone does not prove the dialog was seen.
Either dialog choice records an interaction. During the same UTC day, an
unanswered fallback for a still due item is recovered on restart without
sending another system notification. On a later UTC day, an open overdue item
is treated as a new daily reminder. Shutdown waits at most two seconds for an
unanswered dialog.

`reminder_receipts.ReminderReceiptStore` uses pinned Windows handles and SQLite transactions to
reserve a stable event ID before a single submission. A prior pending or
submitted attempt is not replayed; submission is not proof of viewing. A
recovered native click requires the original token and the already committed
channel. Older Workbench executors do not consult this store, so it cannot
establish single ownership or enable legacy cutover.
Its v2 ledger can permanently close admission for cooperating senders and
retain in-flight reservations after a crash. A drained v2 ledger proves only
those registered senders have drained; it does not fence older binaries. The
store deliberately rejects v1 ledgers instead of upgrading them implicitly.

The resident Launcher assistant cannot use the offline operator entry while it
owns the profile lock. Its normal shutdown requests cancellation of the current
turn, and a status snapshot is not an idle barrier: native queue drain, timers,
workers and projection may still run. Do not stop a live host for migration or
pretend its lock is an offline lease. An eventual online owner must bind the
main-owned project registration and source/target authority to the actual host
generation, keep a separate lifecycle drain reference, and use short native
ledger transactions without holding the assistant command lock across source
scans or knowledge review. It must preserve user edits and receipt recovery,
and must not allow the model to supply filesystem paths or grant itself access.

`online_history.OnlineHistoryOwner` is an unwired coordinator for a future
trusted owner: it accepts only opaque registrations and separately supplied
canonical source identity, and requires generation and source-authority guards
across writes and publication. Its tests use simulated guards; no main-owned
production authority currently supplies them. In particular, existing file
pins do not prevent a different source writer creating a tombstone or asset in
an observed directory. A source change can therefore be detected after an
offline archive becomes visible; until a real source freeze or consistent
snapshot is proven, this is not evidence of a complete or safe cutover.

## Observation of in-flight legacy dispatches

[ADR 0015](../../docs/adr/0015-legacy-dispatch-handoff-is-observation-only.md)
records the user-approved boundary: the original project Session/Turn keeps
execution. Launcher receives receipt observation only. Cancel, continue and
approval operations require fresh native authorization; old temporary grants,
pending approvals, leases and worker ownership are not transferred.

The native SDK adds operator-only `POST /legacy-observers` and closed
`GET /legacy-observers`, `GET /legacy-observers/{observer_id}/receipts` under
the management prefix. Creation requires source Agent, exact sorted message
whitelist, registry hash, expected physical source authority and stable request
ID, plus the original subject/capability/control token and explicit
`legacy:receipts:read`. Formal/sandbox copies with identical IDs cannot satisfy
the wrong source authority. Model actions expose only `legacy_observers` and
`legacy_receipts`; they cannot create grants or supply paths/capabilities.

Offline operator entry is `--observe-handoff <PA> --source-config <config>
--target-profile <profile> --registered-project-id <opaque-registration-id>
--request-id <stable-id> --message-id <old-message-id>` (repeat message-id).
Stop the target host first: this entry reuses its native profile owner lock and
SDK credential store; a resident owner returns `TARGET_PROFILE_BUSY`. It never
upgrades an existing subject automatically. An old subject must first use the
governed `authorization_upgrade` action for the separate read scope.

The existing target Store persists intent and private source proofs; it does
not schedule work. Restart/lost ACK reads the same proof, or retains unknown
when no proof survived. Late receipts are read from the original inbox without
marking them consumed. Business-task completion stays distinct from Turn/run
completion. `nativeTaskId` remains null for A2A dispatches; a native run is
reported only when an actual matching runtime snapshot proves it. Missing
unrelated canonical inboxes have typed negative proofs, never a fabricated
complete empty ledger. Selected PA/target inbox absence and custom unapproved
sources still refuse observation.

Temporary native-process restart, HTTP/SDK receipt and revocation regressions
provide local acceptance. Real DeepSeek and fresh packaged acceptance remain
separate gates; `sourceQuiesced=false` and `readyForCutover=false` remain
mandatory. The old platform assistant and its receipt address stay available
until functional/data handoff and real-model acceptance permit retirement.
