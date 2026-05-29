# Changelog

## 0.4.26 - 2026-05-29

- Simplified Chat/Coding auxiliary message rendering: “思考过程” and “心智模型” now render as compact dedicated panels instead of duplicated operation-timeline rows.
- Expanded the mental model panel so mood, cognitive state, source, confidence, samples, timestamp, feeling, summary, whisper, and intervention can be inspected from the conversation itself.

## 0.4.25 - 2026-05-29

- Fixed Chat/Coding thought visibility: captured assistant `thought` text now appears as a folded summary on the “思考过程” row, and the same text is available as the thought operation detail instead of being stored but visually empty.

## 0.4.24 - 2026-05-29

- Added permanent purge for already archived Agents: Agent Center now exposes a separate irreversible delete action for archived Agents, backed by `DELETE /api/agents/{agent_id}/purge`.
- Purging removes the AgentDirectory record, unreferenced private tool/memory policies, stale mode/group-room references, and the Agent private workspace while logging `agent.purged`; active and protected Agents remain blocked from physical deletion.
- Group-room cleanup now repairs legacy session-only participants before Agent removal, so archived/direct-session Agents cannot slip past unique-member guards because of stale participant shape.

## 0.4.23 - 2026-05-29

- Retired the duplicate `/chat-rooms` group-chat workspace route and kept it as a compatibility redirect into `/chat`.
- Preserved `/chat-rooms?room=...` deep links by redirecting them to `/chat?room=...`, so Chat/Coding remains the single group-chat user surface while `/api/chat-rooms` stays as the backend contract.

## 0.4.22 - 2026-05-29

- Bound the Research Flow Canvas to the stable `research-team` Team entity while keeping `research_organization` as the live organization source.
- Added research-Team synchronization from the active organization graph so Team members, Team canvas nodes, and communication edges stay aligned with the locked research canvas.
- Pruned unresolvable active Research Organization nodes during canvas repair so embedded stale Agent snapshots cannot drift the locked canvas away from AgentDirectory.

## 0.4.21 - 2026-05-29

- Added a Teams inspector task kickoff form that starts the linked Chat/Coding group-room round directly from a selected Team, carrying `source=team_workspace` and `teamId` metadata.
- Blocks task kickoff until the Team has a linked room, active members, and no busy linked-room round, then refreshes team, chat-room, and conversation caches with an open-group-chat handoff link.

## 0.4.20 - 2026-05-29

- Closed archived-Agent execution gaps across edit-resubmit, queued chat workers, chat-room speakers, and ContextEngine context lookup so AgentDirectory active Agents remain the runtime source of truth.
- Fixed chat-room speaker reservation order so a waiting group speaker reserves the Agent execution slot before expensive context preparation, preventing later direct turns from cutting ahead.

## 0.4.19 - 2026-05-29

- Tightened AgentDirectory as the Agent availability source: archived or missing Agents now block chat turn scheduling and inbox wake delivery instead of being runnable through stale direct-session references.
- Split silent ensure from explicit restore semantics: `ensure_agent_for_session` no longer reactivates archived Agents, while fixed supervised/self-evolution role bootstrap uses explicit `agent.reactivated` diagnostics.

## 0.4.18 - 2026-05-29

- Linked Agent Center Teams to Chat/Coding group rooms: teams with active Agent members now create and maintain a linked group chat, and canvas member changes sync that room's participants.
- Added a Teams page control to open or sync the linked group chat, plus `/chat?room=...` deep-link support so team, canvas, Agent members, and group-chat execution share one navigation path.

## 0.4.17 - 2026-05-29

- Fixed Chat/Coding direct session deletion so deleted Agent-bound session ids no longer reappear from the AgentDirectory direct-session index.
- Rebind the active Agent to a fresh empty direct session after deleting its old conversation record, while keeping the Agent active and adding `session.delete.agent_rebound` lifecycle diagnostics.

## 0.4.13 - 2026-05-29

- Reworked Agent Center filters into status, runtime mode, and reference sections so active Agents, archived records, mode membership, group-chat references, and team references are no longer mixed in one flat list.
- Changed the default Agent Center filter to active Agents so archived records no longer inflate the primary available-Agent view.

## 0.4.12 - 2026-05-29

- Made direct chat session deletion diagnosable by logging requested, busy-blocked, and deleted lifecycle events into runtime scene conversation logs.
- Show a visible busy-delete reason in the Chat/Coding session list when a direct session is still running or stopping instead of relying only on a disabled delete button.

## 0.4.11 - 2026-05-29

