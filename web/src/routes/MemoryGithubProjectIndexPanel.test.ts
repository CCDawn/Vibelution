import { describe, expect, it } from "vitest";

import panelSource from "./MemoryGithubProjectIndexPanel.tsx?raw";
import styles from "./MemoryGithubProjectIndexPanel.styles";

describe("MemoryGithubProjectIndexPanel", () => {
  it("uses VUI surfaces and the shared github-projects query key", () => {
    expect(panelSource).toContain("from \"../components/vui\"");
    expect(panelSource).toContain("<VSurface");
    expect(panelSource).toContain("<VPanelHeader");
    expect(panelSource).toContain("<VEntityList");
    expect(panelSource).toContain("<VNativeInput");
    expect(panelSource).toContain("<VEmptyState");
    expect(panelSource).toContain("queryKeys.githubProjectLibrary()");
    expect(panelSource).toContain("cloneGithubProject<GithubProjectLibraryMutationResponse>");
    expect(panelSource).toContain("isDisabled=");
    expect(panelSource).not.toContain("@heroui/react");
    expect(panelSource).not.toContain("/api/memory/");
    expect(styles.githubProjectsPanel).toContain("githubProjectsPanel");
  });
});
