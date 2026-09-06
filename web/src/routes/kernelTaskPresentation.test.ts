import { describe, expect, it } from "vitest";
import { kernelTaskTitle } from "./kernelTaskPresentation";

describe("kernel task title", () => {
  it("uses the actual topic without the machine prefix or the remaining prompt", () => {
    expect(kernelTaskTitle("Chat room round: ## 核验资料来源\n请检索完整的资料并核验。", "task-1", "zh")).toBe("核验资料来源");
  });
  it("keeps ordinary task names and does not invent missing phases or identities", () => {
    expect(kernelTaskTitle("执行自定义检查", "task-2", "zh")).toBe("执行自定义检查");
    expect(kernelTaskTitle("", "task-2", "zh")).toBe("task-2");
    expect(kernelTaskTitle("Chat room round:", "task-2", "en")).toBe("Group discussion");
  });
});
