# Config Health Diagnostics Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the Config page Health Diagnostics display cluster from `ConfigRoute.tsx` into a route-local `ConfigHealthDiagnosticsPanel` without changing user-visible behavior.

**Architecture:** `ConfigRoute.tsx` remains the owner of TanStack Query state, language/copy selection, Config editing state, and refresh callback wiring. `ConfigHealthDiagnosticsPanel.tsx` owns only display markup, display-only helpers, VUI controls, links, and existing `ConfigRoute.styles` class consumption. Architecture tests explicitly allow this route-local panel to share its parent route style map.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, TanStack Query, Tailwind 4 explicit route style maps, existing VUI primitives.

## Global Constraints

- Do not modify `TeamsRoute.*`, `components/vui/product/team-management/**`, or `AgentsRoute.*`; active project-memory claims currently own those surfaces.
- Do not change Config save/apply behavior, model discovery/test behavior, avatar/background upload flows, crop flows, sidebar resize behavior, unsaved-change leave guard behavior, or health diagnostics API contracts.
- The user-visible Config Health Diagnostics area must stay visually and behaviorally unchanged.
- `ConfigRoute.tsx` must keep `healthDiagnosticsQuery` ownership and pass data/loading/refetch into the panel.
- `ConfigHealthDiagnosticsPanel.tsx` may import `./ConfigRoute.styles` because it is a route-local surface subcomponent.
- Quick actions and helpers with `resetItemId` must keep routing to `/launcher`, not `/reset`.
- Use `node node_modules/typescript/bin/tsc -b --noEmit`; do not use bare `npx tsc`.
- Do not commit unless the execution context explicitly authorizes a commit.

---

## File Structure

- Create: `web/src/routes/ConfigHealthDiagnosticsPanel.tsx`
  - Owns `ConfigHealthDiagnosticsPanel` and health diagnostic card/link subcomponents.
  - Owns display-only helpers currently used only by the health diagnostics cluster: `healthStatusLabel`, `healthStatusClassName`, `healthSeverityClassName`, `formatFindingId`, `formatTimestamp`, and `formatBytes`.
  - Imports `HealthDiagnostics`, `HealthFinding`, `HealthQuickAction`, `LogHelper`, and `SessionHelper` types from `../api/types`.
  - Imports `VButton` from `../components/vui`.
  - Imports `ExternalLink`, `RefreshCw` from `lucide-react`.
  - Imports `styles` from `./ConfigRoute.styles`.

- Modify: `web/src/routes/ConfigRoute.tsx`
  - Remove the health diagnostics display-only helper functions and display components after extracting them.
  - Import `ConfigHealthDiagnosticsPanel` and its copy/language types.
  - Keep `healthDiagnosticsQuery` and the `onRefresh` callback.
  - Replace `<LogHelperCenter ... />` with `<ConfigHealthDiagnosticsPanel ... />`.

- Modify: `web/src/routes/ConfigRoute.layout.test.ts`
  - Add source import for the new panel.
  - Assert the route renders `<ConfigHealthDiagnosticsPanel`.
  - Assert the route no longer owns inline health diagnostics display functions.
  - Assert the panel preserves Launcher routing and avoids Reset routing for health maintenance links.

- Modify: `web/src/components/vui/vuiImportBoundary.test.ts`
  - Add `routes/ConfigHealthDiagnosticsPanel.tsx` to `productSharedParentStyleConsumers`.

---

### Task 1: Add extraction and routing contract tests

**Files:**
- Modify: `web/src/routes/ConfigRoute.layout.test.ts`
- Modify: `web/src/components/vui/vuiImportBoundary.test.ts`

**Interfaces:**
- Consumes: existing raw imports in `ConfigRoute.layout.test.ts`:
  - `routeSource` from `./ConfigRoute.tsx?raw`
  - `stylesSource` from `./ConfigRoute.styles.ts?raw`
- Produces: failing tests that require:
  - new file `web/src/routes/ConfigHealthDiagnosticsPanel.tsx`
  - `<ConfigHealthDiagnosticsPanel ... />` usage in `ConfigRoute.tsx`
  - allowlist entry in `vuiImportBoundary.test.ts`

