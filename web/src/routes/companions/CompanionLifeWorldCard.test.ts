import { describe, expect, it } from "vitest";

import source from "./CompanionLifeWorldCard.tsx?raw";

describe("CompanionLifeWorldCard", () => {
  it("edits and confirms the Agent-scoped structured life draft", () => {
    expect(source).toContain("updateVirtualHumanLifeDraft");
    expect(source).toContain("confirmVirtualHumanLifeWorld");
    expect(source).toContain("expectedDraftRevision");
    expect(source).toContain("expectedBindingVersion");
    expect(source).toContain("draftId");
    expect(source).toContain("roleTitle");
    expect(source).toContain("affiliations");
    expect(source).toContain("items");
  });

  it("keeps life management on the paired hidden steward Session", () => {
    expect(source).toContain('steward.provisioningState === "ready"');
    expect(source).toContain("onOpenSteward(steward.sessionId)");
    expect(source).not.toContain("/chat?session=");
  });

  it("uses VUI controls for the desktop rail interaction", () => {
    expect(source).toContain("VButton");
    expect(source).toContain("VInput");
    expect(source).toContain("VStatusChip");
    expect(source).toContain("aria-label");
  });

  it("keeps the long draft editor collapsed until the user asks to edit", () => {
    expect(source).toContain('<details className={styles.disclosure}>');
    expect(source).not.toContain('<details className={styles.disclosure} open>');
  });
});
