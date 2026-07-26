# Chat / Frontend perf baseline (F0)

Recorded for high-ROI program **scope A** (F0–F3, F5, F6; F4 trigger-only).

## Build chunks (approx raw kB, prior production build)

| Chunk | ~kB | Notes |
|---|---:|---|
| three.module | 706 | Memory graph only; dynamic import |
| AgentsRoute | 357 | Largest business route |
| CliAgentRunTerminalPanel | 346 | Chat CLI; already React.lazy |
| ChatCodingRoute | 336 | Chat shell |
| ConversationView | 196 | Separate feature chunk |
| ConversationMarkdownRenderer | 154 | Already via LazyConversationMarkdownRenderer |
| useAppI18n (historical) | ~87 | Shell uses useShellI18n + shellDictionary |

## F0 findings (code)

### Already good

- `CliAgentRunTerminalPanel` lazy from `ChatCodingRoute`
- Markdown via `LazyConversationMarkdownRenderer` (Suspense + plain fallback)
- Shell / Launcher use `useShellI18n` only (layout contracts lock this)
- Core chat live policy: stop session/list/detail poll only after EventSource **onopen**
- Group room detail poll stops when `groupStreamConnected`

### Gaps (actionable)

| Gap | Severity | Owner phase |
|---|---|---|
| `expandedGroupAgentDetailQueries` poll **3s even when group SSE open** | High | F2 |
| `projectAgentBusQuery` always 3s while bus active (no stream) | Medium — keep unless bus SSE exists | F2 review |
| `runtimeQuery` 5s / `petQuery` 10s while secondary chat data enabled | Low — secondary chrome | optional |
| Chat route **full** preload on pointerenter/focus (pulls ChatCodingRoute graph) | Medium | F1 soft idle |
| Agents: ~19 inline mutations, no pane packs | High structure/bundle | F3 |

### Preload triggers today

- `pointerenter` / `focus` / `click` → `import("../routes/ChatCodingRoute")`
- Soft intent should not compete with first paint; hard intent on click stays immediate.

## Target after program

1. Group expanded-agent polls honor `groupStreamConnected`. ✅ (F2)
2. Chat preload: soft (idle) on hover/focus, hard on click. ✅ (F1)
3. Agents: mutation hooks + pane-scoped lazy packs; default overview lighter. (F3 — staged; see `agents/README.md`)
4. i18n: keep shell light; no regression of AppShell dictionary boundary. ✅ already (F5 verify)

## Shipped

| Item | Change |
|---|---|
| F0 | This baseline file |
| F1 | `AppShell` soft idle preload + hard click |
| F2 | `expandedGroupAgentDetailQueries` stop poll when group SSE open |
| F3-A | Agents mutations → hooks (0 inline `useMutation` on AgentsRoute) |
| F3-B | Agent secondary panes React.lazy; AgentsRoute raw ~357→~261 kB gzip ~85→~66 |
| F3-C | Activity poll gates already correct |
| F5 | Verified: AppShell/Launcher use `useShellI18n` only (existing contracts) |
| F4 / R1–R4 | Chat secondary poll; Config pane lazy; Evolution poll gate; Memory item mutations + graph lazy |
| S1–S3 | Memory view-level panel lazy; Chat status/group/file tabs lazy; Memory knowledge mutations extract |
| T1–T3 | ConversationView prefetch + dialog lazy; Chat file/tool dialog lazy; Evolution mutation hooks |
| T4 | Launcher secondary panels React.lazy; i18n shell boundary re-locked (useShellI18n only) |
| U1 | Agents `AgentCreateWizardDialog` lazy (open-only mount) → separate ~52 kB pack |
| U2 | `governanceStatusLabel` → `agentStatusPresentation` (shell no longer static-imports governance panel) |
| U3 | Evolution supervised panels lazy: active-run / run-records / proposal-action-bands |

### Post-U1–U3 chunk notes

| Chunk | ~kB raw | Notes |
|---|---:|---|
| AgentsRoute | **~257** (was ~261) | U1 wizard out of eager graph; gzip ~64 |
| AgentCreateWizardDialog | ~52 | Shared create surface; open-only on Agents |
| EvolutionRoute | **~143** (was ~183) | U3 panels async; gzip ~35 |
| EvolutionActiveRunMonitorPanel | ~15 | live view pack |
| EvolutionRunRecordsPanel | ~23 | runs view pack |
| EvolutionProposalActionBandsPanel | ~3 | library action pack |

### Post-T1–T3 chunk notes (build evidence)

| Chunk | ~kB raw | Notes |
|---|---:|---|
| ChatCodingRoute | ~264 | Surface lazy (S2) + T2 file/tool dialogs out of shell graph when unused |
| ConversationView | ~192–196 | Still large transcript path; ImagePreview / AgentContext are separate chunks |
| ConversationImagePreviewDialog | ~4 | T1 dialog pack |
| AgentContextSectionsView | ~5 | T1 context pack |
| ChatFilePreviewPanel / ChatToolApprovalDialog | ~1 / ~3 | T2 session workspace packs |
| EvolutionRoute | ~183 | Inline mutations → hooks (T3); route still owns layout/query |
| useAppI18n | ~89 | Route-level full dictionary chunk; shell must stay on `useShellI18n` (T4/F5) |
| LauncherRoute | **~80** (was ~122) | T4: shell −~42 kB raw; panels ~9–12 kB each |
| LauncherStartup / Maintenance / Developer / Diagnostics | ~11 / ~9 / ~12 / ~11 | T4 lazy packs |

Prefetch: `prefetchConversationView` after `activeSessionId` via idle callback (does not mount).

Deferred (not T4): domain-splitting `dictionary.ts` / `useAppI18n` by route — high churn, measure before any cut.

### Post-F3 Agents chunk note

Default Agents route chunk reduced by moving config/activity/relations/changes panes into async chunks. Overview stays eager.
