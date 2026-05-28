# Changelog

## 0.4.0 - 2026-05-28

- Added Impeccable product/design context for Vibelution frontend visual work.
- Unified Agent management routes around Agent Center navigation, prompt templates, tools, skills, memory, runtime evidence, and responsive `/agents` behavior.
- Added a read-only Skill Library plus `/skill` slash-command routing into chat turns with bounded runtime context and lifecycle logging.
- Added missing-Agent placeholders and safer delete/reference cleanup so sessions, rooms, bindings, and research canvases can surface invalid Agent content without crashing.
- Streamlined research theme discovery onto Agent-only flow-canvas nodes and updated related route/tests.
- Refined the Agent management surface with a denser control-room layout, stronger runtime/status hierarchy, and polished operational navigation.

## 0.3.0 - 2026-05-27

- Added the unified Agent configuration foundation across AgentInstance, PromptTemplate, ModeBinding, and ContextEngine boundaries.
- Expanded Agent settings APIs for prompt templates, mode bindings, inbox messages, and recent Agent run history.
- Migrated chat, research, supervised evolution, and self-evolution paths toward Agent-based runtime resolution.
- Improved the research flow canvas with Agent bindings, stricter contract validation, and corrected default routing contracts.
- Refined the workbench settings and chat surfaces for Agent configuration, role bindings, and cross-Agent messaging.

## 0.2.1 - 2026-05-27

- Fixed a startup overlay false positive where non-blocking lifecycle proof items could mark an already running workbench as failed.
- Kept advisory runtime source freshness signals visible in lifecycle proof without blocking open/steady workbench sessions.

## 0.2.0 - 2026-05-27

- Added multi-agent conversation and chat room foundations, including persistent agent registry, conversation APIs, and group context handling.
- Expanded the research workspace with configurable research agents, knowledge-base backed research flow, richer canvas editing, and additional validation coverage.
- Improved the web workbench surface across chat, memory, config, self-evolution, and runtime status views.
- Strengthened tool execution, shell safety, LLM routing/configuration, and runtime scene observability.
- Added focused backend and frontend regression coverage for the new workbench, research, agent, and tool behaviors.
