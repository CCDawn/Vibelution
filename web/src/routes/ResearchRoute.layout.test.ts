import { describe, expect, it } from "vitest";

import styles from "./ResearchRoute.module.css";
import routeSource from "./ResearchRoute.tsx?raw";

describe("ResearchRoute layout contract", () => {
  it("renders the API-backed theme discovery MVP", () => {
    expect(routeSource).toContain("ResearchRoute");
    expect(routeSource).toContain("/api/research/theme-discovery/sessions");
    expect(routeSource).toContain("run-draft");
    expect(routeSource).toContain("generate-themes");
    expect(routeSource).toContain("theme-card");
    expect(routeSource).toContain("Candidate themes");
    expect(routeSource).not.toContain("Frontend preview");
  });

  it("keeps the page in the existing dense workbench layout family", () => {
    expect(styles.route).toBeTypeOf("string");
    expect(styles.summaryGrid).toBeTypeOf("string");
    expect(styles.workspace).toBeTypeOf("string");
    expect(styles.sessionRail).toBeTypeOf("string");
    expect(styles.pipelinePanel).toBeTypeOf("string");
    expect(styles.evidencePanel).toBeTypeOf("string");
    expect(styles.outputPanel).toBeTypeOf("string");
    expect(styles.themeGrid).toBeTypeOf("string");
  });
});