- [ ] **Step 1: Import the new panel source in `ConfigRoute.layout.test.ts`**

At the top of `web/src/routes/ConfigRoute.layout.test.ts`, change the imports from:

```ts
import routeSource from "./ConfigRoute.tsx?raw";
import stylesSource from "./ConfigRoute.styles.ts?raw";
```

to:

```ts
import routeSource from "./ConfigRoute.tsx?raw";
import stylesSource from "./ConfigRoute.styles.ts?raw";
import healthDiagnosticsPanelSource from "./ConfigHealthDiagnosticsPanel.tsx?raw";
```

- [ ] **Step 2: Add the health diagnostics extraction test**

Append this test inside the existing `describe("ConfigRoute layout contract", () => { ... })` block in `web/src/routes/ConfigRoute.layout.test.ts`, after the existing health/diagnostic routing test or before the final VUI primitives test:

```ts
  it("moves health diagnostics display into a route-local panel while keeping ConfigRoute as query owner", () => {
    expect(routeSource).toContain('import { ConfigHealthDiagnosticsPanel');
    expect(routeSource).toContain('from "./ConfigHealthDiagnosticsPanel"');
    expect(routeSource).toContain("<ConfigHealthDiagnosticsPanel");
    expect(routeSource).toContain("diagnostics={healthDiagnosticsQuery.data}");
    expect(routeSource).toContain("loading={healthDiagnosticsQuery.isLoading || healthDiagnosticsQuery.isFetching}");
    expect(routeSource).toContain("void healthDiagnosticsQuery.refetch();");

    expect(routeSource).not.toContain("function LogHelperCenter");
    expect(routeSource).not.toContain("function HealthFindingCard");
    expect(routeSource).not.toContain("function HealthQuickActionLink");
    expect(routeSource).not.toContain("function SessionHelperCard");
    expect(routeSource).not.toContain("function LogHelperCard");

    expect(healthDiagnosticsPanelSource).toContain("export function ConfigHealthDiagnosticsPanel");
    expect(healthDiagnosticsPanelSource).toContain("function HealthFindingCard");
    expect(healthDiagnosticsPanelSource).toContain("function HealthQuickActionLink");
    expect(healthDiagnosticsPanelSource).toContain("function SessionHelperCard");
    expect(healthDiagnosticsPanelSource).toContain("function LogHelperCard");
  });
```

- [ ] **Step 3: Add the Launcher maintenance routing test**

Append this test inside the same `describe` block in `web/src/routes/ConfigRoute.layout.test.ts`:

```ts
  it("keeps health diagnostics cleanup and reset hints routed to Launcher maintenance", () => {
    expect(healthDiagnosticsPanelSource).toContain("healthOpenLauncher");
    expect(healthDiagnosticsPanelSource).toContain('href="/launcher"');
    expect(healthDiagnosticsPanelSource).toContain("action.resetItemId ? \"/launcher\"");
    expect(healthDiagnosticsPanelSource).not.toContain("`/reset?item=");
    expect(healthDiagnosticsPanelSource).not.toContain("href={`/reset?item=");
    expect(routeSource).not.toContain("`/reset?item=");
    expect(routeSource).not.toContain("href={`/reset?item=");
  });
```

- [ ] **Step 4: Add the new route-local panel to the VUI parent-style allowlist**

In `web/src/components/vui/vuiImportBoundary.test.ts`, add this string to `productSharedParentStyleConsumers`, keeping the list sorted near other Config/route panel entries if practical:

```ts
  "routes/ConfigHealthDiagnosticsPanel.tsx",
