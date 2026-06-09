# Changelog

## 1.0.9 - 2026-06-09

- Extended the Launcher runtime-manager restart wait window so guarded rebuild/close/open transactions can finish without the outer `-Action restart` call timing out near completion.
- Added Launcher regression coverage for the explicit `restart_workbench` wait timeout and forwarded command flags.

## 1.0.8 - 2026-06-08

- Coalesced duplicate Launcher close requests so repeated stop clicks join the in-flight close instead of queueing extra shutdowns.
- Skipped residual process cleanup for already-closed clean Workbench observations while preserving strict cleanup for manager shutdowns and real residual evidence.
- Added segmented Launcher shutdown timing evidence to runtime-scene and control logs so slow stops identify the backend, port wait, browser, or closure-snapshot phase.

## 1.0.7 - 2026-06-08

- Made the Challenge Cup research team surface show one selected workflow node at a time, with Source Collection, Coordination, Ingestion, Candidate Graph, Candidates, Discussion, and Canvas separated behind the team-level index.
- Unified the synced research team display name to `ai科学研究团队` and kept the canvas as an auxiliary view instead of the default right-panel content.
- Bound source-collection run assignments to functional team Agents from the Team canvas when available, while preserving the contract-only boundary with no external search, formal Team Knowledge, RAG, or official graph writes.

## 1.0.6 - 2026-06-08

- Switched the backend ready wait loop to a direct HTTP ready probe instead of full backend liveness scans on every startup poll.
- Tightened Launcher backend ready polling from 500ms to 250ms while still requiring a successful Workbench HTTP response before reporting the runtime scene ready.
- Added Launcher regression coverage for the faster HTTP-ready wait contract.

## 1.0.5 - 2026-06-08

- Removed the startup-ready-path browser process memory snapshot so opening the managed Workbench window no longer waits on an unsupported multi-second process scan.
- Changed Launcher backend readiness checks to probe the Workbench root URL first, with `/api/health` retained as a fallback, reducing startup wait time while preserving API health semantics.
- Added Launcher regression coverage for the non-blocking browser memory evidence path and root-first readiness probe.

## 1.0.4 - 2026-06-08

- Marked managed Workbench sessions ready before attaching the desktop supervisor so Launcher restart/open commands finish after the backend and window are live.
- Started supervisor attachment as a non-blocking hidden background step with runtime-scene evidence for ready, attach-started, and attach-failed paths.
- Added launcher regression coverage for the ready-before-supervisor lifecycle order and preserved full Launcher script test coverage.

## 1.0.3 - 2026-06-08

- Prevented the PowerShell Launcher frontend dependency and build paths from invoking npm `.cmd` wrappers, avoiding transient Windows cmd flashes during startup.
- Switched Launcher frontend build execution to direct Node.js package entrypoints for TypeScript and Vite while preserving runtime-scene build logs.
- Added launcher regression coverage so frontend build and dependency flows cannot silently return to cmd shim execution.

## 1.0.2 - 2026-06-08

- Blocked direct Launcher and Workbench window closes while the managed project is still running, using browser beforeunload confirmation plus lifecycle telemetry.
- Preserved controlled Launcher stop/restart flows by sharing a short-lived lifecycle-operation marker with the Workbench window.
- Added regression coverage for running, partial, closed, and controlled lifecycle close-guard states.

## 1.0.1 - 2026-06-08

- Fixed supervised-evolution judge marker extraction so prompt examples cannot override the real final judge response.
- Hydrated referenced conversation payload files before summarizing supervised Agent judgments, preserving real PROMOTE/HOLD decisions and scores in persisted reports.
- Added regression coverage for referenced LLM responses and prompt-example marker noise.

## 1.0.0 - 2026-06-08

- Promoted Vibelution to the stable 1.0.0 line across the canonical backend version source and frontend package metadata.
- Recorded the stable mainline contract after the Launcher lifecycle, runtime-scene diagnostics, supervised evolution surfaces, and multi-agent worktree workflow became inspectable as one product baseline.
- Kept this release bump scoped to version metadata and changelog documentation; no runtime behavior, API contract, or evaluation harness code changed in this release commit.

## 0.12.1 - 2026-06-08

- Added the Challenge Cup AI research team source-collection execution panel to the Teams surface, with run startup, assignment/query visibility, and manual result writeback into candidate source records.
- Kept the source-collection UI on the candidate side of the knowledge boundary: no external search execution, no formal Team Knowledge writes, no RAG writes, and no official graph publication.
- Hardened Launcher/workbench state reconciliation and supervised-evolution transaction closure so merged development rounds refresh and close more reliably.

## 0.12.0 - 2026-06-08

