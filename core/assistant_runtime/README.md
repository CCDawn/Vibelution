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
action/manage tools. Writes retain native approval and active-work protection;
there is no force, interrupt, path, URL or generic command parameter. Currently
only registrations whose root is their integration root use this main-line
engine; branch instances return `prerequisite_required` before reserving a
request. Their existing instance supervisor remains the lifecycle owner.

Temp verification covers an actual Python HTTP host, Node main-control modules,
native active-work guard and queued-restart settlement, full host stop/start,
and original receipt recovery without another native execution. The fixture
uses a synthetic native identity and explicit temporary-request authorization;
it is not a real-model or packaged-Electron UI acceptance claim. DeepSeek remains
paused until funding confirmation. Platform PA retirement still requires the
new package's functional and data-handoff acceptance.

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

Fresh SDK subjects explicitly request ten scopes. Persisted nine-scope subjects
retain those exact grants, and historical grants without a scope list retain
their original eight. No automatic upgrade or subject rotation is performed.
Temp native-Agent/Session lifecycle and SDK/receipt regressions have passed;
this does not establish real-model or formal-project acceptance. The remaining
effective-parameter API needs a side-effect-free configuration/catalog owner
before it can replace the legacy ensure/repair getter faithfully.

Archive admission and uncertain-result readback explicitly avoid the repairing
Agent projection. Their dedicated adapter reuses an existing-only config and
sandbox authority resolver, reads bounded strict raw registry/roster snapshots,
and gives the existing Companion store the same non-initializing resolver.
Missing authority is refused without seed/copy/repair. Receipt avatars describe
persisted selections, without hydrating a current UI/default logo. Regression
sentinels prohibit the old getter, save/repair and sandbox initialization, and
verify unchanged registry bytes through stale rejection and restarted readback.
