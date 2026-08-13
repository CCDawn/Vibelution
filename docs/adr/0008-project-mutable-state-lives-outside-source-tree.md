# ADR 0008 · Project Mutable State Lives Outside The Source Tree

## Status

Accepted (2026-08-14).

## Context

The repository historically accumulated active `workspace/`, `.runtime/`,
`logs/`, `backups/`, and `.docs/project-memory/` content. Git ignore rules kept
these files out of commits, but did not prevent large logs, databases, runtime
locks, browser profiles, research evidence, or coordination projections from
polluting a checkout or colliding across worktrees.

Operator configuration was already external, but mutable project state had no
single identity, root, migration gate, or rollback contract.

## Decision

1. The repository tracks only source, templates, rules, formal documentation,
   and `.vibelution/project.json`. The tracked `projectId` is stable across
   clones and worktrees; it contains no operator or runtime data.
2. Mutable state defaults to:

   ```text
   %LOCALAPPDATA%\Vibelution\projects\<projectId>\
     memory\
     instances\<instanceId>\
       data\
       runtime\
       logs\
       cache\
   ```

   `instanceId` is derived from the normalized checkout path, so worktrees do
   not overwrite one another. Project governance memory is project-shared;
   product data and runtime state are instance-isolated.
3. `%USERPROFILE%\Documents\Vibelution\config` remains the operator-editable
   configuration authority. Explicit `VIBELUTION_DATA_HOME` or
   `[storage].data_home` remains an operator override.
4. Existing installations do not switch to an empty external root. They keep
   legacy paths active until `scripts/migrate_project_storage.py apply`
   completes copy, inventory recheck, per-file SHA-256 verification, manifest
   write, and an atomic completion marker.
5. Migration never deletes or overwrites different legacy content. Rollback
   archives only the completion marker and retains both copies. Physical legacy
   cleanup requires a separate, explicit destructive confirmation.
6. `.docs/project-memory/` is a legacy read-only projection after migration.
   Live Agent coordination remains under the Git common dir; durable project
   memory resolves from the external `memory` path and never becomes runtime
   authority over code, Git, tests, or logs.
7. A fresh checkout with no legacy state uses external paths immediately and
   must not generate mutable files in the source tree.

## Consequences

- Runtime diagnostics shown as `logs/runtime_scenes/...` are logical product
  paths; their physical root is the active external project state root.
- Tools must call `vibelution_storage.py` or the infrastructure compatibility
  import, not concatenate `PROJECT_ROOT/.runtime`, `PROJECT_ROOT/logs`, or
  `project_root/workspace` for active state.
- The tracked identity file is mandatory and fails closed when missing or
  invalid. Runtime code must not silently generate a new project identity.
- Old ignored directories can remain on disk for rollback and audit without
  receiving new writes after the verified switch.

## Operations

```powershell
python scripts/migrate_project_storage.py inventory --project <project-root>
python scripts/migrate_project_storage.py apply --project <project-root>
python scripts/migrate_project_storage.py rollback --project <project-root>
```

Run `apply` only while Launcher, Runtime Manager, tests, and Agents are stopped
for that checkout; a changing source aborts before the completion marker.

## Related

- [ADR 0003](0003-operator-config-lives-outside-repo.md)
- `vibelution_storage.py`
- `core/infrastructure/storage_migration.py`
- `docs/ops/config/01-authority-and-paths.md`
