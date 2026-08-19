import { describe, expect, it } from "vitest";

import {
  presentResearchWorkflowError,
  researchWorkflowErrorInlineText,
} from "./researchWorkflowErrorModel";

describe("presentResearchWorkflowError", () => {
  it("maps cascade reset recommendation for downstream experiment blocks", () => {
    const presented = presentResearchWorkflowError(
      "本项目已有实验设计或迭代产物，资料批次保留供审计，无法仅清空资料后重开。请使用「连同实验与迭代一起清空」。",
    );
    expect(presented.recommendedAction).toBe("reset_progress_cascade");
    expect(presented.titleZh).toContain("仅清资料");
  });

  it("maps wait recommendation while search is running", () => {
    const presented = presentResearchWorkflowError(
      "The current project's source search is still running. Wait for it to finish before clearing this project.",
    );
    expect(presented.recommendedAction).toBe("wait_for_search");
  });

  it("falls back to raw message for unknown errors", () => {
    const presented = presentResearchWorkflowError("Something custom failed");
    expect(presented.bodyZh).toBe("Something custom failed");
    expect(presented.recommendedAction).toBe("none");
  });
});

describe("researchWorkflowErrorInlineText", () => {
  it("combines productized title and guidance for known failures", () => {
    const text = researchWorkflowErrorInlineText(
      "The current project's source search is still running. Wait for it to finish before clearing this project.",
    );
    expect(text).toContain("资料搜索仍在进行");
    expect(text).toContain("请等待当前批次搜索结束后再清空或重开");
  });

  it("keeps raw technical messages out of the inline flow for unknown failures", () => {
    const text = researchWorkflowErrorInlineText("TypeError: Cannot read properties of undefined");
    expect(text).toBe("操作未完成");
    expect(text).not.toContain("TypeError");
  });

  it("renders the generic title for empty input", () => {
    expect(researchWorkflowErrorInlineText("")).toBe("操作未完成");
    expect(researchWorkflowErrorInlineText(null)).toBe("操作未完成");
  });
});
