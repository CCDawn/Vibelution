# Frontend Componentization Migration Playbook

> Scope: long-running Vibelution frontend route componentization, style ownership, and VUI visual grammar convergence.
> Status: active execution playbook.
> Primary audience: future Agents continuing frontend refactors in `C:\Users\17533\Desktop\Vibelution`.

## 1. Purpose

This playbook is the default operating plan for future frontend refactoring rounds that target routes or panels that are not yet fully componentized.

It exists to prevent repeated small manual rounds. Future Agents should not rediscover the migration shape from scratch, stop after one tiny extraction, or mix unrelated behavior work into a componentization pass. A migration round should select a coherent batch, apply the same template, run the same checks, and leave clear evidence.

The goal is not to make every page generic. For ordinary componentization batches, the default is to keep route files as data/state/action owners while moving repeated display composition, local DOM clusters, reusable panel grammar, and local style ownership into dedicated components. A dedicated architecture spec may move a cohesive vertical slice under typed owners when it defines staged gates and preserves behavior explicitly.

## 2. Authority And Relationship To Other Docs

Use this playbook after reading:

- `AGENTS.md`
- `DEVELOPMENT_STANDARD.md`
- `.docs/project-memory/INDEX.md`
- `.docs/project-memory/memory.json`
- `.docs/project-memory/profile.json`
- `.docs/project-memory/agent-registry.json`

Related frontend design sources:

- `docs/superpowers/specs/2026-06-26-frontend-style-system-design.md`
- `docs/superpowers/specs/2026-06-29-vui-foundation-heroui-renderer-plan.md`
- `docs/superpowers/specs/2026-07-02-vui-productization-plan.md`
- `docs/superpowers/specs/2026-07-04-frontend-heroui-vui-aesthetic-unification-design.md`

When these docs disagree, use this order for frontend refactoring:

1. `AGENTS.md` and `DEVELOPMENT_STANDARD.md` for workspace, git, claim, memory, and safety rules.
2. Current project memory and active claims for ownership and conflict avoidance.
3. This playbook for componentization batch shape, execution template, and validation contract.
4. Visual/aesthetic specs for surface language and design intent.

Do not edit `DEVELOPMENT_STANDARD.md`, `AGENTS.md`, `.docs/project-memory/**`, or generated project-memory HTML as part of a normal componentization batch. If this playbook needs promotion into a formal standard, run a separate governance/documentation round after checking active documentation claims.

## 3. Current Baseline

As of 2026-07-05 after the source collection residual ownership wave:

- CSS module migration is no longer the primary remaining task. `web/src` has no normal `.module.css` route migration surface in the active scan.
- Route-level direct `@heroui/react` imports are not the active blocker; HeroUI is expected to stay behind `web/src/components/vui/**`.
- Static inline `style={{ ... }}` in production TSX is not the active blocker in the scanned frontend source.
- Parent route style ownership has mostly been split for prior child panels in Agents, Memory, Teams, Launcher, Config, ChatCoding conversation children, and related route-local panels.
- Teams source collection residual ownership has been narrowed: `TeamsRoute.styles.ts` keeps the page/grid/run-badge/step-state shell, while child panels and VUI product components own panel frames, focused panel layout, active-stage result layout, graph node list shell, result filter/pagination controls, result rows, and candidate list shells.
- The remaining work is concentrated in large route files, large route style maps, repeated visual grammar, and product-level behavior backlogs that must be scheduled separately.

> 2026-07-13 architecture note: the helper-only Teams source collection recommendation in Q3 and section 18 is superseded by [Teams source collection vertical split](2026-07-13-teams-source-collection-vertical-split-design.md). That dedicated design is a behavior-preserving architecture refactor, not a normal visual/componentization batch, and may move query/controller ownership under its stricter staged gates. All other guidance in this playbook remains active.

Largest route/componentization hotspots observed:

| Surface | Approximate line count | Primary remaining concern |
| --- | ---: | --- |
| `web/src/routes/TeamsRoute.tsx` | 12500+ | Route still carries many research workflow clusters and candidate/action compositions. |
| `web/src/routes/ChatCodingRoute.tsx` | 8000+ | Chat, session index, preview, cache detail, composer, live status, and terminal orchestration remain dense. |
| `web/src/routes/AgentsRoute.tsx` | 5800+ | Many panels were extracted, but route still owns broad view-model assembly and workspace composition. |
| `web/src/routes/EvolutionRoute.tsx` | 4600+ | Supervised/self-evolution workbench composition remains broad and visually dense. |
| `web/src/routes/MemoryRoute.tsx` | 4300+ | Many panels were extracted, but memory management and knowledge surfaces still carry repeated chrome. |
| `web/src/routes/ConfigRoute.tsx` | 3800+ | Config display clusters were partially extracted; deeper action surfaces and schema editor composition remain. |

