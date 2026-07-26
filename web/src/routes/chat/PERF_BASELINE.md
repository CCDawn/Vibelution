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
| F4 | Trigger-only — no Config/Memory feature PR this round |

### Post-F3 Agents chunk note

Default Agents route chunk reduced by moving config/activity/relations/changes panes into async chunks. Overview stays eager.
