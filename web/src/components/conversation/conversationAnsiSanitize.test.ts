import { describe, expect, it } from "vitest";

import { stripAnsiArtifacts } from "./conversationAnsiSanitize";

describe("stripAnsiArtifacts", () => {
  it("removes full escape sequences including the control byte", () => {
    expect(stripAnsiArtifacts("生成计划\[1m加粗\[0m正文")).toBe("生成计划加粗正文");
    expect(stripAnsiArtifacts("a\[1;32mgreen\[0mb")).toBe("agreenb");
  });

  it("removes orphan CSI fragments after the ESC byte was lost upstream", () => {
    expect(stripAnsiArtifacts("生成计划[1m加粗[0m正文")).toBe("生成计划加粗正文");
    expect(stripAnsiArtifacts("cursor[?25lhidden[?25h")).toBe("cursorhidden");
    expect(stripAnsiArtifacts("clear[2Kline")).toBe("clearline");
  });

  it("keeps markdown brackets, footnotes and array indexing intact", () => {
    expect(stripAnsiArtifacts("see [1] and [^note] and arr[0] and [link](x)")).toBe(
      "see [1] and [^note] and arr[0] and [link](x)",
    );
  });

  it("drops stray C0 controls but keeps tab and newline", () => {
    expect(stripAnsiArtifacts("abc\nd\te")).toBe("abc\nd\te");
  });

  it("passes clean text through unchanged", () => {
    const clean = "生成计划：先分析，再实施。";
    expect(stripAnsiArtifacts(clean)).toBe(clean);
  });
});
