# ADR 0012 · Launcher Owns The Personal Assistant Runtime

## Status

Accepted (2026-10-24). Supersedes only the two-role Python restriction in
[ADR 0009](0009-launcher-control-plane-lives-in-electron-main.md), Decision 5.
All other Launcher control-plane ownership in ADR 0009 remains in force.
Project API transport is refined by
[ADR 0013](0013-launcher-assistant-reuses-native-project-sdk.md); this does not
change the lifecycle and shared-engine ownership below.

## Context

The user chose to move the complete personal assistant into Launcher and retire
the platform product surface. A project restart must not restart its conversation
or lose task references. Reimplementing the existing Session, Journal, provider
and tool authorization engines in TypeScript would create two maintenance paths.
The settled migration is recorded in the
[migration plan](../plans/2026-10-23-launcher-personal-assistant-migration.md).

## Decision

1. Electron main remains the sole Launcher lifecycle, window and project registry
   owner. It may supervise one additional Python role: `launcher_assistant`.
   This child is a native conversation runtime, never a second Launcher control
   plane. It must not mount the Workbench lifespan or write Workbench lifecycle
   state, instances, command queues or runtime ownership records.
2. The assistant process fixes its native profile root before importing native
   services. The default Workbench root resolution is unchanged. A process cannot
   switch profiles or project roots after import. The assistant reuses native
   Agent/Session/Journal/provider/tool code from a single source tree.
3. The renderer uses a role-scoped main-process bridge. Its private loopback child
   requires a generation-specific bearer credential, does not publish a token
   endpoint, and rejects browser Origins. Credentials never enter renderer state,
   CLI arguments, URLs, public receipts or diagnostics.
4. Project work uses native authorized APIs. The first task adapter reuses the
   external-Agent gateway's hidden Sessions, task capabilities, stable request
   keys, approval and receipts. It does not require a personal assistant Agent or
   Session in the target project. Its private credential files are separate from
   MCP adapters. UI disconnection never calls MCP `shutdown()` or cancels tasks.
   Gateway eligibility, permission ceilings and finite leases still apply.
5. Native task IDs and native Session receipts remain authoritative. Launcher
   persists only request associations, opaque native references and bounded
   receipts. Unknown responses cannot justify a new request ID or fabricated
   success. Lease expiry and revocation are reported as native outcomes.
6. Final ownership is Launcher-only. Platform PA routes, settings, bootstrap and
   patrol are retired after independent runtime, migration and receipt acceptance;
   generic project APIs and ordinary Agent/Session behavior remain. Source-host
   acceptance alone does not authorize claiming full package/data migration.
7. The native Windows `--assistant` entry resolves a fixed managed package under
   KnownFolder LocalAppData, before any project parsing or project mutex. It
   never discovers a checkout, invokes a Python bridge, or repairs an install.
   The existing desktop build owner remains the sole producer. Explicit
   installation publishes verified immutable versions and atomically changes a
   closed active pointer last, preserving previous versions. The pointer pins a
   content-addressed catalog plus EXE/provenance hashes; neither hashes nor a
   caller-selected local build output constitute publisher authentication.
   Private injected installation roots exist only in test functions/harnesses,
   not in the public native CLI. The final startup admission pins verified
   files and path identities until OS process creation and checks membership
   again at handoff; it does not claim an ACL against later same-user writes.
   Integrity I/O retains namespace paths for long files. Final process startup
   uses ordinary Win32 spelling only after reopening EXE and cwd against the
   same admitted final paths; those additional handles stay in the same lease.

## Alternatives

- Keep a project-local PA as a permanent proxy: rejected because restart and
  identity coupling remain and both product implementations require maintenance.
- Rewrite conversation execution in Electron: rejected because native provider,
  Journal, streaming, policy and recovery code already provide these contracts.
- Mount the whole Workbench app as an assistant child: rejected because it starts
  unrelated services and recreates project coupling.
- Make MCP disconnection semantics the Launcher owner: rejected because its
  normal shutdown deliberately cancels tasks and native leases are finite.

## Consequences

The shared engine has one implementation; Launcher gains a small supervisor,
private transport and project adapter. Packaging must include and fingerprint
the Python dependency closure. Profile migration, authorization, finite offline
recovery, package freshness and platform retirement each require independent
evidence. Normal rollback targets a compatible Launcher package and does not
re-enable a second platform assistant.
