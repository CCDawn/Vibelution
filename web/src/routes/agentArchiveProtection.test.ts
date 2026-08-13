import { describe, expect, it } from "vitest";

import { agentArchiveProtected } from "./agentArchiveProtection";

describe("agentArchiveProtected", () => {
  it("protects research-org and system-owned roles", () => {
    expect(agentArchiveProtected({ metadata: { researchOrgRole: "organization_advisor" } })).toBe(true);
    expect(agentArchiveProtected({ metadata: { researchOrgRole: "capability_steward" } })).toBe(true);
    expect(agentArchiveProtected({ metadata: { systemRole: "runtime" } })).toBe(true);
    expect(agentArchiveProtected({ metadata: { protected: true } })).toBe(true);
    expect(agentArchiveProtected({ metadata: {} })).toBe(false);
    expect(agentArchiveProtected(null)).toBe(false);
  });
});