- Added lightweight runtime-manager live-control probes for evolution control surfaces, reducing expensive process inventory work during polling while preserving lifecycle evidence.
- Added agent-judged Terminal-Bench-style supervised evaluation support with explicit non-official score labeling, limited bundle materialization, and judge-artifact tests.
- Split heavy shell surfaces into lazy AppShell utility/status panels and tightened topbar responsive behavior for dense launcher/workbench layouts.
- Added chat-review candidate detail loading and self-evolution overview caching so review and evolution surfaces stay responsive.
- Switched the default Workbench window mode to fullscreen across product defaults, example config, and launcher-facing tests.

## 0.11.5 - 2026-06-08

- Kept Workbench shell and Chat startup data loading alive while the managed window is hidden, using a bounded startup warmup instead of permanent high-frequency background polling.
- Allowed Chat session streams to connect during startup warmup and logged warmup state in browser telemetry.
- Adjusted managed Edge launch flags to avoid background networking and timer throttling during startup.

## 0.11.4 - 2026-06-08

- Added a traceable Challenge Cup data-search plan contract to source-collection run startup, including query seeds, planned queries, role assignment inputs, and result writeback boundaries.
- Extended `/api/teams/{team_id}/workflow-orchestration/source-collection-runs` with query seed, language, source type, and max-results inputs while keeping the slice contract-only with no external search execution.
- Updated the Challenge Cup flow HTML to show M6.5 data-search planning as the next step in the source-collection Agent workflow.
- Fixed permanent Agent deletion so active Agents can be purged directly, including solo chat-room cleanup and direct-session tombstone preservation.
- Preserved deleted-Agent session history without allowing session repair to recreate purged Agents.
- Kept unresolved current LLM bindings visible in Agent model slot selectors and preserved structured `llmBindings` in runtime scene child logs.
- Added management-center safeguards for bulk Agent purge, generated-tool deletion, and prompt-template reset/deactivation, while making Skill bulk edit/delete visibly read-only.

## 0.11.3 - 2026-06-07

- Added a Team workflow source-collection run launcher that creates a generic DataProcessing run plus functional collection assignments for the AI research team.
- Exposed `/api/teams/{team_id}/workflow-orchestration/source-collection-runs` so the research coordinator can start a traceable source batch before DataRecord import.
- Updated the Challenge Cup flow HTML to show source-collection run startup as the entry into the data-gathering Agent workflow.

## 0.11.2 - 2026-06-07

- Removed archived Team member Agents from extra group rooms during Team archive cascade, while preserving the existing linked Team room deletion behavior.
- Added Team archive cleanup evidence with removed room ids and per-Agent room cleanup mapping in runtime scene events.
- Refreshed Team archive frontend caches for Agents, mode bindings, chat rooms, sessions, conversations, config workspace, and project bus state.

## 0.11.1 - 2026-06-07

- Added a Team workflow bridge that imports generic DataProcessing records into Challenge Cup `source_manifest` candidates while preserving run, record, quality, and collection-trace metadata.
- Exposed the bridge through `/api/teams/{team_id}/workflow-orchestration/data-processing/runs/{run_id}/records/{record_id}/source-candidate` with idempotent duplicate handling.
- Updated the Challenge Cup flow HTML to mark DataRecord-to-source-manifest import as the handoff from generic collection to the AI research team candidate workflow.

## 0.11.0 - 2026-06-07

- Added the generic data-processing substrate with profiles, runs, records, collection assignments, collection outputs, and status APIs under `/api/data-processing`.
- Persisted data-processing runs under `workspace/data_processing/runs/<runId>` so agent-driven source collection can be tracked before any domain-specific knowledge publication.
- Recorded safe runtime scene events for data-processing run, record, assignment, and output activity while keeping raw source content out of lifecycle logs.
- Updated the Challenge Cup flow HTML to position data processing as the generic source-collection layer feeding the AI research team workflow.

## 0.10.46 - 2026-06-07

- Added bulk selection bars to the Agent, Prompt Template, Tool, and Skill management pages.
- Added safe bulk actions for Agent prompt assignment/archive, prompt category/reset/deactivate, and generated-tool enable/disable/delete while preserving existing per-item protection rules.
- Kept the Skill library read-only while adding bulk command copy and disabled edit/delete controls with explicit read-only guidance.
- Hardened supervised-evolution startup with runtime-manager source freshness checks and safer active-work probe failures.
- Added guarded restart frontend build preflight and Launcher desktop-entry validation before closing a running workbench.
- Improved supervised evaluation environment handling, memory detail surfaces, and related workbench UI affordances.

## 0.10.45 - 2026-06-07

- Added read-only communication briefs to the Challenge Cup workflow coordination status API, mapping queue items to target functional Agent roles and suggested delivery channels without sending messages automatically.
- Surfaced coordination brief targets and channel hints in the Teams research workflow panel while keeping transfer, approval, and formal-knowledge writes disabled.
- Updated the Challenge Cup flow HTML to document coordination briefs as the bridge between workflow queues and later team communication dispatch.

## 0.10.44 - 2026-06-06

