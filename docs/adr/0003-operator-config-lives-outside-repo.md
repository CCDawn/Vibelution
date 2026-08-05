# ADR 0003 · Operator Config Lives Outside The Repo

## Status

Accepted (codified 2026-08-05 from long-standing runtime practice).

## Context

Vibelution is local-first. Operators need secrets, provider keys, ports, and model profiles that:

- must not be committed to git;
- must survive worktree switches and clean checkouts;
- must be shared across Launcher, Runtime Manager, Workbench, and headless agents.

The repository still ships template / legacy config under the project root (`config/`, example TOML). Agents and humans frequently edit the wrong file and report “config change has no effect”.

## Decision

1. **Active operator config** lives under the user profile data home, defaulting to:
   - Windows: `%USERPROFILE%\Documents\Vibelution\config\config.toml`
   - Resolved via `config/paths.py` (`VIBELUTION_CONFIG_PATH` / `VIBELUTION_CONFIG_HOME` overrides).
2. **Repository root config** is **template / legacy / public defaults only**, not the runtime authority for packaged or desktop-started sessions.
3. Failures in schema or credentials should be fixed in the **external** operator file, not by hard-coding keys in source.
4. Product docs and Agent checklists must point to the Documents path first (see `docs/ops/config/`).

## Consequences

- Changing only repo-root TOML will not reconfigure a normal desktop session.
- Packaging and Electron must not hard-code production secrets into the install tree.
- Tests may inject `VIBELUTION_CONFIG_PATH` to isolate fixtures.
- Detailed field semantics stay in `docs/ops/config/*`, not in this ADR.

## Related

- `docs/ops/config/01-authority-and-paths.md`
- `config/paths.py`
- root `AGENTS.md` §4 (active operator config path)
