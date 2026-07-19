import { describe, expect, it } from "vitest";

import dialogSource from "./AgentCreateWizardDialog.tsx?raw";
import dialogStyles from "./AgentCreateWizardDialog.styles";

describe("AgentCreateWizardDialog contract", () => {
  it("keeps creation in an accessible, scroll-contained floating layer", () => {
    expect(dialogSource).toContain("createPortal(");
    expect(dialogSource).toContain('role="dialog"');
    expect(dialogSource).toContain('aria-modal="true"');
    expect(dialogSource).toContain('event.key === "Escape"');
    expect(dialogSource).toContain('event.key !== "Tab"');
    expect(dialogSource).toContain('querySelector<HTMLElement>("[autofocus]")');
    expect(dialogSource).toContain("triggerRef?.current");
    expect(dialogSource).toContain("document.getElementById(triggerId)");
    expect(dialogSource).toContain("requestAnimationFrame(() => {");
    expect(dialogSource).toContain('document.body.style.overflow = "hidden"');
    expect(dialogStyles.overlay).toContain("fixed inset-0");
    expect(dialogStyles.body).toContain("overflow-y-auto");
  });

  it("loads options only while open, preserves the draft, and creates no implicit session", () => {
    expect(dialogSource).toContain("enabled: open");
    expect(dialogSource).toContain("draftDirty");
    expect(dialogSource).toContain("normalizeCreateDraftForWorkspace");
    expect(dialogSource).toContain('fetchJson<AgentConfigWorkspaceAgent>("/api/agents"');
    expect(dialogSource).toContain("onStartConversation");
    expect(dialogSource).toContain("onStartConversation(createdAgent)");
    expect(dialogSource).not.toContain('fetchJson<SessionDetail>("/api/sessions"');
  });
});
