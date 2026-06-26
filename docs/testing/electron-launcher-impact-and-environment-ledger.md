# Electron Launcher Impact And Environment Ledger

日期：2026-06-26
范围：low-risk Electron Launcher supervisor migration

## Impact Rules

- Do not change startup ownership before protocol, active-work guard, and generic provider tests pass.
- Do not remove Edge provider or `browserManaged` compatibility before Electron is default and old tests are migrated.
- Do not let Electron main own product semantics, LLM routing, tool execution, Git execution, memory writes, or self-evolution decisions.
- Do not package until unpacked smoke proves one public entry and no independent Workbench shortcut.

## Config And Environment Rules

- Active operator config remains `C:\Users\17533\Documents\Vibelution\config\config.toml`.
- Root `config.toml` and `config.example.toml` are legacy/template surfaces, not packaged runtime authority.
- Python path, ports, Launcher URL, Workbench URL, and control-token presence come from existing Launcher/runtime-manager resolution or explicit dev/test override.
- Electron must not hard-code production ports, spawn shell wrappers as normal lifecycle, or log full environment variables.

## Exit Condition

Implementation can move past Tasks 0-4 only when tests prove protocol shape, deep-link parsing, generic provider state, and config/environment resolution are stable without starting runtime children.