- Optimized Agent Center loading by reusing repaired Agent registry snapshots, batching Agent API hydration and runtime history reads, and logging slow `list_agents` hydration breakdowns.
- Added Agent creation tool packages in the Web Agent Center, while keeping per-tool policy tuning available after creation.
- Hardened direct-session Agent indexing, archive/purge cleanup, team-linked chat room cleanup, and runtime LLM binding diagnostics with focused lifecycle evidence.
- Removed stale legacy `llmConfigId` flow-canvas persistence from the frontend contract and aligned visible copy around Agent model slots.

## 0.10.43 - 2026-06-06

- Added a read-only Challenge Cup workflow coordination status API that groups pending transfers, rework candidates, stewardship items, blocked candidates, and active work for the research team.
- Surfaced the coordination queue in the Teams research workflow panel without adding automatic transfer, approval, or formal-knowledge write controls.
- Updated the Challenge Cup flow HTML to show the coordination queue as the team organization layer for research review and knowledge-governance handoff.

## 0.10.42 - 2026-06-06

- Collapsed low-frequency Chat/Coding session diagnostics behind a compact context diagnostics disclosure while keeping status, LLM input, token speed, current task, and prompt-cache facts visible.
- Kept previous-turn context/cache composition and compression details available inside the diagnostics disclosure instead of occupying the default left rail.
- Renamed ordered execution-trace expansion copy from tool-call language to execution-detail language so mixed thought/status/tool chains are labeled truthfully.

## 0.10.41 - 2026-06-06

- Added a Teams workspace knowledge-ingestion status panel for the Challenge Cup research team, showing staged source/candidate/steward/review/official-sync progress from the read-only status API.
- Surfaced action items and official Knowledge/RAG/Graph boundaries in the research workflow panel without adding approval or write controls.
- Updated the Challenge Cup flow HTML to mark the Teams status funnel as the visible coordination entry for the knowledge ingestion process.

## 0.10.40 - 2026-06-06

- Added a read-only Challenge Cup knowledge-ingestion status API for Team workflows, summarizing CandidateStore progress, candidate validation, candidate graph health, Team Knowledge proposal/item counts, and official sync boundaries.
- Returned staged action items for source collection, candidate screening, steward-pack review, and official graph sync without creating KnowledgeItems, writing RAG content, or generating new candidate graph snapshots.
- Updated the Challenge Cup flow HTML to mark the knowledge-ingestion status view as landed and document the pending-review versus official-sync boundary.

## 0.10.39 - 2026-06-06

- Added a shared Agent Turn Runtime facade for chat, self-evolution, and supervised-evaluation runs, producing common runtime metadata and prompt-cache partitions.
- Wired self-evolution executor turns to record safe `turnRuntime` diagnostics in lifecycle logs without changing run-state, carryover, or transaction semantics.
- Propagated supervised Agent runtime metadata through harness child-process environment variables so baseline and candidate runs keep isolated cache scopes while reusing the shared turn contract.

## 0.10.38 - 2026-06-06

- Split prompt-cache usage observation into cache read hits, cache writes, and uncached input tokens across LLM logs, session detail APIs, and the Chat/Coding status UI.
- Added stable per-agent/per-session/per-model prompt cache partitioning for chat turns so automatic cache keys no longer drift per turn.
- Recorded safe prompt-cache key hashes and cache composition diagnostics without logging raw cache keys or prompt text.

## 0.10.37 - 2026-06-06

- Added the Challenge Cup review rework/rejection closure path: transfer decisions can now return candidates to the smallest upstream revision node or archive rejected candidates in `metadata.rejectionArchive`.
- Candidate graph snapshots now exclude rejected/archive candidates from the active graph while reporting `archivedCandidateCount`.
- Updated the Teams research workflow graph stats and Challenge Cup flow HTML/technical plan to show the closed rework/rejection behavior.

## 0.10.36 - 2026-06-06

- Added a Candidate Graph panel to the Team workspace research workflow view, reading latest `candidate_graph` snapshots and rendering candidate nodes, evidence-direction edges, missing links, unreviewed nodes, and candidate-only boundary status.
- Added a Team workflow graph refresh action that reuses the existing candidate-only graph builder without writing formal Team Knowledge, RAG, or the official knowledge graph.
- Updated the Challenge Cup flow HTML and technical plan to mark Teams candidate graph visualization as landed.

## 0.10.35 - 2026-06-06

- Fixed Launcher `status` so it remains read-only: it now reports missing or incomplete Python dependencies without creating `.venv` or running `pip install`.
- Added an explicit `repair-deps` Launcher action for Python dependency bootstrap and kept mutating start/restart flows on the existing dependency repair path.
- Added pip install override support through `VIBELUTION_PIP_INDEX_URL`, `PIP_INDEX_URL`, and `VIBELUTION_PIP_EXTRA_ARGS`, with structured dependency status logging.

## 0.10.34 - 2026-06-06

