import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("TeamSourceCollectionScreeningPanel", () => {
  it("uses a non-verbal scroll cue instead of permanent gray instructions", () => {
    const source = readFileSync(
      new URL("./TeamSourceCollectionScreeningPanel.tsx", import.meta.url),
      "utf8",
    );
    const styles = readFileSync(
      new URL("./TeamSourceCollectionScreeningPanel.styles.ts", import.meta.url),
      "utf8",
    );

    expect(source).toContain("sourceCollectionScreeningScrollCue");
    expect(styles).toContain("bg-gradient-to-t");
    expect(source).not.toContain("可向下滚动查看更多");
    expect(source).not.toContain("向下滚动查看更多本页候选");
  });
});