Known non-componentization backlog that must remain separate:

| Backlog | Why separate |
| --- | --- |
| Chat/Coding token-level or stage-level SSE/live transport | Changes backend/session streaming behavior and cache reconciliation. |
| Reset and Config deeper action surfaces | Changes destructive/config behavior and requires source-of-truth validation. |
| CodeMirror/FilePreview chunk optimization | Changes bundling and preview dependency strategy. |
| User Markdown Space memory integration | Active separate claim can overlap Memory route and API types. |

## 4. Intent Lock

Future componentization rounds should preserve this intent:

- User-visible behavior remains unchanged unless a batch explicitly says it is a visual-only convergence pass.
- In ordinary componentization batches, route files keep ownership of query state, mutations, cache reconciliation, navigation, URL state, permission decisions, and backend DTO assembly. A dedicated approved architecture spec may move a cohesive subset under typed controllers while preserving the same external semantics.
- Extracted components own DOM composition, local display helpers, local VUI composition, local style maps, and local empty/loading/error rendering for their cluster.
- Common visual grammar moves upward into VUI/product compositions when reuse or consistency improves.
- Batch size should be large enough to remove a coherent cluster or class of offenders in one pass.
- Each batch ends with evidence, not a chat-only claim.

Non-goals for normal componentization batches:

- No backend API redesign.
- No behavior semantics change.
- No route state-machine rewrite.
- No broad copy rewrite.
- No package migration.
- No version bump.
- No GitHub push or PR unless the user explicitly authorizes it.

## 5. Target Architecture

Use this default ownership model for componentization batches unless a dedicated architecture spec explicitly supersedes it:

```text
Route
  owns: query/mutation/cache/url/nav/draft state/view-model assembly
  passes: normalized props, callbacks, labels, status, derived items

Route-local panel
  owns: DOM composition for one route-owned surface cluster
  owns: cluster-specific display helpers and local empty/loading/error branches
  may use: local .styles.ts and VUI primitives
  must not own: backend writes, query keys, cache invalidation, global routing contracts

Product component
  owns: reusable Vibelution workflow grammar across routes
  may use: VUI primitives, product-specific props, local style map
  must not import: parent Route.styles

VUI primitive/composition
  owns: generic visual grammar for controls, panels, rows, chips, toolbars, state rows
  may wrap: HeroUI renderer
  must keep: HeroUI hidden from routes
```

Component extraction should usually converge to:

```text
web/src/routes/<ClusterName>Panel.tsx
web/src/routes/<ClusterName>Panel.styles.ts
web/src/routes/<RouteName>.layout.test.ts
```

Reusable product/VUI convergence should usually converge to:

```text
web/src/components/vui/<domain or composition>/<ComponentName>.tsx
web/src/components/vui/<domain or composition>/index.ts
web/src/components/vui/<contract>.test.tsx
```

## 6. Batch Size Rules

Do not stop after a cosmetic one-line move when a coherent batch is visible.

A normal batch should complete at least one of these units:

- One complete route cluster, including component file, style file, route wiring, and layout tests.
- One repeated visual grammar class across 2-4 files, such as header chrome, metric chips, panel wrappers, or button-panel hybrids.
- One large route composition band, such as a detail workspace, active-run panel, candidate preview, source collection overview, run settings section, or cache diagnostics section.
- One VUI composition primitive plus adoption in at least one affected route cluster.

Minimum useful batch evidence:

- At least one route file gets smaller or a repeated style grammar class is eliminated.
- Tests are updated to lock the new ownership boundary.
- A route style-owner scan or VUI boundary scan proves the old ownership path did not remain active.

Allowed small batch exceptions:

- A blocker prevents a larger batch and is documented.
- Active claims make the larger surface unsafe.
- The batch creates a reusable migration tool/test that unlocks larger follow-up batches.
- The user explicitly asks for a narrow isolated change.

## 7. Standard Migration Algorithm

Every future migration batch should follow this sequence.

### 7.1 Intake And Conflict Check

Run from root:

```powershell
git status --short --branch
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" status
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" check --lane web-workbench-surface --scope "<scope-1>" --scope "<scope-2>"
```

If the local script exposes `recommend` or `preflight`, use them. If it does not, `check` plus an explicit `claim` is the accepted local equivalent.

Do not continue if the target file is inside another active claim unless the user explicitly authorizes a forced claim and the conflict is documented.

### 7.2 Worktree Setup

Use a task worktree for normal frontend refactoring:

```powershell
git worktree add "C:\Users\17533\Desktop\Vibelution-worktrees\<task-slug>" -b codex/<task-slug> main
```