- Added a read-only Research Workflow panel to the Team workspace for `research-team` / research-organization teams, showing workflow stage, CandidateStore totals, active workflow items, validation summary, and recent candidate states.
- Wired the panel to the existing TeamWorkflowOrchestration and candidate list APIs without adding transfer, approval, Team Knowledge, RAG, or graph write actions.
- Updated the Challenge Cup flow HTML and technical plan to mark the Team workspace workflow panel as landed.

## 0.10.33 - 2026-06-06

- Removed legacy `profileCards` and `profileCount` from the config workspace API contract, keeping Model Library access through `modelOptions`.
- Hid the legacy Tools config editor section from the Config page so tool-specific configuration stays with Agent/tool management surfaces.
- Changed direct Agent session renaming to update the Agent Directory display name, while child-session renaming updates only the task title and leaves Agent identity unchanged.

## 0.10.32 - 2026-06-06

- Added lazy-loaded Memory Graph node details through `/api/memory/knowledge-graph/node-detail`, returning full formal knowledge bodies only for the selected node and within Team Knowledge ACL boundaries.
- Updated the Memory graph detail panel to fetch and render selected node knowledge content with loading and truncation states while keeping the main graph payload body-free.
- Added runtime-scene diagnostics for node-detail views without logging knowledge content.

## 0.10.32 - 2026-06-06

- Changed Launcher and runtime stop/restart requests to reject active project work with `409 active_work_*_blocked` instead of queuing or silently stopping chat, group, evolution, or worktree runs.
- Added blocked active-work lifecycle evidence for runtime and launcher stop/restart paths, preserving active task state for later diagnosis.
- Updated Launcher copy so active work is presented as a hard stop/restart guard, with legacy deferred restart queue text marked as historical diagnostics rather than an automatic action.

## 0.10.31 - 2026-06-06

- Added a Challenge Cup paper-note autodraft API that turns a completed local PDF `sourceExtraction` into a `paper_note_draft` local-model invocation.
- Reused the existing Local Research Worker Model and CandidateStore recording path, preserving source refs, page-anchor evidence refs, validation, and source-candidate draft trace metadata.
- Updated the Challenge Cup flow HTML and technical plan to mark the first source-extraction to paper-note bridge as landed while keeping long-document splitting pending.

## 0.10.30 - 2026-06-06

- Added the Challenge Cup source-extraction API for local PDF `source_manifest` candidates, computing `sha256`, extracting page anchors and excerpts, and writing traceable `metadata.sourceExtraction` evidence back to CandidateStore.
- Kept source extraction inside the candidate boundary: failed extraction leaves the source in `source_needs_confirmation`, and no formal Team Knowledge, RAG, or official graph writes happen.
- Added `pypdf` as the runtime PDF text extraction dependency and updated the Challenge Cup flow HTML and technical plan to mark local PDF page-anchor extraction as landed while keeping automatic `paper_note` generation pending.

## 0.10.29 - 2026-06-06

- Fixed OpenAI-compatible `tool_chat` protocol routing so Xiaomi MiMo and similar providers with `compat_mode = "openai"` resolve to `openai_chat_tools` instead of falling back to `basic_chat_no_tools`.
- Preserved Qwen thinking and local runtime special routes while adding regression coverage for Xiaomi `tool_chat` tool support.

## 0.10.28 - 2026-06-05

- Expanded `officialResearchGraph` into the read-only Memory Graph when requested, adding formal research reference nodes and `official_*` edges while preserving the default high-level graph.
- Updated the Memory page to request `include=officialResearchGraph`, so formal Challenge Cup research trace edges are visible in the graph canvas without exposing full knowledge bodies.
- Updated the Challenge Cup flow HTML and technical plan to mark Memory Graph canvas expansion as landed.

## 0.10.27 - 2026-06-05

- Added official Challenge Cup research graph trace syncing on steward-pack approval, storing `officialResearchGraph` on the formal KnowledgeItem and `officialSyncRecord`.
- Translated steward-pack `sourceTrace` and `candidateIds` into formal `supports`, `maps_to`, `inspires`, and `approved_for_ingestion` edges without promoting candidate graph drafts directly.
- Updated the Challenge Cup flow HTML and technical plan to mark M5 formal graph trace metadata as landed, leaving only Memory Graph canvas expansion for a later slice.

## 0.10.26 - 2026-06-05

- Migrated approved Challenge Cup steward-pack proposal rating suggestions into formal KnowledgeItem pending rating reviews without auto-applying the score.
- Recorded `ratingSuggestionMigration` in `officialSyncRecord` and `knowledgeIngestion` metadata so approval, skipped, and failed migration outcomes are traceable.
- Updated the Challenge Cup flow HTML and technical plan to mark M5 rating suggestion migration as landed while keeping fine-grained formal graph edges for later.

## 0.10.25 - 2026-06-05

