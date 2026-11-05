import { describe, expect, it } from "vitest";
import { agentConfigurationApprovalActionIsKnown, agentConfigurationApprovalPreviewIsValid, agentConfigurationApprovalText } from "./agentConfigurationApprovalPreview";

const policy = () => ({ mode: "custom", enabled: true, maxTokenLimit: "50000", maxCompressionsPerSession: "10",
  levels: { light: 0.7, standard: 0.8, deep: 0.9, emergency: 1 },
  summaryChars: { light: "1000", standard: "2000", deep: "3000", emergency: "4000" },
  preservation: { keepAiMessages: "5", preserveErrors: true, extractKeyDecisions: false, retentionFocus: ["errors", "decisions"] },
  policyVersion: "0", compressionTriggerTokenLimit: "0", postCompressionTargetTokenLimit: "0" });
const summary = (kind = "model"): Record<string, unknown> => ({
  argumentKeys: ["action", "arguments_json"], assistantAction: "agent_parameters_update", assistantPlatformPreviewVersion: 1,
  assistantParametersDigest: "a".repeat(64), assistantDetailsOmitted: false, assistantContentOmitted: false,
  assistantTargets: { project_id: "project-a", request_id: "request-a", agent_id: "agent-a", expected_config_revision: "9007199254740993", kind },
  assistantChangedFields: [kind], assistantDelta: kind === "model" ? { expected_model_ref: "relay/model-a", context_window: "9007199254740993", reasoning_effort: "high" }
    : kind === "budget" ? { maxCallsPerTurn: "20" } : { policy: policy() },
});
const prompt = (): Record<string, unknown> => ({ ...summary(), assistantAction: "agent_prompt_update", assistantContentOmitted: true,
  assistantTargets: { project_id: "project-a", request_id: "request-a", agent_id: "agent-a", expected_config_revision: "7",
    expected_template_id: "agent:role.template-1", expected_content_hash: `sha256:${"b".repeat(64)}` },
  assistantChangedFields: ["promptContent", "promptTemplateId"], assistantDelta: {
    scope: "single_agent_copy_on_write", activation: "next_submission", contentChars: "25", contentDigest: "c".repeat(64),
  } });
const targets = (value: Record<string, unknown>) => value.assistantTargets as Record<string, unknown>;
const delta = (value: Record<string, unknown>) => value.assistantDelta as Record<string, unknown>;

