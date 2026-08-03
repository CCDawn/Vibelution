import { describe, expect, it } from "vitest";

import { humanizeReasoningPreview } from "./conversationReasoningPreview";

describe("humanizeReasoningPreview", () => {
  it("inserts boundaries for camelCase and CJK/English glue", () => {
    expect(humanizeReasoningPreview('TheUserSays"确认"and继续')).toContain("The User Says");
    expect(humanizeReasoningPreview("状态ok下一步")).toContain("状态 ok 下一步");
  });

  it("softens long unspaced ascii blobs instead of dumping them raw", () => {
    const preview = humanizeReasoningPreview(
      "Letmeunderstandthecurrentstate.Theusersaysconfirmandcontinue",
    );
    expect(preview.length).toBeLessThanOrEqual(96);
    expect(preview).toContain("…");
    expect(preview).not.toMatch(/Letmeunderstandthecurrentstate\.Theusersaysconfirmandcontinue/);
  });
});
