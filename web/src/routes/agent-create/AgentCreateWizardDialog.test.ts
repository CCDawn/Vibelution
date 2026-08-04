import { describe, expect, it } from "vitest";

import dialogSource from "./AgentCreateWizardDialog.tsx?raw";
import dialogStyles from "./AgentCreateWizardDialog.styles";

describe("AgentCreateWizardDialog contract", () => {
  it("hosts creation in VDialog with viewport-clamped content", () => {
    expect(dialogSource).toContain("<VDialog");
    expect(dialogSource).toContain("from \"../../components/vui\"");
    expect(dialogSource).toContain("onOpenChange={handleOpenChange}");
    expect(dialogSource).toContain("contentClassName={styles.dialogContent}");
    expect(dialogSource).toContain("triggerRef?.current");
    expect(dialogSource).toContain("document.getElementById(triggerId)");
    expect(dialogSource).toContain("requestAnimationFrame(() => {");
    expect(dialogSource).not.toContain("createPortal(");
    expect(dialogSource).not.toContain('document.body.style.overflow = "hidden"');
    expect(dialogStyles.dialogContent).toContain("min(880px");
    expect(dialogStyles.dialogContent).toContain("100dvh");
  });

  it("loads avatar options while open for create-time library picks", () => {
    expect(dialogSource).toContain("/api/agents/avatar-options");
    expect(dialogSource).toContain("avatarOptions=");
    expect(dialogSource).toContain("avatarOptionsPending=");
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

  it("adds the newly created Agent to the chat directory cache before reconciliation", () => {
    expect(dialogSource).toContain("setQueryData<AgentInstance[]>(queryKeys.agents()");
    expect(dialogSource).toContain("afterAgentWorkspaceChanged()");
  });

  it("requires a successful saved-config probe before creation", () => {
    expect(dialogSource).toContain('fetchJson<ConfigLlmTestResult>("/api/config/test-llm"');
    expect(dialogSource).toContain("publicConfig: {}");
    expect(dialogSource).toContain('capability: "text"');
    expect(dialogSource).toContain("probeUsableModelIds");
    expect(dialogSource).toContain("createDraftReady(draft, toolBundles, probeUsableModelIds)");
    expect(dialogSource).toContain('markProbe(modelId, "ok"');
    expect(dialogSource).toContain('markProbe(modelId, "fail"');
  });

  it("keeps discard confirmation and success actions inside the dialog body", () => {
    expect(dialogSource).toContain("discardConfirmOpen");
    expect(dialogSource).toContain("setDiscardConfirmOpen(true)");
    expect(dialogSource).toContain("createdAgent");
    expect(dialogSource).toContain("onStartConversation");
    expect(dialogStyles.confirmation).toContain("grid");
    expect(dialogStyles.success).toContain("min-h-[280px]");
  });
});