Then claim:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" claim --lane web-workbench-surface --scope "<scope-1>" --scope "<scope-2>" --agent "<agent-id>" --task "<task title>" --status active --ttl-minutes 240 --note "Branch codex/<task-slug>; worktree C:\Users\17533\Desktop\Vibelution-worktrees\<task-slug>"
```

If web dependencies are absent in the worktree, prefer a junction to the root `web/node_modules` only after verifying the source and target absolute paths. Remove only the junction during cleanup.

### 7.3 Baseline Scan

Run the smallest scan set that describes the target:

```powershell
Get-ChildItem -LiteralPath "web\src\routes" -Filter "*.tsx" |
  ForEach-Object {
    $lines = (Get-Content -LiteralPath $_.FullName | Measure-Object -Line).Lines
    [PSCustomObject]@{ Lines = $lines; Name = $_.Name }
  } |
  Sort-Object Lines -Descending |
  Select-Object -First 20 |
  Format-Table -AutoSize

Get-ChildItem -LiteralPath "web\src\routes" -Filter "*.styles.ts" |
  ForEach-Object {
    $lines = (Get-Content -LiteralPath $_.FullName | Measure-Object -Line).Lines
    [PSCustomObject]@{ Lines = $lines; Name = $_.Name }
  } |
  Sort-Object Lines -Descending |
  Select-Object -First 25 |
  Format-Table -AutoSize

rg -n "style=\{\{" "web/src" -g "*.tsx"
rg -n "@heroui/react" "web/src" -g "*.ts" -g "*.tsx"
rg --files "web/src" -g "*.module.css"
```

For route ownership:

```powershell
rg -n "<cluster token>|<style key>|<component name>" "web/src/routes/<RouteName>.tsx" "web/src/routes/<RouteName>.styles.ts" "web/src/routes/<RouteName>.layout.test.ts"
```

For visual convergence:

```powershell
rg -n "rounded-\[var\(--radius-panel\)\].*bg-\[var\(--vui-surface-glass\)\]|shadow-\[var\(--vui-shadow-hairline\)\]|bg-\[var\(--surface-page\)\]" "web/src/app" "web/src/routes" -g "*.styles.ts"
```

### 7.4 Batch Selection

Classify each candidate cluster:

| Signal | Meaning | Action |
| --- | --- | --- |
| Route contains cohesive JSX plus local helper functions | Good extraction target | Extract route-local panel. |
| Route computes query/mutation/cache state inside same block as DOM | Split view-model from DOM | In an ordinary batch, keep state in route and pass props; under a dedicated architecture spec, follow its staged ownership contract. |
| Child component imports parent `Route.styles` | Ownership leak | Move to local style map unless route-local exception is intentionally documented. |
| Style key name implies header/button/eyebrow but includes card chrome | Visual grammar conflict | Replace with VUI/product composition or layout-only class. |
| Same class string appears in multiple style maps | Reusable VUI/product grammar | Extract composition if adoption covers enough surfaces. |
| Target overlaps active claim | Conflict | Defer or narrow scope. |
| Requires backend/API/cache semantics change | Not componentization | Move to separate behavior batch. |

Select the largest safe batch that shares the same verification gate.

### 7.5 Write Tests First For Ownership

Add or update route layout tests before implementation when practical. A good ownership test asserts:

- Route imports and renders the new panel.
- The ownership asserted by the active componentization playbook or dedicated architecture spec remains unique and unchanged outside the declared migration boundary.
- Extracted panel owns specific DOM identifiers, labels, or local display helpers.
- Extracted panel imports its own local style map when it is not an intentional route-local exception.
- Route style map no longer owns moved style keys.
- VUI boundary allow-list does not grow unless the exception is intentional and short-lived.

Example pattern:

```ts
import routeSource from "./<RouteName>.tsx?raw";
import panelSource from "./<ClusterName>Panel.tsx?raw";
import routeStylesSource from "./<RouteName>.styles.ts?raw";
import panelStylesSource from "./<ClusterName>Panel.styles.ts?raw";

it("moves <cluster> display into <ClusterName>Panel while keeping <RouteName> as state owner", () => {
  expect(routeSource).toContain('from "./<ClusterName>Panel"');
  expect(routeSource).toContain("<ClusterName>Panel");
  expect(routeSource).toContain("<query or mutation owner token>");
  expect(panelSource).toContain("export function <ClusterName>Panel");
  expect(panelSource).toContain('from "./<ClusterName>Panel.styles"');
  expect(panelStylesSource).toContain("<movedStyleKey>");
  expect(routeStylesSource).not.toContain("<movedStyleKey>");
});
```

### 7.6 Extract Component

Use this component contract:

```ts
import type { ReactNode } from "react";

import styles from "./<ClusterName>Panel.styles";

