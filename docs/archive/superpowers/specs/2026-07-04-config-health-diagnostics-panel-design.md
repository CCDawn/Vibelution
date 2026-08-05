# Config Health Diagnostics Panel Design

> Date: 2026-07-04
> Scope: `web/src/routes/ConfigRoute.tsx` health diagnostics display extraction
> Status: user-approved design section, pending written spec review

## 1. Goal

Continue the frontend Tailwind/VUI refactor with a low-conflict, low-risk ConfigRoute slice. The selected slice is the Health Diagnostics display area currently embedded in `ConfigRoute.tsx`.

The user-visible Config page must not change. This wave only moves display composition into a route-local subcomponent so `ConfigRoute.tsx` keeps state and behavior while a dedicated panel owns the health diagnostics DOM structure.

## 2. Context

Current repository state shows:

- `createVuiStyleMap` is no longer present; route styles are explicit Tailwind class maps.
- No `web/src/**/*.module.css` files remain.
- Active project-memory claims exist for Teams layout polish and Agents debug reset work, so this wave avoids `TeamsRoute.*`, `components/vui/product/team-management/**`, and `AgentsRoute.*`.
- `ConfigRoute.tsx` is still large and contains a cohesive read-only health diagnostics display cluster:
  - `LogHelperCenter`
  - `HealthFindingCard`
  - `HealthQuickActionLink`
  - `SessionHelperCard`
  - `LogHelperCard`

## 3. Architecture

Add a route-local subcomponent:

```text
ConfigRoute.tsx
  ├─ owns healthDiagnosticsQuery, refetch callback, language, copy, Config state machines
  └─ renders <ConfigHealthDiagnosticsPanel ... />

ConfigHealthDiagnosticsPanel.tsx
  ├─ owns health diagnostics markup, cards, links, badges, empty/loading display
  └─ imports ./ConfigRoute.styles and VUI primitives
```

The new file will live at:

```text
web/src/routes/ConfigHealthDiagnosticsPanel.tsx
```

This follows the existing route-local panel pattern used by Memory and Agent route extractions.

## 4. Component API

The panel props are deliberately narrow:

```ts
export type ConfigHealthDiagnosticsPanelCopy = LogHelperCopy;

type ConfigHealthDiagnosticsPanelProps = {
  diagnostics: HealthDiagnostics | undefined;
  loading: boolean;
  lang: ConfigLanguage;
  copy: ConfigHealthDiagnosticsPanelCopy;
  onRefresh: () => void;
};
```

`ConfigRoute.tsx` passes:

- `diagnostics={healthDiagnosticsQuery.data}`
- `loading={healthDiagnosticsQuery.isLoading || healthDiagnosticsQuery.isFetching}`
- `lang={lang}`
- `copy={copy}`
- `onRefresh={() => { void healthDiagnosticsQuery.refetch(); }}`

The panel must not import query keys, query client, or Config mutation helpers.

## 5. Data Flow

`ConfigRoute.tsx` remains the data owner:

```text
healthDiagnosticsQuery
  → diagnostics/loading/refetch callback
ConfigHealthDiagnosticsPanel
  → derives display-only collections:
      priorityFindings = findings.filter(...).slice(0, 4)
      quickActions = diagnostics?.quickActions ?? []
      sessionHelpers = diagnostics?.sessionHelpers ?? []
      logHelpers = diagnostics?.logHelpers ?? []
```

The panel is a display adapter only. It does not change API data shape, query ownership, or Config page state.

## 6. Helper Function Ownership

Move these display-only helpers with the panel:

- `healthStatusLabel`
- `healthStatusClassName`
- `healthSeverityClassName`
- `formatFindingId`
- `formatTimestamp`
- `formatBytes`

Keep unrelated ConfigRoute helpers in `ConfigRoute.tsx`, including:

- sidebar width/height storage and clamp helpers
- config draft/model editor helpers
- upload/crop helpers
- leave guard helpers
- query invalidation logic

## 7. Styling

The new panel imports the existing route style map:

```ts
import styles from "./ConfigRoute.styles";
```

This is intentional for this wave. The component is route-local and not a reusable product component yet. The VUI architecture boundary test already permits known route subcomponents to share parent route styles, so the new file must be added to that allowlist.

This wave does not create `components/vui/product/config-management/` and does not move Config styles into a new style system.

## 8. Behavior Contract

The Config Health Diagnostics area must behave the same after extraction:

- Loading with no diagnostics renders the existing loading helper text.
- Existing diagnostics render status, summary counts, summary text, priority findings, quick actions, session helpers, and log helpers.
- No helpers while not loading renders the existing empty helper text.
- Finding links still fall back to `/logs` when no route is provided.
- Quick actions with `resetItemId` still route to `/launcher`; they must not route to `/reset`.
- Log helpers with `resetItemId` still include a Launcher maintenance link.
- Session helpers still fall back to `/chat`.
- Timestamp formatting keeps the current locale behavior and fallback behavior.

## 9. Explicit Non-Goals

This wave does not change:

- Config save/apply behavior
- model discovery or model test behavior
- avatar upload, background upload, or crop flows
- sidebar resize behavior
- unsaved-change leave guard behavior
- health diagnostics API contracts
- Teams or Agents files with active project-memory claims

## 10. Review Perspectives

- Core user: Config page still looks and behaves the same.
- Maintainer: `ConfigRoute.tsx` loses a cohesive display cluster and becomes easier to navigate.
- QA/test: Existing layout and architecture contracts can prove the extraction without needing backend data.
- Operations/support: Cleanup/reset-related health entries still direct users to Launcher maintenance, preserving the current operational boundary.

## 11. Test Plan

Run these validations after implementation:

```bash
cd web
node node_modules/typescript/bin/tsc -b --noEmit
node_modules/.bin/vitest run src/routes/ConfigRoute.layout.test.ts src/components/vui/vuiImportBoundary.test.ts src/components/vui/vuiBatchMigration.test.ts
node_modules/.bin/vite build
```

If time and environment permit, also run:

```bash
node_modules/.bin/vitest run
```

Update tests to assert:

- `ConfigRoute.tsx` renders `<ConfigHealthDiagnosticsPanel`.
- `ConfigRoute.tsx` no longer contains the inline display functions moved to the panel.
- `ConfigHealthDiagnosticsPanel.tsx` keeps Launcher routing for reset/maintenance entries.
- `ConfigHealthDiagnosticsPanel.tsx` is listed in the VUI import boundary allowlist for parent style sharing.

## 12. Completion Report

After implementation, report:

- Changed files.
- Which functions moved out of `ConfigRoute.tsx`.
- Which validation commands passed or failed.
- Whether project memory was updated.
