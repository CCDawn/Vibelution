# ADR 0013 · Launcher Assistant Reuses The Native Project SDK

## Status

Accepted (2026-10-25), following the user's explicit selection of the native SDK
option. Refines project business-API transport in
[ADR 0012](0012-launcher-owns-personal-assistant-runtime.md) and replaces the
all-project-message forwarding requirement in the
[migration plan](../plans/2026-10-23-launcher-personal-assistant-migration.md),
§3.2, §5.1 and §6.2. [ADR 0009](0009-launcher-control-plane-lives-in-electron-main.md)
still owns all project lifecycle writes in Electron main.

## Context

The Launcher-owned Python host already reuses the native Agent, Session,
Journal, provider and tool engines. Its closed project SDK also reuses native
gateway authorization, stable request keys, finite leases and task receipts.
Temporary real-provider acceptance has exercised project task dispatch and
receipt recovery after a full owned Launcher/host restart without a target
project PA. This proves that path; it does not prove complete migration or
production cutover.

The original plan required Electron to forward every project business request
and retain all project credentials. Completing that variant would add another
RPC and error mapping layer around the same SDK, with duplicate timeout,
streaming and recovery responsibilities. The user chose to retain direct native
SDK calls in the supervised trusted host to reduce duplicated development and
maintenance. Neither variant gives credentials to the model or renderer.

## Decision

1. Electron main owns the registered project roots and registration epochs,
   permission snapshot, assistant generation, child Job and desktop windows.
   Only main can update the host's project-registry snapshot. Model parameters
   contain opaque registered project references and business arguments, never
   URLs, filesystem roots, authorization subjects or credentials.
2. The trusted native assistant host calls the existing closed project SDK
   directly for migrated business APIs. Its private per-project capability files
   remain in its own protected profile. They never enter renderer state, model
   tool results, CLI arguments, URLs, receipts or diagnostics. No second SDK
   worker, generic HTTP proxy or second conversation engine is introduced.
3. The target gateway remains the final authorization and execution authority:
   native actor binding, granted scopes, object visibility, capability revision,
   finite lease, expected revision/turn and action-specific preconditions must
   still pass. A registration snapshot or model-visible API description grants
   no additional access. Unmigrated APIs remain unavailable for execution.
4. The existing request association stores only stable request IDs, source
   references and bounded native receipts. Unknown outcomes are reconciled by
   their original IDs. Neither main nor the host becomes a second project task
   scheduler, Journal, transcript or source of successful completion.
5. Project start/stop/restart, native command queues, supervisor state and
   process recovery remain in Electron main. A separate closed lifecycle bridge
   may reuse the native engine with a context and queue per registered project.
   It must establish stable native command association and recovery before
   becoming model-executable. The SDK must not start Python project lifecycles,
   mutate `instances.json` or bypass the active-work guard.
6. Connection identity, revocation, expired capabilities, offline recovery and
   package compatibility are tested at their owning boundaries. This decision
   authorizes no production data migration or installation. Platform PA
   retirement still requires the functional and data handoff acceptance in the
   migration plan; the permanent product owner is Launcher alone.

## Alternatives

- Forward every project request through Electron: rejected for this migration
  because it duplicates an existing native SDK's transport, errors and recovery
  without changing the model/renderer credential boundary. It may be revisited
  only if the trusted host isolation or credential requirements change.
- Move the SDK to a separate Python worker: rejected because another process
  adds packaging, supervision and recovery work while sharing the same trust.
- Give the renderer a generic project proxy or token: rejected because it
  expands the authority and attack surface beyond closed business actions.
- Keep a project-local PA as a proxy: rejected because project restarts would
  still affect the assistant and both products would need maintenance.

## Consequences

Business APIs, authorization and task recovery retain one native implementation.
Electron keeps a smaller registry, window and lifecycle boundary. SDK, target
DTO and packaged dependency compatibility must be validated together, and the
trusted host necessarily holds private project capabilities. Logs and tool
projections must continue to exclude them.

Offline lifecycle admission/recovery, remaining user-facing capabilities,
history/in-flight migration and platform retirement remain separate deliverables.
A successful source test or earlier sealed package cannot substitute for the
current package's real-provider and page acceptance.