- Added the Challenge Cup steward-pack ingestion approval gate API, approving pending steward packs into formal Team Knowledge or rejecting them back to revision.
- Recorded `officialSyncRecord` evidence on steward candidates, including proposal, batch, KnowledgeItem, reviewer, RAG, and graph status boundaries.
- Updated the Challenge Cup flow HTML and technical plan to mark M5 approval-gate behavior as landed while leaving rating migration and fine-grained graph edges for later.

## 0.10.24 - 2026-06-05

- Fixed Agent Center runtime status so current direct-session cards ignore stale run snapshots from old direct sessions, while preserving those runs as historical diagnostics.
- Surfaced unresolved Agent dialogue model references as blocking health issues and showed the raw model ID in Agent Center instead of a misleading `-`.
- Kept Agent reset replacement direct sessions synchronized back to AgentDirectory so Agent Center and the Chat/Coding session list stay aligned.
- Added the Challenge Cup steward-pack knowledge-ingestion API, submitting valid `steward_pack_draft` candidates to Team Knowledge as a `SourceArtifact` plus pending `RefinementProposal`, with optional pending rating suggestion.
- Moved submitted steward packs into `steward_pending_knowledge_review` while keeping official `KnowledgeItem`, RAG, and graph writes blocked until the approval gate.
- Updated the Challenge Cup research-flow HTML and technical plan to show the M5 pending-review bridge and remaining official-sync work.

## 0.10.23 - 2026-06-05

- Added the Challenge Cup `steward_pack_draft` CandidateStore gate for knowledge-governance ingestion drafts, requiring traceable candidate IDs, target domain, source trace, proposal payload, rating suggestion, risk summary, and `approvalRequired=true`.
- Blocked ingestion drafts that try to write official Team Knowledge, RAG, or graph state before the approval gate.
- Updated the Challenge Cup research-flow HTML and technical plan to show M5 steward pack behavior and remaining official-ingestion work.
- Fixed Chat/Coding session deletion so deleting an Agent direct session clears the Agent's `directSessionId` instead of creating a replacement direct session that makes the conversation appear restored.
- Kept the Agent active in Agent Center after its direct conversation is deleted, while removing the deleted session from the chat index.
- Changed last-session deletion fallback to create a plain empty "新会话" conversation without Agent binding.

## 0.10.22 - 2026-06-05

- Added a unified Model Library test control: choose one saved model and run a text connection test from that single button.
- Extended `/api/config/test-llm` to accept `modelId`, using the selected model library entry and its unique key binding through a temporary probe profile.
- Kept per-row Model Library actions focused on edit, image capability check, and delete, with model test diagnostics now logging the tested model ID.

## 0.10.21 - 2026-06-05

- Fixed Agent Center debug reset pending state so only the Agent being reset shows "resetting", while other Agent detail views remain usable.
- Added Agent reset requested/failed runtime-scene diagnostics at the API boundary, complementing the existing completed event so reset crashes and validation failures are traceable.
- Restored resetToolPolicy behavior for work-session Agents to the session default tool package instead of an empty default policy.

## 0.10.20 - 2026-06-04

- Surfaced live Chat/Coding model status while streamed LLM calls retry, fail, or fall back to non-streaming invoke, so the assistant output area no longer appears idle during retry backoff or fallback work.
- Added safe `llm:status` breadcrumbs with session/turn context and lifecycle logging for retry, fallback-started, fallback-succeeded, and failed states.
- Preserved fallback non-streaming assistant replies in the live session stream when the final result is otherwise only a control marker.
- Added the Anthropic thinking request contract for Claude Opus 4.7 via ATPify, including `thinking_type` / `thinking_display` model fields, payload injection, and safe runtime-scene diagnostics for requested and observed reasoning.

## 0.10.19 - 2026-06-04

- Added `conversation_log_inspect_tool`, a read-only JSONL conversation log inspector that summarizes candidate logs, event counts, LLM/token usage, tool-call sequences, errors, repeated calls, and large-result inefficiency signals without shell execution or raw full-log expansion.
- Added the new log inspector to the built-in tool registry and the 会话 Agent 基础包, with safe fixed-argument registry testing.
- Changed work-session Agent defaults so new and repaired chat/session Agents receive a private read-only session tool policy that includes `conversation_log_inspect_tool`; Agent Center work-session creation now lets the backend default policy apply instead of requiring a manual tool package.

## 0.10.18 - 2026-06-04

- Reduced Chat/Coding background polling while a direct session SSE stream is connected, pausing session, conversation, and team index polling until the stream disconnects or the user switches surfaces.
- Added low-noise `session.detail_snapshot.published` runtime-scene telemetry for active SSE subscribers, including snapshot publish latency, subscriber count, delivery/drop counts, message count, and current phase.
- Updated focused backend and ChatCodingRoute layout tests for the stream-backed polling and telemetry contract.

## 0.10.17 - 2026-06-04

