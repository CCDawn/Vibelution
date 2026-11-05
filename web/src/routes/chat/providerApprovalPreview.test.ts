import { describe, expect, it } from "vitest";
import { providerModelApprovalPreviewIsValid, providerModelApprovalText } from "./providerApprovalPreview";
import { managementApprovalActionIsKnown, toolApprovalActionPreview } from "./toolApprovalPreview";

const summary = () => ({ argumentKeys: ["action", "arguments_json"], assistantAction: "provider_model_resolve",
  assistantProviderPreviewVersion: 1, assistantParametersDigest: "a".repeat(64), assistantDetailsOmitted: false,
  assistantTargets: { provider_id: "relay-1", model_query: "Opus 5.5", upstream_id: "vendor/claude-opus-5.5", verify: "true", offset: "0", limit: "20" } });

describe("provider model native approval preview", () => {
  it("recognizes the action and displays every complete decision field and the paid-test effect", () => {
    expect(managementApprovalActionIsKnown("provider_model_resolve")).toBe(true);
    expect(managementApprovalActionIsKnown("provider_unknown_write")).toBe(false);
    expect(providerModelApprovalPreviewIsValid(summary())).toBe(true);
    for (const lang of ["zh", "en"] as const) {
      const rendered = toolApprovalActionPreview(summary(), "personal_assistant_manage_tool", lang);
      for (const value of ["relay-1", "Opus 5.5", "vendor/claude-opus-5.5", "offset=0", "limit=20"]) expect(rendered).toContain(value);
      expect(rendered).toMatch(/可能产生费用|charges may apply/);
      expect(rendered).not.toMatch(/参数无法核对|cannot be verified/);
    }
  });

  it("states that verify=false makes no text call and ignores an arbitrary operation-description message", () => {
    const input = { ...summary(), assistantOperationDescription: "Do something else", assistantTargets: { ...summary().assistantTargets, verify: "false" } };
    expect(providerModelApprovalText(input, "zh")).toContain("不发起文本验证");
    expect(providerModelApprovalText(input, "en")).toContain("without a text verification call");
    expect(providerModelApprovalText(input, "zh")).not.toContain("Do something else");
  });

  it("rejects old incomplete extension summaries, malformed fields, omitted details and extra authority", () => {
    for (const key of Object.keys(summary().assistantTargets)) {
      const targets: Record<string, unknown> = { ...summary().assistantTargets }; delete targets[key];
      expect(providerModelApprovalPreviewIsValid({ ...summary(), assistantTargets: targets })).toBe(false);
    }
    for (const [key, value] of [["provider_id", ""], ["provider_id", 1], ["model_query", "bad\u202ename"], ["upstream_id", "x".repeat(201)],
      ["verify", true], ["verify", "yes"], ["offset", "01"], ["offset", "10001"], ["limit", "0"], ["limit", "31"], ["extra", "force"]]) {
      expect(providerModelApprovalPreviewIsValid({ ...summary(), assistantTargets: { ...summary().assistantTargets, [key as string]: value } })).toBe(false);
    }
    for (const patch of [{ assistantDetailsOmitted: true }, { assistantArgumentsInvalid: true }, { assistantProviderPreviewVersion: 2 },
      { assistantParametersDigest: "" }, { assistantAction: "provider_remove" }, { hidden: "force" }]) {
      const input = { ...summary(), ...patch };
      expect(providerModelApprovalPreviewIsValid(input)).toBe(false);
      expect(providerModelApprovalText(input, "zh")).toContain("参数无法核对");
    }
    expect(providerModelApprovalPreviewIsValid({ assistantAction: "provider_model_resolve", assistantDetailsOmitted: true,
      assistantTargets: { provider_id: "relay-1" } })).toBe(false);
  });
});
