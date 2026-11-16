import { describe, expect, it } from "vitest";
import { providerModelApprovalPreviewIsValid, providerModelApprovalText } from "./providerApprovalPreview";
import { managementApprovalActionIsKnown, toolApprovalActionPreview } from "./toolApprovalPreview";

const summary = () => ({ argumentKeys: ["action", "arguments_json"], assistantAction: "provider_model_resolve",
  assistantProviderPreviewVersion: 1, assistantParametersDigest: "a".repeat(64), assistantDetailsOmitted: false,
  assistantTargets: { provider_id: "relay-1", model_query: "Opus 5.5", upstream_id: "vendor/claude-opus-5.5", verify: "true", offset: "0", limit: "20" } });

describe("provider model native approval preview", () => {
  it("shows every requested batch connection in a single approval", () => {
    const { assistantTargets: _, ...base } = summary();
    const row = { providerId: "chatgpt", modelId: "chatgpt/gpt-6.1-sol-high", origin: "https://api.openai.com", protocol: "responses" };
    const local = { providerId: "local", modelId: "local/qwen", origin: "http://127.0.0.1:8081", protocol: "chat_completions" };
    const input = { ...base, assistantAction: "provider_test_batch", assistantProbeTargets: [row, local] };
    expect(managementApprovalActionIsKnown(input.assistantAction)).toBe(true);
    expect(providerModelApprovalPreviewIsValid(input)).toBe(true);
    const preview = toolApprovalActionPreview(input, "personal_assistant_manage_tool", "zh");
    for (const value of ["最多 2 次", row.modelId, row.origin, local.modelId, local.origin]) expect(preview).toContain(value);
    for (const targets of [[], [row, row], [{ ...row, modelId: "unrelated/model" }], [{ ...row, origin: "https://example.com/private" }]]) {
      expect(providerModelApprovalPreviewIsValid({ ...input, assistantProbeTargets: targets })).toBe(false);
    }
  });
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