- Clarified Chat/Coding context indicators so session message history estimates and runtime context compression estimates are displayed as separate scopes.
- Added `source`, `scope`, `tokenBasis`, and `limitBasis` metadata to runtime `contextCompression` payloads so the UI can explain why compression percentages differ from session history usage.
- Expanded Chat/Coding provider-failure notices with safe user-facing reason summaries such as quota exhaustion, deprecated sampling parameters, authentication failure, context limit, timeout, and upstream gateway failure.
- Updated Chat/Coding layout tests and runtime summary tests for the new context-scope contract.

## 0.10.16 - 2026-06-04

- Rebuilt `code_symbol_tool` as the native project code context graph tool, replacing the old Python-only outline/entity/definition/hover contract with status/index/search/explore/inspect/references/impact/affected_tests/files modes.
- Added a local cache-backed project index for code, frontend, docs, config, and workspace prompt assets while excluding runtime-history noise.
- Updated agent guidance, tool metadata, reading strategy, runtime observations, and focused tests for the new graph-based code navigation contract.

## 0.10.15 - 2026-06-04

- Added per-turn `llmUsage` to chat session details, sourced from provider usage metadata only.
- Changed Chat/Coding status display so "本轮真实输入" shows provider-observed input tokens, while missing provider usage is shown as unavailable instead of estimated.
- Kept session history context as a separate estimate and added runtime-scene events for recorded versus missing LLM usage.

## 0.10.14 - 2026-06-04

- Increased Launcher route information density by replacing repeated lifecycle cards with a compact lifecycle matrix.
- Consolidated control-plane evidence, recent command results, recent events, and guardian responsibilities into tighter console tables.
- Fixed narrow viewport Launcher layout so panels keep natural height and no longer visually overlap.

## 0.10.13 - 2026-06-04

- Changed the desktop launch chain so Start Menu / desktop entry opens the Launcher control surface first instead of directly starting the full workbench lifecycle.
- Added a `launcher_control_surface` session role so runtime and launcher status distinguish Launcher-only backend/control UI from a started project bundle.
- Hardened launcher stale-state cleanup by ignoring tracked backend PIDs whose command line no longer matches a launcher-managed backend.

## 0.10.12 - 2026-06-04

- Restored provider-agnostic LLM reasoning capture for OpenAI-compatible/local providers by centralizing reasoning field aliases and explicit `<think>` / `<thinking>` tag extraction.
- Kept hidden reasoning out of visible assistant content, including streamed think tags split across chunks.
- Added runtime-scene reasoning diagnostics with source and character-count summaries for invoke, stream, and stream fallback paths.

## 0.7.5 - 2026-06-01

- Added `/api/memory/usage-contract` as the cross-system contract for how Agent private memory, Team knowledge, Team chat, self evolution, supervised evolution, and external artifacts use the memory platform.
- Visualized the usage contract in `/agents/memory/knowledge`, including system domains, allowed read/write paths, prompt defaults, current contract state, and forbidden actions.
- Locked the evolution boundary in tests: evolution evidence may register sources and proposals, but it cannot directly create formal Team knowledge without reviewer confirmation.
- Logged contract reads through `memory.usage_contract.viewed`.

## 0.7.4 - 2026-06-01

- Added knowledge operations health APIs, Agent tools, and UI panels that surface orphan sources, pending proposals, pending rating suggestions, and unrated formal items without mutating knowledge.
- Added read-only governance plan APIs, Agent tools, and Memory Library visualization with explicit `planOnly` boundaries and recommended next tools.
- Added `exact` / `semantic` / `hybrid` knowledge search mode support with lightweight local token-overlap scoring and visible match reasons.
- Logged health and governance plan reads through `knowledge.operations.health.viewed`, `knowledge.governance.plan.viewed`, `knowledge.tool.operations_health.queried`, and `knowledge.tool.governance_plan.queried`.

## 0.7.3 - 2026-06-01

- Added the Knowledge Steward workbench API at `/api/knowledge/steward/workbench`, aggregating steward identity, open governance tasks, read-only recommendations, staged next actions, and acceptance checklist evidence.
- Added ToolPolicy-gated `knowledge_steward_workbench_tool` for the protected Knowledge Steward Agent so Agents can inspect the unified governance workflow without applying, deleting, changing ACLs, or bypassing reviewers.
- Visualized the steward workbench in `/agents/memory/knowledge`, including governance stages, next actions, and the review-safe acceptance checklist.
- Logged workbench reads through `knowledge.steward.workbench.viewed` and tool reads through `knowledge.tool.steward_workbench.queried`.

## 0.7.2 - 2026-06-01

