# Composer Button States Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Chat/Coding composer button state colors while preserving compact geometry.

**Architecture:** Reuse the existing `ConversationView.styles.ts` named style slices. Add assertions to existing layout/style tests so state tokens remain stable.

**Tech Stack:** React, TypeScript, Tailwind utility strings, VUI/HeroUI wrappers, Vitest.

## Global Constraints

- Root checkout remains `main`; implementation happens in `C:\Users\17533\Desktop\Vibelution-worktrees\composer-button-states`.
- Scope is limited to composer button style/test/spec/plan files.
- Do not edit process trace or timeline style regions owned by the overlapping active claim.
- No runtime logging change is required because this is a presentation-only frontend style change.

---

### Task 1: Composer Button State Tokens

**Files:**
- Modify: `web/src/components/conversation/ConversationView.styles.ts`
- Modify: `web/src/components/conversation/ConversationView.test.tsx`
- Modify: `web/src/routes/ChatCodingRoute.layout.test.ts`

**Interfaces:**
- Consumes: existing `styles.attachButton`, `styles.composerRoundButton`, `styles.composerRoundButtonPrimary`, `styles.sendButton`, and `styles.stopButton`.
- Produces: updated class strings with default, hover, focus-visible, active, disabled, send, and stop state color tokens.

- [ ] **Step 1: Add failing style assertions**

Assert that composer action buttons include focus-visible, active, disabled, send accent, and stop danger/warning tokens.

- [ ] **Step 2: Run focused tests and confirm red**

Run: `npm --prefix web run test -- ConversationView.test.tsx ChatCodingRoute.layout.test.ts`
Expected: fail because the new state tokens are not present yet.

- [ ] **Step 3: Update style slices**

Revise only the composer button class strings near the top of `ConversationView.styles.ts` and the `attachButton` / `stopButton` entries.

- [ ] **Step 4: Run focused tests and build**

Run:

```powershell
npm --prefix web run test -- ConversationView.test.tsx ChatCodingRoute.layout.test.ts
npm --prefix web run build
```

Expected: both pass.

- [ ] **Step 5: Self-review diff**

Run:

```powershell
git diff --check
git diff -- web/src/components/conversation/ConversationView.styles.ts web/src/components/conversation/ConversationView.test.tsx web/src/routes/ChatCodingRoute.layout.test.ts
```

Expected: no whitespace errors and no edits outside composer button state slices.