export type <ClusterName>PanelStatus = "idle" | "loading" | "ready" | "error";

export type <ClusterName>PanelItem = {
  id: string;
  label: string;
  status?: <ClusterName>PanelStatus;
};

type <ClusterName>PanelProps = {
  lang: "zh" | "en";
  title: string;
  summary?: string;
  items: <ClusterName>PanelItem[];
  loading?: boolean;
  errorMessage?: string | null;
  actions?: ReactNode;
  onRefresh?: () => void;
};

export function <ClusterName>Panel({
  lang,
  title,
  summary,
  items,
  loading = false,
  errorMessage = null,
  actions,
  onRefresh,
}: <ClusterName>PanelProps) {
  return (
    <section className={styles.panel} aria-labelledby="<cluster-name>-title">
      {/* Display composition only. No query keys, cache invalidation, or backend writes. */}
    </section>
  );
}
```

Adjust props to the actual domain. Do not create generic props when domain-specific props make the ownership clearer.

Route code should prepare:

- stable arrays;
- computed labels;
- status class names or status tones;
- callbacks for mutation dispatch;
- empty/error strings;
- selected IDs;
- pending IDs;
- derived counts;
- view-model objects.

Panel code should not call:

- `useQuery`;
- `useMutation`;
- `queryClient.invalidateQueries`;
- route navigation helpers;
- backend API clients;
- project memory or filesystem helpers.

### 7.7 Move Styles

Use a local style map:

```ts
const styles = {
  panel: "min-w-0 ...",
  header: "min-w-0 ...",
  body: "min-w-0 ...",
} as const;