describe("Agent configuration approval metadata", () => {
  it("recognizes exactly two known actions", () => {
    expect(agentConfigurationApprovalActionIsKnown("agent_parameters_update")).toBe(true);
    expect(agentConfigurationApprovalActionIsKnown("agent_prompt_update")).toBe(true);
    for (const action of ["agent_update", "agent_tool_policy_update", "unknown_write", null, {}, "agent_prompt_update\n"]) {
      expect(agentConfigurationApprovalActionIsKnown(action)).toBe(false);
    }
  });

  it.each(["model", "budget", "compression"])("shows all %s configuration metadata and precise integer strings", kind => {
    const input = summary(kind);
    expect(agentConfigurationApprovalPreviewIsValid(input)).toBe(true);
    for (const lang of ["zh", "en"] as const) {
      const rendered = agentConfigurationApprovalText(input, lang);
      for (const value of ["project-a", "request-a", "agent-a", "9007199254740993", kind]) expect(rendered).toContain(value);
      expect(rendered).not.toMatch(/参数无法核对|cannot be verified/);
      for (const value of Object.values(delta(input))) {
        if (typeof value === "string") expect(rendered).toContain(value);
      }
    }
  });

  it("displays prompt CAS, content metadata, isolated scope and activation without accepting a body", () => {
    const input = prompt();
    expect(agentConfigurationApprovalPreviewIsValid(input)).toBe(true);
    for (const lang of ["zh", "en"] as const) {
      const rendered = agentConfigurationApprovalText(input, lang);
      for (const value of ["project-a", "request-a", "agent-a", ": 7", "agent:role.template-1",
        `sha256:${"b".repeat(64)}`, ": 25", "c".repeat(64)]) expect(rendered).toContain(value);
      expect(rendered).toMatch(/从下一次新提交开始生效|next new submission/);
      expect(rendered).toMatch(/仅为此 Agent|this Agent only/);
      expect(rendered).toMatch(/不修改共享模板|preserves the shared template/);
    }
    const forged = { ...input, assistantDelta: { ...delta(input), content: "PRIVATE FULL PROMPT" } };
    expect(agentConfigurationApprovalPreviewIsValid(forged)).toBe(false);
    expect(agentConfigurationApprovalText(forged, "zh")).not.toContain("PRIVATE FULL PROMPT");
  });

  it("keeps budget null, zero and positive values semantically distinct", () => {
    for (const [value, zh, en] of [[null, "恢复默认", "restore the default"], ["0", "不限制", "unlimited"], ["200", "上限", "call limit"]] as const) {
      const input = { ...summary("budget"), assistantDelta: { maxCallsPerTurn: value } };
      expect(agentConfigurationApprovalPreviewIsValid(input)).toBe(true);
      expect(agentConfigurationApprovalText(input, "zh")).toContain(zh);
      expect(agentConfigurationApprovalText(input, "en")).toContain(en);
    }
  });

  it("requires every target, and cannot add unknown or cross-action targets", () => {
    for (const input of [summary(), prompt()]) {
      for (const key of Object.keys(targets(input))) {
        const incomplete = { ...targets(input) }; delete incomplete[key];
        expect(agentConfigurationApprovalPreviewIsValid({ ...input, assistantTargets: incomplete })).toBe(false);
      }
      expect(agentConfigurationApprovalPreviewIsValid({ ...input, assistantTargets: { ...targets(input), secret: "SECRET" } })).toBe(false);
    }
    for (const [key, value] of [["agent_id", "agent\nspoof"], ["project_id", "../project"], ["request_id", "request:a"],
      ["expected_config_revision", 7], ["expected_config_revision", "01"], ["expected_config_revision", "-1"], ["kind", "temperature"]]) {
      expect(agentConfigurationApprovalPreviewIsValid({ ...summary(), assistantTargets: { ...targets(summary()), [key as string]: value } })).toBe(false);
    }
    for (const [key, value] of [["expected_template_id", "role/other"], ["expected_template_id", "a".repeat(161)],
      ["expected_content_hash", "a".repeat(64)], ["expected_content_hash", `sha256:${"A".repeat(64)}`]]) {
      expect(agentConfigurationApprovalPreviewIsValid({ ...prompt(), assistantTargets: { ...targets(prompt()), [key]: value } })).toBe(false);
    }
  });

  it("rejects incomplete top-level metadata, unsorted fields and extra authority", () => {
    for (const patch of [{ assistantPlatformPreviewVersion: 2 }, { assistantParametersDigest: "" }, { assistantDetailsOmitted: true },
      { assistantArgumentsInvalid: true }, { assistantPermissions: ["all"] }, { assistantOperationDescription: "approve anyway" },
      { assistantContentOmitted: true }, { assistantChangedFields: ["budget"] }, { assistantChangedFields: ["model", "model"] },
      { argumentKeys: ["action", "other"] }, { argumentKeys: ["action", "action"] }, { hidden: "SECRET" }]) {
      const forged = { ...summary(), ...patch };
      expect(agentConfigurationApprovalPreviewIsValid(forged)).toBe(false);
      expect(agentConfigurationApprovalText(forged, "en")).toContain("cannot be verified");
      expect(agentConfigurationApprovalText(forged, "en")).not.toContain("SECRET");
    }
    expect(agentConfigurationApprovalPreviewIsValid({ ...prompt(), assistantChangedFields: ["promptTemplateId", "promptContent"] })).toBe(false);
    expect(agentConfigurationApprovalPreviewIsValid({ ...prompt(), assistantContentOmitted: false })).toBe(false);
  });

  it("validates model values using the executable schema and Unicode code-point limits", () => {
    const input = { ...summary(), assistantDelta: { expected_model_ref: "模😀".repeat(100), context_window: "1", reasoning_effort: "" } };
    expect(agentConfigurationApprovalPreviewIsValid(input)).toBe(true);
    for (const [key, value] of [["expected_model_ref", ""], ["expected_model_ref", " model"], ["expected_model_ref", "x".repeat(201)],
      ["context_window", "0"], ["context_window", 128000], ["context_window", "1.0"], ["context_window", true],
      ["reasoning_effort", " high "], ["reasoning_effort", "x".repeat(81)], ["temperature", 0.7]]) {
      expect(agentConfigurationApprovalPreviewIsValid({ ...input, assistantDelta: { ...delta(input), [key as string]: value } })).toBe(false);
    }
    for (const character of ["\n", "\x00", "\x7f", "\u200b", "\u202e", "\ud800", "\u2028", "\u2029"]) {
      expect(agentConfigurationApprovalPreviewIsValid({ ...input, assistantDelta: { ...delta(input), reasoning_effort: `high${character}` } })).toBe(false);
    }
  });

  it.each([{}, { maxCallsPerTurn: 0 }, { maxCallsPerTurn: "201" }, { maxCallsPerTurn: "-1" }, { maxCallsPerTurn: "00" },
    { maxCallsPerTurn: false }, { maxCallsPerTurn: "null" }, { maxCallsPerTurn: "20", extra: true }])("rejects non-schema budget %j", block => {
    expect(agentConfigurationApprovalPreviewIsValid({ ...summary("budget"), assistantDelta: block })).toBe(false);
  });

  it("requires the full compression policy including serialized defaults and float thresholds", () => {
    const input = summary("compression");
    const check = (value: unknown) => agentConfigurationApprovalPreviewIsValid({ ...input, assistantDelta: { policy: value } });
    for (const key of Object.keys(policy())) {
      const incomplete: Record<string, unknown> = { ...policy() }; delete incomplete[key];
      expect(check(incomplete)).toBe(false);
    }
    for (const patch of [{ mode: "inherit" }, { enabled: "true" }, { maxTokenLimit: "0" }, { maxTokenLimit: "2000001" },
      { maxCompressionsPerSession: "101" }, { policyVersion: 0 }, { compressionTriggerTokenLimit: "-1" },
      { postCompressionTargetTokenLimit: "2000001" }, { unknown: true }]) expect(check({ ...policy(), ...patch })).toBe(false);
    for (const value of ["0.7", NaN, Infinity, -0.1, 1.1, true]) {
      expect(check({ ...policy(), levels: { ...policy().levels, light: value } })).toBe(false);
    }
    for (const value of [1000, "0", "20001", null]) {
      expect(check({ ...policy(), summaryChars: { ...policy().summaryChars, light: value } })).toBe(false);
    }
    for (const patch of [{ keepAiMessages: "0" }, { keepAiMessages: "51" }, { preserveErrors: 1 }, { extractKeyDecisions: "false" },
      { retentionFocus: ["safe", false] }, { retentionFocus: ["unsafe\u202e"] }, { unknown: true }]) {
      expect(check({ ...policy(), preservation: { ...policy().preservation, ...patch } })).toBe(false);
    }
    expect(check({ ...policy(), preservation: { ...policy().preservation, retentionFocus: null } })).toBe(true);
    // The native DTO has no 32-item/200-character cap for retentionFocus.
    expect(check({ ...policy(), preservation: { ...policy().preservation, retentionFocus: Array(33).fill("k".repeat(201)) } })).toBe(true);
  });

  it("requires exact isolated prompt metadata and bounded content length", () => {
    for (const patch of [{ scope: "shared_template" }, { activation: "immediate" }, { contentChars: "0" }, { contentChars: "8001" },
      { contentChars: 25 }, { contentDigest: "sha256:" + "c".repeat(64) }, { instruction: "SECRET" }]) {
      expect(agentConfigurationApprovalPreviewIsValid({ ...prompt(), assistantDelta: { ...delta(prompt()), ...patch } })).toBe(false);
    }
    for (const count of ["1", "8000"]) expect(agentConfigurationApprovalPreviewIsValid({ ...prompt(), assistantDelta: { ...delta(prompt()), contentChars: count } })).toBe(true);
    for (const input of [undefined, null, {}]) expect(agentConfigurationApprovalPreviewIsValid(input)).toBe(false);
  });
});