- Added QQ-like blue clickable `@` mentions in the Chat/Coding project bus and group-chat timelines, resolving active Agent code/name/id mentions to their direct conversation index and `@全体成员`/`@all` to the project bus index.
- Added focused mention tokenization coverage so unknown mentions remain plain text while recognized Agent mentions preserve the original message content around them.

## 0.4.10 - 2026-05-29

- Added read-only research organization context to persistent Research Agent turns so a CEO/advisor/steward can see connected team members, Agent IDs/codes, roles, responsibilities, communication edges, allowed message types/intents, and wake policy before using `agent_message_tool`.
- Filtered the runtime organization context to the current Agent's connected communication subgraph so stale historical research nodes do not pollute the member list.

## 0.4.9 - 2026-05-29

- Added the project Agent bus and Agent Teams workspace so project-wide and team-scoped broadcasts can target active Agents, wake or interrupt them, appear in the shared bus timeline, and be revoked through the UI.
- Routed research-organization Agent messages through the organization graph policy layer and locked the Research Flow Canvas to the live organization graph, including read-only Agent/communication-line rendering and stale/archived Agent safety fixes.
- Tightened Agent Center pages into a compact console layout across Agents, Prompt Templates, Tools, Skills, and Memory, while exposing team references, archived/protected Agent counts, and safer archive semantics.
- Reduced frontend API failure telemetry noise by suppressing pagehide-adjacent background GET cancellations without hiding normal foreground failures.

## 0.4.8 - 2026-05-29

- Fixed AgentDirectory-only direct sessions in Chat/Coding so selecting or sending to an active Agent direct session materializes it into chat state instead of returning "Session not found."
- Added lifecycle logging and regression coverage for materializing active Agent direct sessions from Agent Center metadata before detail, attachment, delete, or message submission flows.

## 0.4.7 - 2026-05-28

- Clarified Agent Center archive semantics for protected core research Agents: active CEO/advisor/steward cards now show a neutral archive-protection panel instead of the destructive safe-archive zone.
- Added the archived Agent count to the Agent Center summary so protected active Agents and truly archived Agents are visibly separate.
- Locked the research flow canvas to the live research organization graph so it shows active project Agents, person-name/function tags, and communication edges from the same project-bound source.

## 0.4.6 - 2026-05-28

- Aligned Chat/Coding conversation indexes with Agent Center as the authoritative Agent source: direct conversations now carry Agent primary mode, role key, and prompt template metadata, and active Agent Directory direct sessions can appear in the conversation list even when chat state lacks a matching conversation entry.
- Updated Chat/Coding grouping so research organization members classify under the Research Agent group from Agent Center metadata instead of brittle session titles or legacy profile labels.

## 0.4.5 - 2026-05-28

- Routed `agent_message_tool` messages involving research organization Agents through the organization graph policy layer, so CEO, organization advisor, capability steward, and recruited research members honor communication edges, message type/intent rules, supervision gates, inbox delivery, wake rules, and audit logging.
- Added regression coverage for allowed CEO-to-capability-steward delivery, blocked advisor-to-CEO task delivery, and blocked outsider-to-core Agent delivery through the real tool executor path.

## 0.4.4 - 2026-05-28

- Exposed restricted tool permission metadata in the tool registry so Agent management can distinguish default-inherited tools from explicit-allow tools.
- Updated the Agent tools workbench to show the research knowledge query tool as requiring explicit Agent allow-list permission before it becomes visible or callable.

## 0.4.3 - 2026-05-28

- Added the protected research Capability Steward Agent as the third default core role beside CEO and organization advisor.
- Assigned role-specific tool policies, memory read/write groups, and graph communication edges so prompt, tool, and memory governance can start from a minimal ordered team.
- Restored the built-in capability steward prompt template and updated the default research flow canvas to show the graph-shaped three-role opening structure.

## 0.4.2 - 2026-05-28

- Changed the default research team entry to CEO Agent plus organization advisor only; specialist research Agents are now explicitly activated or created through CEO/advisor organization proposals instead of being auto-seeded.
- Updated the research flow canvas default to the CEO-to-advisor organization entry while preserving explicit worker flow execution support and regression coverage.

## 0.4.1 - 2026-05-28

- Fixed Research AgentInstance sync so archived or missing Research Agents are replaced before mode binding updates, preventing repeated `research.mode_binding.sync_failed` runtime-scene errors from stale Agent ids.
- Added lifecycle logging for stale Research Agent replacement and regression coverage for archived Research mode binding references.

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
