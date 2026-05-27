# Changelog

## 0.2.1 - 2026-05-27

- Fixed a startup overlay false positive where non-blocking lifecycle proof items could mark an already running workbench as failed.
- Kept advisory runtime source freshness signals visible in lifecycle proof without blocking open/steady workbench sessions.

## 0.2.0 - 2026-05-27

- Added multi-agent conversation and chat room foundations, including persistent agent registry, conversation APIs, and group context handling.
- Expanded the research workspace with configurable research agents, knowledge-base backed research flow, richer canvas editing, and additional validation coverage.
- Improved the web workbench surface across chat, memory, config, self-evolution, and runtime status views.
- Strengthened tool execution, shell safety, LLM routing/configuration, and runtime scene observability.
- Added focused backend and frontend regression coverage for the new workbench, research, agent, and tool behaviors.
