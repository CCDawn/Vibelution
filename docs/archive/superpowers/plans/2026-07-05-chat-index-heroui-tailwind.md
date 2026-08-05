# Chat Index HeroUI Tailwind Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the Chat/Coding left conversation index into a compact HeroUI/VUI + Tailwind sidebar list.

**Architecture:** Keep the existing `ConversationIndexTree` data flow and route state. Update only presentation components and their Tailwind style contracts, using existing VUI wrappers over HeroUI primitives.

**Tech Stack:** React 19, TypeScript, HeroUI via VUI wrappers, Tailwind utility strings, Vitest, Vite.

## Global Constraints

- Do not change backend, DTOs, query keys, grouping semantics, context menu behavior, drag references, or right-side chat UI.
- All touched UI styles must remain Tailwind utility strings, not new CSS modules or legacy CSS expansion.
- Buttons must hug content unless the whole row is intentionally clickable.
- Validate with focused Vitest, `npm --prefix web run build`, and browser screenshots/checks at desktop and narrow widths.

---

### Task 1: Lock Layout Contracts

**Files:**
- Modify: `web/src/routes/ChatCodingRoute.layout.test.ts`
- Modify: `web/src/routes/DirectSessionIndexItem.test.ts`
- Modify: `web/src/routes/GroupSessionIndexItems.test.ts`

**Interfaces:**
- Consumes: existing exported `styles` objects and static markup tests.
- Produces: failing assertions for the desired Tailwind/VUI contracts.

- [ ] Add tests that require compact search/action/section/item/system-entry style tokens.
- [ ] Run focused tests and verify they fail because the UI contracts are not implemented yet.

### Task 2: Refine Sidebar Shell, Search, Actions, And System Entry

**Files:**
- Modify: `web/src/routes/ChatCodingRoute.tsx`
- Modify: `web/src/routes/ChatCodingRoute.styles.ts`

**Interfaces:**
- Consumes: existing `VButton`, `VNativeInput`, `panelSearch`, `newSessionButton`, `newGroupButton`, `systemEntry*` class keys.
- Produces: compact HeroUI/VUI + Tailwind shell contracts for the screenshot top/bottom sections.

- [ ] Replace heavy search/action/system entry styling with compact Tailwind contracts.
- [ ] Preserve all event handlers and labels.
- [ ] Run focused route layout tests until green for this surface.

### Task 3: Refine Group Headers And Conversation Rows

**Files:**
- Modify: `web/src/routes/ConversationIndexSection.tsx`
- Modify: `web/src/routes/ConversationIndexSection.styles.ts`
- Modify: `web/src/routes/DirectSessionIndexItem.tsx`
- Modify: `web/src/routes/DirectSessionIndexItem.styles.ts`
- Modify: `web/src/routes/GroupSessionIndexItems.tsx`
- Modify: `web/src/routes/GroupSessionIndexItems.styles.ts`

**Interfaces:**
- Consumes: existing props and callbacks; no data model changes.
- Produces: one shared visual grammar for direct, group, team, active, current, and running rows.

- [ ] Apply subtle row backgrounds, stable grids, truncation, count/status chips, and active/running emphasis.
- [ ] Preserve rename, context menu, drag, open, and disabled semantics.
- [ ] Run component tests and route layout tests until green.

### Task 4: Verify, Screenshot, And Close

**Files:**
- Modify: `.docs/project-memory/lanes/chat-coding-surface.json`
- Modify: `.docs/project-memory/memory.json`
- Regenerate: `.docs/project-memory/overview.html`
- Regenerate: `.docs/project-memory/INDEX.md`
- Regenerate: `PROJECT_MEMORY.html`

**Interfaces:**
- Consumes: final UI diff and validation output.
- Produces: project memory update and task branch commit.

- [ ] Run focused Vitest for Chat/Coding layout and index item components.
- [ ] Run `npm --prefix web run build`.
- [ ] Verify the live page with browser screenshot/checks at desktop and narrow widths.
- [ ] Sync project memory with validation evidence.
- [ ] Release the guard claim and commit the task branch.
