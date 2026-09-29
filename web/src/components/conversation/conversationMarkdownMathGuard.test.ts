import { describe, expect, it } from "vitest";

import { guardConversationMarkdownMath } from "./conversationMarkdownMathGuard";

describe("guardConversationMarkdownMath", () => {
  it("escapes compact currency ranges so `$5-$10` never becomes a formula", () => {
    // Only the opening `$` of a compact range is escaped; the closing one has
    // no partner left, so the whole run renders as plain text with `$` visible.
    expect(guardConversationMarkdownMath("套餐价格 $5-$10，两档。")).toBe("套餐价格 \\$5-$10，两档。");
    expect(guardConversationMarkdownMath("预算 $1,200+$800 超支。")).toBe("预算 \\$1,200+$800 超支。");
  });

  it("escapes paired dollar text that is not math", () => {
    expect(guardConversationMarkdownMath("售价 $100，成本 $80。")).toBe("售价 \\$100，成本 $80。");
    expect(guardConversationMarkdownMath("set $HOME before $PATH")).toBe("set \\$HOME before $PATH");
  });

  it("keeps a real single-dollar formula untouched for inline KaTeX", () => {
    expect(guardConversationMarkdownMath("边际成本 $c = a + b$ 递增")).toBe("边际成本 $c = a + b$ 递增");
    expect(guardConversationMarkdownMath("统一初值 $x^2$ 即可")).toBe("统一初值 $x^2$ 即可");
    expect(guardConversationMarkdownMath("速度 $\\alpha$")).toBe("速度 $\\alpha$");
  });

  it("keeps `$$…$$` block math untouched", () => {
    const block = "$$\\sum_{i=1}^{n} x_i$$";
    expect(guardConversationMarkdownMath(block)).toBe(block);
    const flow = ["$$", "\\sum_{i=1}^{n} x_i", "$$"].join("\n");
    expect(guardConversationMarkdownMath(flow)).toBe(flow);
  });

  it("leaves a lone `$` in place and never crashes", () => {
    expect(guardConversationMarkdownMath("成本合计 $")).toBe("成本合计 $");
    expect(guardConversationMarkdownMath("$")).toBe("$");
    expect(guardConversationMarkdownMath("")).toBe("");
  });

  it("skips dollars inside fenced code blocks and inline code spans", () => {
    const fenced = ["```bash", "export PRICE=$5", "echo $PATH", "```"].join("\n");
    expect(guardConversationMarkdownMath(fenced)).toBe(fenced);
    expect(guardConversationMarkdownMath("run `export P=$5` then $x^2$")).toBe(
      "run `export P=$5` then $x^2$",
    );
  });

  it("is idempotent across repeated passes (streaming re-parses every frame)", () => {
    const once = guardConversationMarkdownMath("价格 $5-$10，公式 $x^2$，尾随 $");
    expect(guardConversationMarkdownMath(once)).toBe(once);
    const escaped = "已转义 \\$100 与 \\$5-\\$10";
    expect(guardConversationMarkdownMath(escaped)).toBe(escaped);
  });

  it("keeps math adjacent to currency on the same line", () => {
    expect(guardConversationMarkdownMath("成本 $c$ 约 $5-$10")).toBe("成本 $c$ 约 \\$5-$10");
  });
});