- Allowed `terminal_bench_core` to run through the Vibelution custom harness as a non-official Terminal-Bench evaluation, while keeping Harbor/Docker official verifier status pending.
- Marked dataset, bundle, case, decision, proposal, API, and UI payloads with `evaluation_mode=custom_harness`, `official_verifier_status=harbor_pending`, `official_score=null`, and a Vibelution custom score label.
- Kept explicit official-mode launches blocked until the Harbor/Docker `/app` sandbox and official verifier are wired in.
- Logged custom-harness Terminal-Bench starts through `supervised_run.preflight.custom_harness_non_official` for later diagnosis.

## 0.7.1 - 2026-06-01

- Tightened supervised evolution real-run selection so `terminal_bench_core` is marked as requiring the official Harbor/Docker Terminal-Bench `/app` sandbox and verifier, hidden from the primary picker, and blocked during start/retry preflight.
- Kept `terminal_bench_smoke` as the currently runnable multi-step ReAct harness option for closed-loop validation while official Terminal-Bench runner integration remains pending.
- Preserved harness evidence for failed or cancelled supervised runs before temporary worktrees are removed, including conversation/debug logs, payloads, and runtime-scene lifecycle traces.
- Fixed supervised evolution request payload roles so user task input is sent as provider `user` content instead of drifting into a system message.
- Clarified supervised retry control flow by separating the local retry implementation from the runtime-manager wrapper and covering official-environment retry blocking with tests.

## 0.7.0 - 2026-05-31

- Added Memory Platform P1 for team knowledge bases: JSON/JSONL persistence for knowledge bases, source artifacts, refinement proposals, batches, formal items, and audit records under each team workspace.
- Added knowledge APIs for accessible overview, team knowledge-base creation/listing, source registration, proposal submission, review/apply, item listing, and rating updates with team role/ACL enforcement.
- Extended Agent memory policy with readable/proposable/reviewable knowledge-base boundaries and exposed those controls in Agent Center.
- Added ToolPolicy-gated Agent tools `knowledge_query_tool` and `knowledge_proposal_tool` so Agents can read reviewed team knowledge or submit source-backed candidates without directly writing formal knowledge.
- Integrated Team Knowledge into `/agents/memory/knowledge` with source registration, refinement proposal review, formal item inspection, and rating controls while keeping formal knowledge tool-readable and out of prompt by default.

## 0.6.2 - 2026-05-31

- Tightened Agent Center management around setup tasks: added per-Agent management readiness, next-action guidance, task-oriented filters for missing persona/task/tools/team/inbox/maintenance gaps, effective tool capability previews, and a dedicated maintenance intro for reset/archive/purge actions.
- Reduced Agent detail top-level tabs from Overview / Base config / Policies / Membership / Activity to Overview / Config / Activity, with tool, memory, and membership controls progressively disclosed inside Config.
- Reduced overlap between Tools and Agent Center: Tools now stays focused on tool catalog, scope visibility, runtime testing, and lightweight Agent test-boundary summaries, while Agent Center remains the configuration source for Agent ToolPolicy and tool package editing.

## 0.6.1 - 2026-05-31

- Fixed supervised worktree merge analysis so untracked files that already existed before candidate creation, such as local `.codex/visual-checks` artifacts, are kept as baseline noise instead of counted as candidate changes or merge overlaps.
- Kept true candidate edits visible in `candidateWorktree.changedFiles`, allowing the Terminal-Bench smoke closed loop to finish with a clean `mergeAnalysis.ready` result when only the candidate marker changes.

## 0.6.0 - 2026-05-31

- Added a local Terminal-Bench-style supervised dataset adapter with two multi-step terminal/ReAct smoke cases that materialize into `terminal_bench_smoke_v1`.
- Added `multi_step_react` as a supervised harness mode alias that preserves benchmark metadata while launching through the existing single-turn prompt runner.
- Hid empty, missing-source, and external-harness datasets from the supervised workbench's primary dataset picker while keeping their status visible through API metadata.
- Merged the supervised launch dataset/bundle controls into one evaluation-source picker with compact source counts and inline terminology guidance.
- Exposed dataset `visibility`, `selectable`, and `noiseLevel` fields from the evolution workbench API for cleaner benchmark selection.

## 0.5.3 - 2026-05-31

- Added Agent Center tool package presets for fast ToolPolicy setup, including core, research, coding, collaboration, memory/context, media, and operations bundles.
- Exposed `toolBundles` from `/api/tools` with tool counts, preferred-tool counts, high-risk counts, explicit-allow counts, and risk tags.
- Added compact Agent Center controls to merge a tool package into the current draft or reset the draft exactly to that package while keeping manual per-tool allow/block editing.
- Persisted `preferredTools` from the Agent Center tool-policy editor so package priorities are not lost on save.

## 0.5.2 - 2026-05-30

