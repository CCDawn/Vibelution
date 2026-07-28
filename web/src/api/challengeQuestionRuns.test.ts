import { describe, expect, it } from "vitest";

import apiSource from "./challengeQuestionRuns.ts?raw";

describe("challenge question run API", () => {
  it("uses an explicit team and question identity for the read-only detail endpoint", () => {
    expect(apiSource).toContain("/challenge-program/questions/");
    expect(apiSource).toContain("encodeURIComponent(questionId)");
    expect(apiSource).toContain("runId=");
    expect(apiSource).not.toContain("researchProject");
  });
});
