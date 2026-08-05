# ADR 0005 · Docs Authority Layers And Archive Policy

## Status

Accepted (codified 2026-08-05 after docs cleanup waves).

## Context

The repository accumulated large volumes of dated plans, superpowers specs, ops audits, and one-off reports. When those files remained as top-level peers of `docs/standards/`, Agents treated them as current instructions, causing:

- conflicting UI stacks (HeroUI vs VUI);
- stale plan links from service READMEs;
- noise that crowded out operator config and protocol truth.

## Decision

### Authority order (high → low)

1. User’s current explicit request and authorization
2. Root `AGENTS.md`
3. `docs/standards/`
4. ADR + owning module README
5. `docs/ops/config/` + `core/llm/PROTOCOL.md` (config / wire semantics)
6. `docs/agents/` living maps
7. `docs/product/` living product register
8. `docs/archive/**` and `.docs/project-memory/` — **history / state only**, never competing rules

### Placement rules

| Artifact | Location |
| --- | --- |
| Cross-module rules | `docs/standards/` |
| Agent task routing (READ/EDIT/TEST, ownership, loop) | `docs/guides/` (must not redefine rules; not end-user docs) |
| Why a design choice was locked | `docs/adr/` |
| Operator config fields | `docs/ops/config/` |
| Collaboration / flow maps | `docs/agents/` |
| Product purpose & UI register | `docs/product/` |
| Dated plans, old specs, one-off reports | `docs/archive/` (prefer move over delete) |
| Mutable work state | `.docs/project-memory/` |

### Lifecycle

- New written plans: status metadata + close condition; on finish → **archive**.
- Do **not** reintroduce long-lived top-level `docs/plans/` or `docs/superpowers/` as authority.
- Archive may keep broken internal links; living trees must not point at dead top-level paths.
- If archive content is still true, **distill into a living doc** then cite the living doc.

## Consequences

- Top-level `docs/` stays thin (~dozens of living markdown files).
- Service / route READMEs link ownership maps, not phase plans.
- Document maps (`docs/README.md`, `INDEX.md`) must be updated when trees move.

## Related

- `docs/README.md`
- `docs/archive/README.md`
- `docs/standards/development-standard.md` §19.1