```

- [ ] **Step 5: Run the focused tests and verify the expected failure**

Run:

```bash
cd web
node_modules/.bin/vitest run src/routes/ConfigRoute.layout.test.ts src/components/vui/vuiImportBoundary.test.ts --run
```

Expected: FAIL because `./ConfigHealthDiagnosticsPanel.tsx?raw` does not exist yet, or because `ConfigRoute.tsx` still renders `<LogHelperCenter ... />` and still owns the inline functions.

---

### Task 2: Extract the ConfigHealthDiagnosticsPanel component

**Files:**
- Create: `web/src/routes/ConfigHealthDiagnosticsPanel.tsx`
- Modify: `web/src/routes/ConfigRoute.tsx`
- Test: `web/src/routes/ConfigRoute.layout.test.ts`
- Test: `web/src/components/vui/vuiImportBoundary.test.ts`

**Interfaces:**
- Consumes from Task 1:
  - tests requiring `ConfigHealthDiagnosticsPanel.tsx`
  - VUI parent-style allowlist entry
- Produces:
  - `export type ConfigLanguage = "zh" | "en";`
  - `export type ConfigHealthDiagnosticsPanelCopy = { ... }`
  - `export function ConfigHealthDiagnosticsPanel(props: ConfigHealthDiagnosticsPanelProps): JSX.Element`
  - `ConfigRoute.tsx` import and render call

- [ ] **Step 1: Create `ConfigHealthDiagnosticsPanel.tsx` imports and exported types**

Create `web/src/routes/ConfigHealthDiagnosticsPanel.tsx` with this top section:

```ts
import { ExternalLink, RefreshCw } from "lucide-react";

import type { HealthDiagnostics, HealthFinding, HealthQuickAction, LogHelper, SessionHelper } from "../api/types";
import { VButton } from "../components/vui";
import styles from "./ConfigRoute.styles";

export type ConfigLanguage = "zh" | "en";

export type ConfigHealthDiagnosticsPanelCopy = {
  healthTitle: string;
  healthBody: string;
  healthLoading: string;
  healthEmpty: string;
  healthRefresh: string;
  healthPriority: string;
  healthQuickActions: string;
  healthEvidence: string;
  healthRecommended: string;
  healthRelatedFindings: string;
  healthNoFindings: string;
  healthOpenLogs: string;
  healthOpenChat: string;
  healthOpenLauncher: string;
  healthOpen: string;
  healthFiles: string;
  healthDirs: string;
  healthSessions: string;
  healthBusy: string;
  healthFailed: string;
  healthStale: string;
  healthPhase: string;
  healthLatest: string;
  healthUpdated: string;
  healthSize: string;
  healthProtected: string;
  healthMaintenanceAvailable: string;
  healthStatusOk: string;
  healthStatusWarning: string;
  healthStatusBlocked: string;
  healthMissing: string;
  healthNotRecorded: string;
};

