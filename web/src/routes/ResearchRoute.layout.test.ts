import { describe, expect, it } from "vitest";

import styles from "./ResearchRoute.module.css";
import routeSource from "./ResearchRoute.tsx?raw";

describe("ResearchRoute layout contract", () => {
  it("renders the full research workflow as a frontend-only preview", () => {
    expect(routeSource).toContain("ResearchRoute");
    expect(routeSource).toContain("问题定义");
    expect(routeSource).toContain("资料归档");
    expect(routeSource).toContain("假设拆分");
    expect(routeSource).toContain("实验设计");
    expect(routeSource).toContain("证据合成");
    expect(routeSource).toContain("产出沉淀");
    expect(routeSource).toContain("Frontend preview");
  });

  it("keeps the page in the existing dense workbench layout family", () => {
    expect(styles.route).toBeTypeOf("string");
    expect(styles.summaryGrid).toBeTypeOf("string");
    expect(styles.workspace).toBeTypeOf("string");
    expect(styles.pipelinePanel).toBeTypeOf("string");
    expect(styles.evidencePanel).toBeTypeOf("string");
    expect(styles.outputPanel).toBeTypeOf("string");
  });
});
