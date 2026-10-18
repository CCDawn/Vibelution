import { describe, expect, it } from "vitest";
import { toolApprovalRiskLabel } from "./toolApprovalLabels";

describe("native tool risk labels", () => {
  it("preserves native categories instead of calling them low risk", () => {
    expect(toolApprovalRiskLabel("destructive", "zh")).toBe("破坏性操作");
    expect(toolApprovalRiskLabel("execute", "en")).toBe("Code execution");
    expect(toolApprovalRiskLabel("write", "zh")).toBe("写入操作");
    expect(toolApprovalRiskLabel("network", "en")).toBe("Network access");
    expect(toolApprovalRiskLabel("read", "zh")).toBe("读取操作");
    expect(toolApprovalRiskLabel("new-risk", "zh")).toBe("风险未分类");
    expect(toolApprovalRiskLabel(undefined, "en")).toBe("Unclassified risk");
    expect(toolApprovalRiskLabel("low", "zh")).toBe("低风险");
    expect(toolApprovalRiskLabel("high", "en")).toBe("High risk");
  });
});