type ConfigHealthDiagnosticsPanelProps = {
  diagnostics: HealthDiagnostics | undefined;
  loading: boolean;
  lang: ConfigLanguage;
  copy: ConfigHealthDiagnosticsPanelCopy;
  onRefresh: () => void;
};
```

- [ ] **Step 2: Move display helper functions into the new panel file**

Below the props type in `ConfigHealthDiagnosticsPanel.tsx`, add these helpers. They are the display-only helpers formerly in `ConfigRoute.tsx`:

```ts
function formatBytes(size: number) {
  if (!Number.isFinite(size) || size <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatTimestamp(value: string, lang: ConfigLanguage, emptyLabel: string) {
  const text = String(value || "").trim();
  if (!text) {
    return emptyLabel;
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

function healthStatusLabel(status: string, copy: ConfigHealthDiagnosticsPanelCopy) {
  if (status === "ok") {
    return copy.healthStatusOk;
  }
  if (status === "blocked" || status === "error") {
    return copy.healthStatusBlocked;
  }
  return copy.healthStatusWarning;
}

function healthStatusClassName(status: string) {
  if (status === "ok") {
    return `${styles.inlineBadge} ${styles.inlineBadgeSuccess}`;
  }
  if (status === "blocked" || status === "error") {
    return `${styles.inlineBadge} ${styles.healthBadgeBlocked}`;
  }
  return `${styles.inlineBadge} ${styles.inlineBadgeWarning}`;
}

function healthSeverityClassName(severity: string) {
  if (severity === "error" || severity === "blocked") {
    return `${styles.inlineBadge} ${styles.healthBadgeBlocked}`;
  }
  if (severity === "warning") {
    return `${styles.inlineBadge} ${styles.inlineBadgeWarning}`;
  }
  return styles.inlineBadge;
}

function formatFindingId(id: string) {
  return id ? `#${id.replace(/_/g, "-")}` : "";
}
```

- [ ] **Step 3: Add the exported panel component**

Below the helpers, add the main component. This is the old `LogHelperCenter` with the exported name and prop type:

```tsx
export function ConfigHealthDiagnosticsPanel({
  diagnostics,
  loading,
  lang,
  copy,
  onRefresh,
}: ConfigHealthDiagnosticsPanelProps) {
  const sessionHelpers = diagnostics?.sessionHelpers ?? [];
  const helpers = diagnostics?.logHelpers ?? [];
  const findings = diagnostics?.findings ?? [];
  const priorityFindings = findings.filter((finding) => finding.severity !== "info").slice(0, 4);
  const quickActions = diagnostics?.quickActions ?? [];
  return (
    <section id="config-health-diagnostics" className={styles.sectionSurface}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionHeaderMain}>
          <p className={styles.eyebrow}>{copy.healthTitle}</p>
          <h2 className={styles.sectionTitle}>{copy.healthTitle}</h2>
          <p className={styles.sectionText}>{copy.healthBody}</p>
        </div>
        <div className={styles.sectionHeaderActions}>
          {diagnostics ? (
            <span className={healthStatusClassName(diagnostics.status)}>
              {healthStatusLabel(diagnostics.status, copy)}
            </span>
          ) : null}
          <VButton type="button" className={styles.actionButton} onClick={onRefresh} isDisabled={loading}>
            <RefreshCw size={14} />
            {copy.healthRefresh}
          </VButton>
        </div>
      </div>
      {loading && !diagnostics ? <p className={styles.helperText}>{copy.healthLoading}</p> : null}
      {diagnostics ? (
        <div className={styles.healthSummaryGrid}>
          <article className={styles.matrixCard}>
            <p className={styles.matrixTitle}>{copy.healthStatusOk}</p>
            <strong className={styles.healthMetric}>{diagnostics.counts.ok}</strong>
          </article>
          <article className={styles.matrixCard}>
            <p className={styles.matrixTitle}>{copy.healthStatusWarning}</p>
            <strong className={styles.healthMetric}>{diagnostics.counts.warning}</strong>
          </article>
          <article className={styles.matrixCard}>
            <p className={styles.matrixTitle}>{copy.healthStatusBlocked}</p>
            <strong className={styles.healthMetric}>{diagnostics.counts.blocked}</strong>
          </article>
        </div>
      ) : null}
      {diagnostics?.summary ? <p className={styles.sectionText}>{diagnostics.summary}</p> : null}
      {diagnostics ? (
        <div className={styles.healthWorkbenchGrid}>
          <div className={styles.healthPanel}>
            <div className={styles.healthPanelHeader}>
              <h3>{copy.healthPriority}</h3>
              <span className={styles.inlineBadge}>{priorityFindings.length.toLocaleString()}</span>
            </div>
            {priorityFindings.length ? (
              <div className={styles.findingList}>
                {priorityFindings.map((finding) => (
                  <HealthFindingCard key={finding.id} finding={finding} copy={copy} />
                ))}
              </div>
            ) : (
              <p className={styles.helperText}>{copy.healthNoFindings}</p>
            )}
          </div>
          <div className={styles.healthPanel}>
            <div className={styles.healthPanelHeader}>
              <h3>{copy.healthQuickActions}</h3>
              <span className={styles.inlineBadge}>{quickActions.length.toLocaleString()}</span>
            </div>
            {quickActions.length ? (
              <div className={styles.quickActionList}>
                {quickActions.map((action) => (
                  <HealthQuickActionLink key={action.id} action={action} copy={copy} />
                ))}
              </div>
            ) : (
              <p className={styles.helperText}>{copy.healthNoFindings}</p>
            )}
          </div>
        </div>
      ) : null}
      {sessionHelpers.length ? (
        <div className={styles.logHelperGrid}>
          {sessionHelpers.map((helper) => (
            <SessionHelperCard key={helper.id} helper={helper} lang={lang} copy={copy} />
          ))}
        </div>
      ) : null}
      {helpers.length ? (
        <div className={styles.logHelperGrid}>
          {helpers.map((helper) => (
            <LogHelperCard key={helper.id} helper={helper} lang={lang} copy={copy} />
          ))}
        </div>
      ) : !loading ? (
        <p className={styles.helperText}>{copy.healthEmpty}</p>
      ) : null}
    </section>
  );
}
```

- [ ] **Step 4: Add the extracted card/link components**

Below `ConfigHealthDiagnosticsPanel`, add these components. Copy the existing JSX from `ConfigRoute.tsx` exactly, with only the copy type name updated:

```tsx
function HealthFindingCard({ finding, copy }: { finding: HealthFinding; copy: ConfigHealthDiagnosticsPanelCopy }) {
  return (
    <article className={styles.findingCard}>
      <div className={styles.findingHeader}>
        <div>
          <p className={styles.matrixTitle}>{formatFindingId(finding.id)}</p>
          <h4>{finding.title}</h4>
        </div>
        <span className={healthSeverityClassName(finding.severity)}>
          {healthStatusLabel(finding.severity, copy)}
        </span>
      </div>
      <p className={styles.cardSubtle}>{finding.summary}</p>
      {finding.evidence.length ? (
        <div className={styles.findingEvidence} aria-label={copy.healthEvidence}>
          {finding.evidence.slice(0, 4).map((item) => (
            <span key={`${finding.id}-${item.label}`}>
              <strong>{item.label}</strong>
              {item.value}
            </span>
          ))}
        </div>
      ) : null}
      {finding.recommendedAction ? (
        <p className={styles.findingRecommendation}>
          <strong>{copy.healthRecommended}</strong>
          {finding.recommendedAction}
        </p>
      ) : null}
      <div className={styles.actionsRow}>
        <a className={styles.actionButton} href={finding.route || "/logs"}>
          <ExternalLink size={14} />
          {copy.healthOpen}
        </a>
        {finding.resetItemId ? (
          <a className={styles.actionButton} href="/launcher" target="_blank" rel="noreferrer">
            <ExternalLink size={14} />
            {copy.healthOpenLauncher}
          </a>
        ) : null}
      </div>
    </article>
  );
}

function HealthQuickActionLink({ action, copy }: { action: HealthQuickAction; copy: ConfigHealthDiagnosticsPanelCopy }) {
  const href = action.resetItemId ? "/launcher" : action.route || "/logs";
  return (
    <a className={styles.quickActionItem} href={href}>
      <div>
        <span className={healthSeverityClassName(action.severity)}>
          {action.findingId ? formatFindingId(action.findingId) : action.source}
        </span>
        <strong>{action.title}</strong>
        <small>{action.description}</small>
      </div>
      <ExternalLink size={15} />
    </a>
  );
}

function SessionHelperCard({ helper, lang, copy }: { helper: SessionHelper; lang: ConfigLanguage; copy: ConfigHealthDiagnosticsPanelCopy }) {
  const updatedLabel = formatTimestamp(helper.updatedAt, lang, copy.healthNotRecorded);
  return (
    <article className={styles.logHelperCard}>
      <div className={styles.logHelperHeader}>
        <div>
          <p className={styles.matrixTitle}>{helper.activeSessionId || helper.id}</p>
          <h3 className={styles.cardTitle}>{helper.title}</h3>
        </div>
        <span className={healthStatusClassName(helper.status)}>
          {helper.statusLabel || healthStatusLabel(helper.status, copy)}
        </span>
      </div>
      <p className={styles.cardSubtle}>{helper.description}</p>
      <div className={styles.logHelperMetaGrid}>
        <span>
          <strong>{helper.sessionCount.toLocaleString()}</strong>
          {copy.healthSessions}
        </span>
        <span>
          <strong>{helper.busyCount.toLocaleString()}</strong>
          {copy.healthBusy}
        </span>
        <span>
          <strong>{helper.failedCount.toLocaleString()}</strong>
          {copy.healthFailed}
        </span>
        <span>
          <strong>{helper.staleCount.toLocaleString()}</strong>
          {copy.healthStale}
        </span>
        <span title={helper.updatedAt}>
          <strong>{updatedLabel}</strong>
          {copy.healthUpdated}
        </span>
      </div>
      <div className={styles.logHelperSignal}>
        <span>{copy.healthLatest}</span>
        <strong>{helper.latestSignal || helper.activeTitle || copy.healthMissing}</strong>
      </div>
      <div className={styles.logHelperSignal}>
        <span>{copy.healthPhase}</span>
        <strong>{helper.currentPhase || copy.healthNotRecorded}</strong>
      </div>
      <p className={styles.cardSubtle}>{helper.recommendedAction}</p>
      <div className={styles.cardBadges}>
        <span className={`${styles.inlineBadge} ${styles.inlineBadgeWarning}`}>{copy.healthProtected}</span>
        {helper.findingIds?.length ? (
          <span className={styles.inlineBadge}>
            {copy.healthRelatedFindings} {helper.findingIds.length}
          </span>
        ) : null}
      </div>
      {helper.protectedReason ? <p className={styles.helperText}>{helper.protectedReason}</p> : null}
      <div className={styles.actionsRow}>
        <a className={styles.actionButton} href={helper.route || "/chat"}>
          <ExternalLink size={14} />
          {copy.healthOpenChat}
        </a>
      </div>
    </article>
  );
}

function LogHelperCard({ helper, lang, copy }: { helper: LogHelper; lang: ConfigLanguage; copy: ConfigHealthDiagnosticsPanelCopy }) {
  const updatedLabel = formatTimestamp(helper.lastModifiedAt, lang, copy.healthNotRecorded);
  const latestSignal = helper.latestSignal || helper.latestPath || copy.healthMissing;
  return (
    <article className={styles.logHelperCard}>
      <div className={styles.logHelperHeader}>
        <div>
          <p className={styles.matrixTitle}>{helper.rootPath}</p>
          <h3 className={styles.cardTitle}>{helper.title}</h3>
        </div>
        <span className={healthStatusClassName(helper.status)}>
          {helper.statusLabel || healthStatusLabel(helper.status, copy)}
        </span>
      </div>
      <p className={styles.cardSubtle}>{helper.description}</p>
      <div className={styles.logHelperMetaGrid}>
        <span>
          <strong>{helper.fileCount.toLocaleString()}</strong>
          {copy.healthFiles}
        </span>
        <span>
          <strong>{helper.directoryCount.toLocaleString()}</strong>
          {copy.healthDirs}
        </span>
        <span>
          <strong>{formatBytes(helper.sizeBytes)}</strong>
          {copy.healthSize}
        </span>
        <span title={helper.lastModifiedAt}>
          <strong>{updatedLabel}</strong>
          {copy.healthUpdated}
        </span>
      </div>
      <div className={styles.logHelperSignal}>
        <span>{copy.healthLatest}</span>
        <strong>{latestSignal}</strong>
      </div>
      <p className={styles.cardSubtle}>{helper.recommendedAction}</p>
      <div className={styles.cardBadges}>
        <span className={helper.protected ? `${styles.inlineBadge} ${styles.inlineBadgeWarning}` : styles.inlineBadge}>
          {helper.protected ? copy.healthProtected : copy.healthMaintenanceAvailable}
        </span>
        {helper.findingIds?.length ? (
          <span className={styles.inlineBadge}>
            {copy.healthRelatedFindings} {helper.findingIds.length}
          </span>
        ) : null}
      </div>
      {helper.protectedReason ? <p className={styles.helperText}>{helper.protectedReason}</p> : null}
      <div className={styles.actionsRow}>
        <a className={styles.actionButton} href={helper.route || "/logs"}>
          <ExternalLink size={14} />
          {copy.healthOpenLogs}
        </a>
        {helper.resetItemId ? (
          <a className={styles.actionButton} href="/launcher" target="_blank" rel="noreferrer">
            <ExternalLink size={14} />
            {copy.healthOpenLauncher}
          </a>
        ) : null}
      </div>
    </article>
  );
}
```

- [ ] **Step 5: Update `ConfigRoute.tsx` imports**

In `web/src/routes/ConfigRoute.tsx`, remove these type imports from `../api/types` because they move to the new panel file:

```ts
  HealthDiagnostics,
  HealthFinding,
  HealthQuickAction,
  LogHelper,
  SessionHelper,
```

Change the VUI import from:

```ts
import { VButton, VNativeInput, VNativeSelect, VNativeTextarea } from "../components/vui";
```

only if `VButton` is still used elsewhere in `ConfigRoute.tsx`. If it is still used, keep it unchanged. If TypeScript reports `VButton` unused after the extraction, change it to:

```ts
import { VNativeInput, VNativeSelect, VNativeTextarea } from "../components/vui";
```

Add this import near the other route-local imports:

```ts
import { ConfigHealthDiagnosticsPanel, type ConfigHealthDiagnosticsPanelCopy, type ConfigLanguage } from "./ConfigHealthDiagnosticsPanel";
```

Then remove the local declarations currently in `ConfigRoute.tsx`:

```ts
type ConfigLanguage = "zh" | "en";
```

and change the copy type from:

```ts
type LogHelperCopy = {
  ...
};
```

to:

```ts
type LogHelperCopy = ConfigHealthDiagnosticsPanelCopy;
```

- [ ] **Step 6: Remove extracted helpers and components from `ConfigRoute.tsx`**

Delete these functions from `web/src/routes/ConfigRoute.tsx` after confirming they now exist in `ConfigHealthDiagnosticsPanel.tsx`:

```ts
function healthStatusLabel(status: string, copy: LogHelperCopy) { ... }
function healthStatusClassName(status: string) { ... }
function healthSeverityClassName(severity: string) { ... }
function formatFindingId(id: string) { ... }
function LogHelperCenter(...) { ... }
function HealthFindingCard(...) { ... }
function HealthQuickActionLink(...) { ... }
function SessionHelperCard(...) { ... }
function LogHelperCard(...) { ... }
```

Also remove these two helpers only if TypeScript confirms no other `ConfigRoute.tsx` code references them:

```ts
function formatBytes(size: number) { ... }
function formatTimestamp(value: string, lang: ConfigLanguage, emptyLabel: string) { ... }
```

- [ ] **Step 7: Replace the render call in `ConfigRoute.tsx`**

Replace the current block:

```tsx
        {isSectionVisible("health-diagnostics") ? (
          <LogHelperCenter
            diagnostics={healthDiagnosticsQuery.data}
            loading={healthDiagnosticsQuery.isLoading || healthDiagnosticsQuery.isFetching}
            lang={currentLanguage}
            copy={copy}
            onRefresh={() => {
              void healthDiagnosticsQuery.refetch();
            }}
          />
        ) : null}
```

with:

```tsx
        {isSectionVisible("health-diagnostics") ? (
          <ConfigHealthDiagnosticsPanel
            diagnostics={healthDiagnosticsQuery.data}
            loading={healthDiagnosticsQuery.isLoading || healthDiagnosticsQuery.isFetching}
            lang={currentLanguage}
            copy={copy}
            onRefresh={() => {
              void healthDiagnosticsQuery.refetch();
            }}
          />
        ) : null}
```

- [ ] **Step 8: Run focused tests and TypeScript**

Run:

```bash
cd web
node_modules/.bin/vitest run src/routes/ConfigRoute.layout.test.ts src/components/vui/vuiImportBoundary.test.ts --run
node node_modules/typescript/bin/tsc -b --noEmit
```

Expected: both commands PASS. If TypeScript reports unused imports in `ConfigRoute.tsx`, remove the exact unused imports and re-run the same commands.

---

### Task 3: Run migration verification and update project memory

**Files:**
- Test: `web/src/components/vui/vuiBatchMigration.test.ts`
- Read/Update if execution made meaningful code changes: `.docs/project-memory/lanes/web-workbench-surface.json`
- Read/Update if execution made meaningful code changes: `.docs/project-memory/memory.json`
- Regenerate if memory updated: `.docs/project-memory/overview.html`, `.docs/project-memory/INDEX.md`, `PROJECT_MEMORY.html`

**Interfaces:**
- Consumes from Task 2:
  - extracted `ConfigHealthDiagnosticsPanel`
  - passing focused layout/boundary tests
- Produces:
  - completed verification evidence
  - fresh project memory entry for the web-workbench-surface lane if code changed

- [ ] **Step 1: Run the required VUI migration contract and build checks**

Run:

```bash
cd web
node_modules/.bin/vitest run src/routes/ConfigRoute.layout.test.ts src/components/vui/vuiImportBoundary.test.ts src/components/vui/vuiBatchMigration.test.ts --run
node node_modules/typescript/bin/tsc -b --noEmit
node_modules/.bin/vite build
```

Expected: all commands PASS. The build may still print existing bundle size warnings; treat warnings as non-blocking only if the exit code is 0.

- [ ] **Step 2: Optionally run the full Vitest suite when local time permits**

Run:

```bash
cd web
node_modules/.bin/vitest run
```

Expected: PASS. If this is skipped due to time, the completion report must explicitly say it was skipped.

- [ ] **Step 3: Check project-memory work claims before updating memory**

If Python is available in the execution shell, run:

```bash
python C:/Users/17533/.claude/skills/ccdawn-dawn-agent-html-memory/scripts/agent_work_guard.py C:/Users/17533/Desktop/Vibelution status
```

Expected: status output lists claims. Confirm no active claim owns `.docs/project-memory/**` before writing memory. If Python exits because it is unavailable in Git Bash, continue by reading `.docs/project-memory/agent-claims.json` and avoid overwriting active project-memory claim work.

- [ ] **Step 4: Update the web-workbench project memory lane if implementation changed code**

Read these files first:

```text
.docs/project-memory/memory.json
.docs/project-memory/profile.json
.docs/project-memory/lanes/web-workbench-surface.json
.docs/project-memory/inbox.json
```

Append one concise lane update in `.docs/project-memory/lanes/web-workbench-surface.json` describing:

```text
Extracted Config Health Diagnostics display cluster into ConfigHealthDiagnosticsPanel. ConfigRoute keeps health diagnostics query ownership and refresh callback; the new route-local panel owns diagnostics cards, links, Launcher maintenance routing, and parent ConfigRoute.styles consumption. Validation: ConfigRoute layout, VUI import boundary, VUI batch migration, tsc, and Vite build.
```

Append a matching concise item to the global `recentUpdates` array in `.docs/project-memory/memory.json` with lane id `web-workbench-surface` and lane title `Web Workbench Surface`.

- [ ] **Step 5: Regenerate project memory dashboard if memory was updated**

If memory files were updated and Python is available, run:

```bash
python C:/Users/17533/.claude/skills/ccdawn-dawn-agent-html-memory/scripts/render_overview.py C:/Users/17533/Desktop/Vibelution
```

Expected: exit code 0 and regenerated `.docs/project-memory/overview.html`, `.docs/project-memory/INDEX.md`, and `PROJECT_MEMORY.html` reflect the latest update. If Python is unavailable, report that memory content was updated but dashboard regeneration was blocked by Python availability.

- [ ] **Step 6: Report completion with evidence**

Report exactly:

```text
Changed files:
- web/src/routes/ConfigHealthDiagnosticsPanel.tsx
- web/src/routes/ConfigRoute.tsx
- web/src/routes/ConfigRoute.layout.test.ts
- web/src/components/vui/vuiImportBoundary.test.ts
- project memory files, if updated

Verification:
- ConfigRoute.layout + VUI boundary + VUI batch migration: PASS/FAIL
- tsc -b --noEmit: PASS/FAIL
- vite build: PASS/FAIL
- full vitest: PASS/FAIL/SKIPPED

Behavior boundary:
- ConfigRoute still owns healthDiagnosticsQuery and refetch callback.
- ConfigHealthDiagnosticsPanel owns only display markup and Launcher maintenance links.
- No TeamsRoute, team-management, or AgentsRoute files were touched.
```

Do not claim completion if any required verification command failed.