export default styles;
```

Rules:

- Use `as const`.
- Keep the route prefix only when existing display-contract tests require it.
- Remove moved keys from parent route style maps.
- If a child component must consume a parent style map, document why and add the narrowest allow-list entry.
- Avoid duplicated card chrome in `header`, `eyebrow`, `button`, `toolbar`, and `row` keys.
- Prefer VUI composition primitives when multiple surfaces need the same visual language.

### 7.8 Run Verification

Use the narrowest route tests first, then widen.

For route panel extraction:

```powershell
npm --prefix web run test -- src/routes/<RouteName>.layout.test.ts --run
npm --prefix web run test -- src/components/vui/vuiImportBoundary.test.ts src/components/vui/vuiBatchMigration.test.ts --run
npm --prefix web run build
git diff --check
rg -n "style=\{\{" "web/src" -g "*.tsx"
```

For a route that has logic tests:

```powershell
npm --prefix web run test -- src/routes/<RouteName>.logic.test.ts --run
```

For visual grammar convergence:

```powershell
npm --prefix web run test -- src/routes/routeAestheticContract.test.ts --run
npm --prefix web run test -- src/app/AppShell.layout.test.ts src/routes/ChatCodingRoute.layout.test.ts src/routes/MemoryRoute.layout.test.ts src/routes/RouteStyleDisplayContract.test.ts --run
npm --prefix web run build
```

For direct route HeroUI and CSS module boundary:

```powershell
rg -n "@heroui/react" "web/src/routes" -g "*.ts" -g "*.tsx"
rg --files "web/src" -g "*.module.css"
```

Expected boundary:

- `@heroui/react` appears only under VUI renderer/primitive layers or VUI tests.
- `.module.css` scan returns no active route migration target unless a new file was intentionally introduced and documented.
- `style={{` scan returns no production TSX matches.

If a verification fails, classify it:

| Failure type | Response |
| --- | --- |
| Implementation mismatch | Fix inside current batch and rerun exact failing command. |
| Test still asserting retired structure | Update test if it protects stale structure; keep product invariant. |
| Active-claim conflict | Stop and report conflict. |
| Behavior expectation changed | Stop and return to BRT. |
| Environment/dependency failure | Verify path/process state, then retry once with a bounded fix. |

### 7.9 Self Review And Completion

Before commit or merge, self-review:

```powershell
git status --short --branch
git diff -- <current-task-files>
git diff --check
```

Completion report for each batch must include:

- claim id;
- branch;
- worktree path;
- changed files;
- route/component ownership change;
- verification commands and results;
- logging decision;
- test decision;
- architecture/test alignment decision;
- launcher refresh decision;
- version impact;
- project memory sync status or exact reason for skipping.

## 8. Canonical Batch Templates

Use these templates directly. Replace bracketed fields with concrete values before executing.

### 8.1 Route Panel Extraction Batch

```markdown
## Batch: [Route] [Cluster] Panel Extraction

Intent:
- Keep [Route] as owner of [queries/mutations/cache/url/drafts].
- Move [cluster DOM/display helpers/local empty-error-loading rendering] into [Panel].
- No user-visible behavior change.

Files:
- Create: web/src/routes/[Panel].tsx
- Create: web/src/routes/[Panel].styles.ts
- Modify: web/src/routes/[Route].tsx
- Modify: web/src/routes/[Route].styles.ts
- Modify: web/src/routes/[Route].layout.test.ts
- Modify only if needed: web/src/components/vui/vuiImportBoundary.test.ts

Guard:
- Active claim check passed for all listed files.
- No target file belongs to another active claim.

Route keeps:
- [query owner]
- [mutation owner]
- [cache invalidation owner]
- [URL/navigation owner]
- [draft or selected state owner]

Panel owns:
- [DOM id or aria region]
- [display helper]
- [empty state]
- [loading state]
- [error state]
- [local style keys]

Verification:
- npm --prefix web run test -- src/routes/[Route].layout.test.ts --run
- npm --prefix web run test -- src/components/vui/vuiImportBoundary.test.ts src/components/vui/vuiBatchMigration.test.ts --run
- npm --prefix web run build
- git diff --check
- rg -n "style=\{\{" "web/src" -g "*.tsx"
```

### 8.2 Visual Grammar Batch

```markdown
## Batch: [Surface Set] Visual Grammar Convergence

Intent:
- Remove repeated/conflicting route-local visual grammar for [header/panel/button/chip/row].
- Keep route state and product behavior unchanged.
- Move reusable grammar to [VUI composition or product component] when reuse covers multiple surfaces.

Files:
- Modify: [style files]
- Create or modify: [VUI composition file]
- Modify: [contract/layout tests]

Offenders removed:
- [file:key]
- [file:key]

Verification:
- npm --prefix web run test -- src/routes/routeAestheticContract.test.ts --run
- npm --prefix web run test -- [affected layout tests] --run
- npm --prefix web run test -- src/components/vui/vuiImportBoundary.test.ts src/components/vui/vuiBatchMigration.test.ts --run
- npm --prefix web run build
- git diff --check
```

### 8.3 Route Composition Band Batch

```markdown
## Batch: [Route] Composition Band Consolidation

Intent:
- Move [band name] from route-level JSX into [BandPanel].
- Route passes a single [bandProps] view-model object plus callbacks.
- Keep sibling bands unchanged.

Files:
- Create: web/src/routes/[BandPanel].tsx
- Create: web/src/routes/[BandPanel].styles.ts
- Modify: web/src/routes/[Route].tsx
- Modify: web/src/routes/[Route].layout.test.ts
- Modify route styles only for moved keys.

Minimum extraction size:
- Move at least [one complete section/form/list/detail cluster].
- Remove at least [one route-owned helper group or style key group].

Verification:
- [Route layout test]
- [Route logic test if existing]
- VUI boundary/batch tests
- build
- diff check
```

### 8.4 Behavior Backlog Handoff Batch

Use this only to hand off non-componentization work discovered during refactoring.

```markdown
## Behavior Backlog Handoff: [Name]

Reason this is not a componentization batch:
- [backend/API/cache/destructive/config/streaming/bundling impact]

Owning lane:
- [agent-runtime-core/chat-coding-surface/web-workbench-surface/quality-and-operations]

Source of truth:
- [backend service/config/runtime file]

Frontend affected:
- [route/components]

Required validation:
- [backend tests]
- [route tests]
- [build]
- [runtime or launcher evidence if needed]

Blocked by:
- [active claim or missing decision]
```

## 9. Migration Queue

This queue is ordered by reuse value, conflict risk, and validation clarity. Re-evaluate active claims before starting any item.

### Q1. Finish Visual Grammar Wave 0-1

Status: partially prepared in local work but not closed on main.

Recommended next batch:

- Establish or reuse `web/src/components/vui/aesthetic/**` quiet-workbench compositions.
- Close `routeAestheticContract.test.ts` offenders for AppShell, ChatCoding, and safe Memory surfaces.
- Avoid Memory files currently owned by active user Markdown Space memory integration.

Known offender class:

- Header/eyebrow style keys carrying panel/card chrome.
- Button style keys carrying panel/card chrome.
- Full-page opaque `surface-page` wrappers in workbench route surfaces.

Validation:

- `src/routes/routeAestheticContract.test.ts`
- `src/components/vui/vuiAestheticPrimitives.test.tsx`
- `src/visual-regression/workbenchVisualMatrix.test.ts`
- affected layout tests
- build

### Q2. ChatCodingRoute Composition Bands

Preferred order:

1. Cache detail and token-budget/donut surfaces.
2. File preview/detail surfaces.
3. Composer attachments and active-send controls.
4. Live operation/status side surfaces.

Guardrails:

- Do not change session streaming semantics in this queue.
- Do not change CLI terminal protocol in this queue.
- Keep `ConversationView` and chat operation components as separate ownership surfaces.

Validation:

- `src/routes/ChatCodingRoute.layout.test.ts`
- `src/routes/ChatCodingRoute.runModeChip.test.ts`
- `src/routes/SessionContextMenu.test.tsx` if session index/menu surfaces are touched
- conversation component tests if composition crosses into conversation components
- VUI boundary/batch tests
- build

### Q3. TeamsRoute Remaining Research Workflow Clusters

Recently completed clusters:

- `TeamWorkflowCandidatePreviewPanel`
- `TeamWorkflowStatusPanels`
- `TeamSourceCollectionOverviewPanel`
- `TeamSourceCollectionPanelFrame.styles`
- `TeamSourceCollectionResultControls`
- `TeamSourceCollectionActiveStagePanel` result-layout ownership
- `TeamSourceCollectionGraphPanel` node-list ownership

Preferred remaining order:

1. Source collection architecture split: follow [Teams source collection vertical split](2026-07-13-teams-source-collection-vertical-split-design.md); its first implementation stage moves pure models and shared read-query ownership, while later controller/view stages remain separately gated.
2. Candidate paper-note chunk actions and card toolbar cluster.
3. Research loop evidence/status cluster.
4. Experiment smoke/full-run result cluster.
5. Canvas organization controls if still route-owned after verifying `ResearchFlowCanvasRoute` boundaries.

Guardrails:

- Do not alter Challenge Cup workflow semantics in a visual/componentization batch.
- If touching `挑战杯/**`, update the Challenge Cup flow site in the same governance round.
- Keep workflow API/state and source collection writeback behavior out of normal visual/componentization rounds. The dedicated source collection architecture design is the only current exception, and it still preserves API, cache, URL, writeback, and user-visible semantics.

Validation:

- `src/routes/TeamsRoute.layout.test.ts`
- `src/routes/TeamsRoute.logic.test.ts`
- VUI boundary/batch tests
- build
- targeted backend tests only if route props reveal stale assumptions

### Q4. AgentsRoute View-Model And Workspace Composition

Many detail/config panels are already extracted. Remaining work should focus on reducing route-level view-model sprawl and workspace composition bands.

Preferred order:

1. Selected-agent workspace shell props consolidation.
2. List/detail split view-model helpers.
3. Bulk operation orchestration props normalization.
4. Repeated status/metric row visual grammar moved to product/VUI compositions.

Guardrails:

- Do not change Agent archive/purge/reset semantics in a componentization batch.
- Do not touch `web/src/api/types.ts` while another active claim owns it.
- Keep backend Agent Directory cache/service changes separate.

Validation:

- `src/routes/AgentsRoute.layout.test.ts`
- agent workspace cache tests if cache helpers are touched
- VUI boundary/batch tests
- build

### Q5. EvolutionRoute Supervised/Self-Evolution Workbench Bands

Preferred order:

1. Supervised active-run monitor panels.
2. Worktree run queue/list/detail composition.
3. Proposal action bands.
4. Self-evolution lazy track boundary review.

Guardrails:

- Do not change run actions, apply/activate/rollback semantics, or SSE contracts in a componentization batch.
- Any behavior change in supervised evolution belongs to `evolution-control-plane`.

Validation:

- `src/routes/EvolutionRoute.layout.test.ts`
- supervised workspace/tabs tests if touched
- build
- targeted Python tests only for behavior batches

### Q6. MemoryRoute Componentization After Active Claim Clears

Many Memory panels are already extracted. Current Memory work can overlap `codex-user-markdown-space-memory`, so start only after active scope is clear or choose a non-overlapping file set.

Preferred order:

1. Visual grammar convergence in Memory local panel styles.
2. Knowledge detail/action button chrome cleanup.
3. Graph/canvas shell visual convergence.
4. Management editor action surfaces.

Guardrails:

- Do not touch `web/src/routes/memory/memoryusercontentpanel.tsx`, its style file, `MemoryRoute.tsx`, or `web/src/api/types.ts` while the user Markdown Space claim is active unless explicitly coordinated.
- Do not change memory source-of-truth, promotion, RAG, or formal memory behavior in this queue.

Validation:

- `src/routes/MemoryRoute.layout.test.ts`
- `MemoryRouteCss.layout.test.ts` if still present in the selected branch
- VUI boundary/batch tests
- route aesthetic contract if visual grammar is touched
- build

### Q7. ConfigRoute Schema/Editor Composition

Already completed:

- `ConfigLogHelperCenterPanel`
- `ConfigWorkspacePlaceholderPanel`

Preferred order:

1. Schema editor section composition.
2. Avatar/crop/edit display bands if still route-owned.
3. Config action panels only after source-of-truth and destructive/config validation are explicit.

Guardrails:

- Treat `C:\Users\17533\Documents\Vibelution\config\config.toml` as operator config source of truth.
- Do not duplicate ConfigHealthDiagnosticsPanel if the current code already uses `ConfigLogHelperCenterPanel`.
- Config behavior changes require config route/service tests, not only layout tests.

Validation:

- `src/routes/ConfigRoute.layout.test.ts`
- `src/routes/configRouteLogic.test.ts` if logic helpers are touched
- config route/service Python tests if behavior changes
- VUI boundary/batch tests
- build

### Q8. ResetRoute Action Surface

Reset is not primarily a componentization task until action semantics are settled. Treat it as a behavior backlog with destructive-operation guardrails.

Guardrails:

- Archive/reset/delete semantics must be explicit.
- Preview before execute must remain.
- Protected areas must stay protected.

Validation:

- backend reset service tests;
- Reset route layout tests;
- destructive-operation boundary tests;
- build.

## 10. Test Alignment Rules

Structural refactors must classify tests:

| Test type | Keep when | Update when | Remove or migrate when |
| --- | --- | --- | --- |
| Layout source tests | They protect ownership and visible structure | Component boundary changes | They only assert retired implementation detail. |
| Logic tests | They protect route-derived view-model behavior | Helpers move files | They only preserve old helper placement. |
| VUI boundary tests | They protect architecture | New component needs local style map or narrow exception | Exception has expired. |
| Aesthetic contract tests | They protect visual grammar | New accepted grammar needs precise rule | Rule blocks valid product-specific state. |
| Build/type checks | Always required for frontend code changes | Build config changes | Never removed for code changes. |

Do not weaken a test to pass a refactor. Either keep the product invariant and update ownership assertions, or state why the old assertion protected a retired structure.

## 11. Visual Grammar Rules

Use these rules during visual convergence:

- Headers orient; they should not usually be cards.
- Eyebrows label; they should not carry full panel chrome.
- Buttons act; they should not carry panel wrappers.
- Rows scan; they should not default to separate cards.
- Panels frame meaningful repeated items or tools; avoid nested cards.
- Surface wrappers should stay background-aware and avoid opaque full-page masks.
- Explanatory copy should stay terse on dense operational surfaces.
- Tooltips or details can carry supplemental meaning; critical blockers remain visible.
- Controls must fit Chinese and English labels without overflow.

When a style key violates these rules across multiple files, prefer a visual grammar batch instead of one-off edits.

## 12. Backlog Separation Rules

Componentization should not be a hiding place for behavior changes.

Route a discovered issue as follows:

| Discovered work | Route |
| --- | --- |
| Query/cache/source-of-truth mismatch | Behavior fix with frontend cache coherence validation. |
| Backend route or service contract change | Separate behavior batch with Python tests. |
| SSE/live transport | Chat/runtime behavior batch. |
| Reset/delete/archive/purge | Destructive behavior batch with preview/execute tests. |
| Config model/provider/source-of-truth | Config behavior batch with operator config validation. |
| Bundle chunk optimization | Performance/build batch. |
| Visual grammar offender | Visual grammar batch. |
| Route DOM cluster | Route panel extraction batch. |

## 13. Stop Conditions

Stop and report instead of forcing the migration when:

- An active claim owns a target file.
- The route behavior would change without explicit user approval.
- The extraction requires changing backend DTOs or route APIs.
- Tests reveal the old structure encodes a product invariant that is not yet represented in the new component.
- The batch needs to edit `DEVELOPMENT_STANDARD.md`, `AGENTS.md`, `.docs/project-memory/**`, generated memory HTML, `VERSION`, `CHANGELOG.md`, `web/package.json`, or `web/package-lock.json`.
- Validation fails three times for the same reason and the cause is outside the batch contract.
- A Launcher restart would be required while active-work guards show running work.

## 14. Project Memory And Claim Closure

For meaningful frontend batches, sync project memory after validation:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\sync_project_memory.py" "C:\Users\17533\Desktop\Vibelution" --lane web-workbench-surface --focus "<batch focus>" --update "<validated result summary>"
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\render_overview.py" "C:\Users\17533\Desktop\Vibelution"
```

Release the claim:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" release --claim-id "<claim-id>" --status completed --reason "<validated result>"
```

If memory sync is unsafe because another claim owns `.docs/project-memory/**`, report the exact memory update proposal and do not hand-edit generated memory files.

## 15. Commit And Merge Rules

Stage only current-task files:

```powershell
git status --short --branch
git add -- "docs/superpowers/specs/<file>.md" "web/src/routes/<files>" "web/src/components/vui/<files>"
git diff --cached --check
git commit -m "<type>(web): <scoped behavior>"
```

For a componentization batch, commit messages should be behavior-oriented:

- `refactor(web): extract chat cache detail panel`
- `refactor(web): consolidate memory route panel chrome`
- `test(web): add workbench visual grammar contract`
- `refactor(web): move teams paper-note actions into panel`

Do not use:

- `update files`
- `cleanup`
- `misc frontend`
- `wip`

Merge to local main only after:

- target files are clean or conflicts are understood;
- validation passed in the task worktree;
- root target paths are not dirty with unrelated changes;
- merge validation can run on main.

Do not push or create a PR without explicit user authorization.

## 16. Standard Completion Report

Use this compact report:

```markdown
完成状态: [completed / ready_for_merge / blocked]

Claim:
- id: [claim-id]
- branch: [branch]
- worktree: [absolute path]

What changed:
- [route/component ownership change]
- [style/VUI ownership change]
- [tests added or updated]

Validation:
- [command] => PASS/FAIL with count if available
- [command] => PASS/FAIL

Decisions:
- Logging: [not added because display-only refactor / added because behavior path changed]
- Tests: [focused tests used]
- Architecture/test alignment: [old structure retired, invariant preserved]
- Developer mode: [not affected / parity preserved]
- Launcher refresh: [not needed / recommended before user testing / required before release]
- Version impact: [none / patch/minor recommendation]

Remaining risk:
- [active claims, visual manual review, deferred behavior backlog]

Next batch:
- [recommended next migration batch]
```

## 17. Success Criteria For The Long-Running Program

This componentization program is complete when:

- The six large routes no longer carry unrelated dense DOM clusters inside route bodies.
- Parent route style maps no longer act as shared style registries for child panels.
- Route layout tests lock route/component ownership boundaries without preserving retired internals.
- Reusable header, row, status, toolbar, metric, and panel grammar exists in VUI/product compositions where appropriate.
- `@heroui/react` stays behind VUI layers.
- Production TSX avoids inline layout styles.
- Visual grammar checks and VUI boundary checks pass.
- The project can continue frontend work from this playbook without asking each Agent to rediscover the migration process.

## 18. Superseded Teams Recommendation

The following block records the 2026-07-05 recommendation for historical context. It is no longer executable guidance for Teams source collection; use [Teams source collection vertical split](2026-07-13-teams-source-collection-vertical-split-design.md) instead.

```text
Batch: Teams source collection view-model split wave
Reason: Source collection display ownership is now mostly local, but TeamsRoute still owns dense projection/filter/pagination/provenance helper code. Splitting that layer removes more route mass without touching backend behavior.
Scope:
- web/src/routes/TeamsRoute.tsx
- web/src/routes/TeamsRoute.layout.test.ts
- web/src/routes/TeamsRoute.logic.test.ts
- new route-local helper/adapter files such as web/src/routes/TeamSourceCollectionViewModel.ts
- focused TeamSourceCollection* tests if helpers become testable outside the route
Validation:
- npm --prefix web run test -- src/routes/TeamsRoute.layout.test.ts src/routes/TeamsRoute.logic.test.ts --run
- npm --prefix web run test -- src/components/vui/vuiImportBoundary.test.ts src/components/vui/vuiBatchMigration.test.ts --run
- npm --prefix web run build
- git diff --check
Stop:
- if a helper extraction would change source collection query keys, mutation sequencing, writeback semantics, or backend DTO shape.
```

Parallel alternative if Teams source collection becomes blocked:

```text
Batch: AppShell + ChatCoding visual grammar convergence
Reason: routeAestheticContract failures are concrete, mostly style-only, and avoid Memory/user-content API ownership.
Scope:
- web/src/app/AppShell.styles.ts
- web/src/app/AppShellStatusGuidePanel.styles.ts
- web/src/app/AppShellUtilityMenu.styles.ts
- web/src/routes/ChatCodingRoute.styles.ts
- web/src/routes/routeAestheticContract.test.ts
- affected AppShell/ChatCoding layout tests
Validation:
- npm --prefix web run test -- src/routes/routeAestheticContract.test.ts --run
- npm --prefix web run test -- src/app/AppShell.layout.test.ts src/routes/ChatCodingRoute.layout.test.ts src/routes/RouteStyleDisplayContract.test.ts --run
- npm --prefix web run test -- src/components/vui/vuiImportBoundary.test.ts src/components/vui/vuiBatchMigration.test.ts --run
- npm --prefix web run build
- git diff --check
Stop:
- if Memory offenders become required before the active user Markdown Space claim closes.
```

Do not edit `MemoryRoute.tsx`, `web/src/api/types.ts`, or `web/src/routes/memory/**` during either recommended next batch while a user Markdown Space claim owns those paths.
