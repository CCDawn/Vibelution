# Web Baseline Test Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore a green complete Web test suite by synchronizing a stale route-style contract and removing dynamic module loading from two timed image tests.

**Architecture:** Keep production route and image-component behavior unchanged. Update static contract expectations to match the current route composition, and move image component imports to module scope so dependency transformation is outside individual test timeout windows.

**Tech Stack:** TypeScript 5.9, React 19 server rendering, Vitest 3, Vite 8.

## Global Constraints

- Do not modify production route layout or image components.
- Do not increase global or per-test timeout values.
- Preserve all existing render assertions.
- Verify the three affected test files before rerunning the complete Web suite.

---

### Task 1: Synchronize the route-style contract

**Files:**

- Modify: `web/src/routes/RouteStyleDisplayContract.test.ts`

**Interfaces:**

- Consumes: current `ChatCodingRoute` class composition using `styles.layout` and `styles.layoutCompactDesktop`.
- Produces: a static grid-display contract that recognizes `layoutCompactDesktop` as a composed modifier.

- [ ] **Step 1: Preserve the observed RED evidence**

Run result already captured:

```text
RouteStyleDisplayContract.test.ts: 2 failed
- layoutCompactDesktop reported as a grid-template utility without grid display
- expected layoutCenterFirst composition was absent
```

- [ ] **Step 2: Update the composed modifier identity**

Replace:

```typescript
"ChatCodingRoute.styles.ts:layoutCenterFirst",
```

with:

```typescript
"ChatCodingRoute.styles.ts:layoutCompactDesktop",
```

- [ ] **Step 3: Update the source composition assertion**

Replace:

```typescript
expect(chatRouteSource).toContain("`${styles.layout} ${styles.layoutCenterFirst}`");
```

with:

```typescript
expect(chatRouteSource).toContain("`${styles.layout} ${styles.layoutCompactDesktop}`");
```

- [ ] **Step 4: Verify the route contract**

Run:

```powershell
npm --prefix web test -- src/routes/RouteStyleDisplayContract.test.ts
```

Expected result: `2 passed`.

### Task 2: Move image component loading outside test timeouts

**Files:**

- Modify: `web/src/components/conversation/ConversationImagePreviewDialog.test.tsx`
- Modify: `web/src/components/conversation/ConversationImageArtifactView.test.tsx`

**Interfaces:**

- Consumes: `ConversationImagePreviewDialog` and `ConversationImageArtifactView` named exports.
- Produces: unchanged static-markup assertions without asynchronous module loading inside test bodies.

- [ ] **Step 1: Preserve the observed RED evidence**

Run result already captured from the complete suite:

```text
ConversationImagePreviewDialog: timed out after 5000ms
ConversationImageArtifactView: timed out after 5000ms
```

- [ ] **Step 2: Statically import the preview dialog**

Add:

```typescript
import { ConversationImagePreviewDialog } from "./ConversationImagePreviewDialog";
```

Change the test from:

```typescript
it("renders a preview dialog with download and close actions", async () => {
  const { ConversationImagePreviewDialog } = await import("./ConversationImagePreviewDialog");
```

to:

```typescript
it("renders a preview dialog with download and close actions", () => {
```

- [ ] **Step 3: Statically import the image artifact view**

Add:

```typescript
import { ConversationImageArtifactView } from "./ConversationImageArtifactView";
```

Change the test from:

```typescript
it("renders generated image artifact preview, metadata, and download affordance", async () => {
  const { ConversationImageArtifactView } = await import("./ConversationImageArtifactView");
```

to:

```typescript
it("renders generated image artifact preview, metadata, and download affordance", () => {
```

- [ ] **Step 4: Verify all affected files together**

Run:

```powershell
npm --prefix web test -- src/routes/RouteStyleDisplayContract.test.ts src/components/conversation/ConversationImagePreviewDialog.test.tsx src/components/conversation/ConversationImageArtifactView.test.tsx
```

Expected result: `9 passed`.

- [ ] **Step 5: Verify the complete Web suite and build**

Run:

```powershell
npm --prefix web test
npm --prefix web run build
```

Expected result: all Web tests pass and the frontend production build succeeds.

### Task 3: Review and integrate

**Files:**

- Review all task-scoped source, test, specification, and plan changes.

**Interfaces:**

- Consumes: complete branch diff and fresh verification evidence.
- Produces: one scoped commit suitable for local `main` integration.

- [ ] **Step 1: Review for behavioral and test risks**

Confirm:

```text
- final assistant messages supersede same-turn live overlays
- draft-only overlays remain visible
- route and image production code is unchanged
- no timeout values were increased
- no text-content deduplication was introduced
```

- [ ] **Step 2: Commit only task files**

Stage the two assistant projection files, three baseline test files, and four design/plan documents. Commit with:

```powershell
git commit -m "fix(web): consolidate settled assistant messages"
```

- [ ] **Step 3: Merge locally and reverify**

Merge `codex/assistant-message-consolidation` into local `main`, rerun the decisive focused tests and frontend build on `main`, then perform the Launcher refresh decision.