- Added configuration-stage image input capability checks for model library entries and profile-derived models through `/api/config/draft/check-model-capabilities`.
- Persist image input capability metadata including `supports_image_input`, `capability_status`, `capability_source`, `capability_checked_at`, and `capability_error`.
- Added model-center actions to check one model or all models for image input support and display the resulting capability status.
- Marked DeepSeek V4 Pro/Flash presets as unsupported for image input, kept Xiaomi MiMo V2.5 multimodal as supported, and made the profile/model-center badges use conservative `supports_image_input` evidence.
- Moved Agent binding edits out of the Config page: LLM config now keeps read-only Agent usage summaries and links to Agent management instead of duplicating Agent bindings, prompt/session/workspace edits, and mode slot/pool assignment controls.
- Restored recent image attachments for contextual retry messages such as “你再试试” when the active task is image comparison or prompt refinement.

## 0.5.1 - 2026-05-30

- Added AgentDirectory-backed `taskProfile` fields for mission, task types, responsibilities, preferred and avoided tasks, success criteria, deliverables, constraints, and handoff notes.
- Added Agent Center editing for task profiles and exposed the profile through `/api/agents` plus `/api/agents/config-workspace`.
- Injected non-empty task profiles into Agent runtime context as descriptive task-fit guidance without automatic recommendation, routing, permission, or scheduling behavior.
- Logged task profile updates through `agent.task_profile.updated` and covered API/context/UI contracts with focused tests.

## 0.5.0 - 2026-05-30

- Added AgentDirectory-backed `personaProfile` fields for gender, age, pronouns, personality, communication style, background, expertise, collaboration preference, and identity notes.
- Added Agent Center editing for persona profiles and exposed the profile through `/api/agents` plus `/api/agents/config-workspace`.
- Injected non-empty persona profiles into Agent runtime context as descriptive collaboration guidance, while explicitly keeping age/gender out of capability or permission logic.
- Logged persona profile updates through `agent.persona_profile.updated` and covered API/context/UI contracts with focused tests.

## 0.4.33 - 2026-05-29

- Added one-shot route chunk recovery for stale lazy-loaded assets after a frontend rebuild, preventing the default React Router error screen when a managed window still holds an older entry bundle.
- Covered dynamic import fetch failure detection and reload loop prevention with focused frontend tests.

## 0.4.32 - 2026-05-29

- Renamed the top-level Research navigation entry to Team and mounted the Team workspace at `/teams`.
- Kept `/research` and `/agents/teams` as compatibility redirects to `/teams`, preserving selected team query links.
- Moved Team out of the Agent management subnavigation while keeping Agent Center as the member binding source.

## 0.4.31 - 2026-05-29

- Added Agent Center avatar editing from the detail avatar: upload a new PNG/JPG/WebP, choose an existing `workspace/avatars` image, or restore the Agent role default.
- Added Agent avatar management APIs under `/api/agents/{agent_id}/avatar`, `/api/agents/{agent_id}/avatar-image`, and `/api/agents/avatar-options`.
- Logged avatar updates/uploads through AgentDirectory runtime-scene events while preserving text-avatar fallback behavior.

## 0.4.30 - 2026-05-29

- Added AgentDirectory-backed default avatars sourced from `workspace/avatars`, exposed through `/api/agents/avatar-image/{filename}` and `avatarImageUrl` fields.
- Render Agent avatars in Agent Center and Chat/Coding Agent reference surfaces while keeping text-initial fallbacks for missing images.
- Persisted default avatar assignments for existing Agents and logged `agent.avatar_defaults_assigned` during directory repair.

## 0.4.29 - 2026-05-29

- Tightened Research Flow Canvas communication-edge routing so dense bidirectional team organization edges stay close to their Agent nodes instead of expanding into large overlapping arcs.
- Added a focused ResearchFlowCanvas geometry regression for the three-Agent research team layout with six communication lines.
- Render Chat/Coding generated-image Markdown as real inline image previews, links, and compact tables instead of exposing raw `![...](...)` syntax after image2 tool calls.
- Suppress stale interrupted-turn runtime notices after a real follow-up message arrives, and show at most one active runtime notice in the Chat/Coding status strip.

## 0.4.28 - 2026-05-29

- Tightened `list_sessions()` into a read-only lightweight index path: session list loading no longer creates missing session workspaces, materializes legacy Agents, or hydrates each Agent through full detail serialization.
- Kept AgentDirectory-only direct sessions visible in the list through compact Agent state, while moving legacy chat-state repair to detail/interaction paths such as `get_session_detail`.
- Added `session.list.loaded` runtime-scene timing metadata so future diagnostics can verify the lightweight read path.
- Moved interrupted-turn recovery notices out of Agent assistant replies and into `runtimeNotices`, rendered as a separate Chat/Coding status strip while filtering legacy notice messages from the conversation timeline.

## 0.4.27 - 2026-05-29

- Sped up Agent Center configuration workspace loading by switching team and group-room references to compact read paths that avoid session scans, participant repair, linked-room hydration, and canvas reads during the first aggregate load.
- Added `loadModes` timing metadata to `agent_config.workspace.loaded` so future runtime-scene logs show when compact workspace reads are active.

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
