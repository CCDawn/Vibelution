import { describe, expect, it } from "vitest";

import { agentPurgeBatchPreviewIsValid, launcherAgentPurgeBatchActionPreview } from "./launcherAgentPurgeBatchPreview";

// Shape produced by actions.agent_purge_batch_approval_summary; native tool projection
// additionally supplies argumentKeys: ["action", "arguments_json"].
function validSummary(count = 2) {
  return {
    assistantAction: "agent_purge_batch",
    assistantTargets: { project_id: "registered:project-1", request_id: "purge-request_1", batchCount: String(count) },
    assistantPurgeItems: Array.from({ length: count }, (_, index) => ({
      agent_id: `agent-${index + 1}`, expected_config_revision: String(index),
    })),
    assistantPurgeIrreversible: true,
    assistantPurgeEffects: ["agent", "sessions", "private_workspace", "team_room_mode_references"],
  };
}

function expectInvalid(summary: unknown) {
  expect(agentPurgeBatchPreviewIsValid(summary)).toBe(false);
  expect(launcherAgentPurgeBatchActionPreview(summary, "zh")).toContain("不能批准");
  expect(launcherAgentPurgeBatchActionPreview(summary, "en")).toContain("Cannot approve");
}

describe("Launcher complete batch purge approval preview", () => {
  it.each([1, 2, 50])("shows every one of %i targets, its exact revision, and the irreversible scope", count => {
    const summary = validSummary(count);
    summary.assistantPurgeItems[count - 1].expected_config_revision = "900719925474099312345678901234567890";
    expect(agentPurgeBatchPreviewIsValid(summary)).toBe(true);
    expect(launcherAgentPurgeBatchActionPreview(summary, "zh").split("\n")[0]).toBe(`永久删除${count}个Agent`);
    for (const lang of ["zh", "en"] as const) {
      const text = launcherAgentPurgeBatchActionPreview(summary, lang);
      expect(text).toContain(summary.assistantTargets.project_id);
      expect(text).toContain(summary.assistantTargets.request_id);
      summary.assistantPurgeItems.forEach((item, index) => {
        expect(text).toContain(lang === "zh"
          ? `${index + 1}. Agent：${item.agent_id}；配置版本：${item.expected_config_revision}`
          : `${index + 1}. Agent: ${item.agent_id}; config revision: ${item.expected_config_revision}`);
      });
      for (const scope of lang === "zh" ? ["不可逆", "全部会话", "私有工作区", "团队房间模式引用", "无法撤销"]
        : ["Irreversible", "all its sessions", "private workspace", "team room mode references", "cannot be undone"]) expect(text).toContain(scope);
    }
  });

  it("accepts exactly the native standard argumentKeys or no argumentKeys", () => {
    expect(agentPurgeBatchPreviewIsValid({ ...validSummary(), argumentKeys: ["action", "arguments_json"] })).toBe(true);
    for (const argumentKeys of [null, [], ["action"], ["arguments_json", "action"], ["action", "arguments_json", "force"],
      ["action", "action"], "action,arguments_json"]) expectInvalid({ ...validSummary(), argumentKeys });
  });

  it("rejects every missing top-level, target, or item field", () => {
    for (const key of Object.keys(validSummary())) {
      const summary: Record<string, unknown> = validSummary();
      delete summary[key];
      expectInvalid(summary);
    }
    for (const key of Object.keys(validSummary().assistantTargets)) {
      const summary = validSummary();
      const targets: Record<string, unknown> = { ...summary.assistantTargets };
      delete targets[key];
      expectInvalid({ ...summary, assistantTargets: targets });
    }
    for (const key of Object.keys(validSummary().assistantPurgeItems[0])) {
      const summary = validSummary();
      const item: Record<string, unknown> = { ...summary.assistantPurgeItems[0] };
      delete item[key];
      expectInvalid({ ...summary, assistantPurgeItems: [item, summary.assistantPurgeItems[1]] });
    }
  });

  it("rejects unknown metadata and any invalid or omission marker", () => {
    for (const key of ["force", "assistantArgumentsInvalid", "assistantDetailsOmitted", "assistantContentOmitted", "omitted", "invalid"])
      for (const value of [true, false, null]) expectInvalid({ ...validSummary(), [key]: value });
    expectInvalid({ ...validSummary(), assistantTargets: { ...validSummary().assistantTargets, force: true } });
    const summary = validSummary();
    expectInvalid({ ...summary, assistantPurgeItems: [summary.assistantPurgeItems[0], { ...summary.assistantPurgeItems[1], force: true }] });
    for (const assistantAction of ["agent_purge", "agent_update", null]) expectInvalid({ ...validSummary(), assistantAction });
    for (const assistantPurgeIrreversible of [false, "true", 1, null]) expectInvalid({ ...validSummary(), assistantPurgeIrreversible });
  });

  it("requires 1..50 complete unique items and a lossless matching decimal count", () => {
    expectInvalid(validSummary(0));
    expectInvalid(validSummary(51));
    const summary = validSummary();
    expectInvalid({ ...summary, assistantPurgeItems: [summary.assistantPurgeItems[0], summary.assistantPurgeItems[0]] });
    expectInvalid({ ...summary, assistantPurgeItems: new Array(2) });
    for (const batchCount of ["0", "1", "3", "02", "+2", "2.0", "2\n", "9007199254740993", 2, null])
      expectInvalid({ ...summary, assistantTargets: { ...summary.assistantTargets, batchCount } });
    for (const assistantPurgeItems of [null, {}, "agent-1", [null], [{}, {}]]) expectInvalid({ ...summary, assistantPurgeItems });
  });

  it("requires nonnegative canonical decimal revision strings without numeric coercion", () => {
    for (const expected_config_revision of [-1, 0, 9007199254740992, "-1", "+1", "01", "1.0", "1e3", "", "1\n", "１", null]) {
      const summary = validSummary(1);
      expectInvalid({ ...summary, assistantPurgeItems: [{ ...summary.assistantPurgeItems[0], expected_config_revision }] });
    }
  });

  it("requires the exact fixed ordered irreversible effects", () => {
    const summary = validSummary();
    for (const assistantPurgeEffects of [null, [], summary.assistantPurgeEffects.slice(1), [...summary.assistantPurgeEffects, "unknown"],
      [...summary.assistantPurgeEffects].reverse(), ["agent", "sessions", "private_workspace", "unknown"],
      ["agent", "sessions", "private_workspace", "private_workspace"]]) expectInvalid({ ...summary, assistantPurgeEffects });
  });

  it("enforces exact safe identity lengths and rejects deceptive Unicode or multiline identities", () => {
    const boundary = validSummary(1);
    boundary.assistantTargets.project_id = "p".repeat(160);
    boundary.assistantTargets.request_id = "r".repeat(96);
    boundary.assistantPurgeItems[0].agent_id = "a".repeat(128);
    expect(agentPurgeBatchPreviewIsValid(boundary)).toBe(true);
    for (const unsafe of ["", "../agent", "agent/1", "*", " agent", "agent ", "agent\n", "agent\r\n", "agent\u2028x", "agent\u2029x",
      "agent\u202ex", "agent\u2066x", "agent\u200bx", "agent\u0000", "agent\ud800", "ａｇｅｎｔ", "аgent", "agent😀"]) {
      const summary = validSummary(1);
      expectInvalid({ ...summary, assistantTargets: { ...summary.assistantTargets, project_id: unsafe } });
      expectInvalid({ ...summary, assistantTargets: { ...summary.assistantTargets, request_id: unsafe } });
      expectInvalid({ ...summary, assistantPurgeItems: [{ ...summary.assistantPurgeItems[0], agent_id: unsafe }] });
    }
    expectInvalid({ ...boundary, assistantTargets: { ...boundary.assistantTargets, project_id: "p".repeat(161) } });
    expectInvalid({ ...boundary, assistantTargets: { ...boundary.assistantTargets, request_id: "r".repeat(97) } });
    expectInvalid({ ...boundary, assistantPurgeItems: [{ ...boundary.assistantPurgeItems[0], agent_id: "a".repeat(129) }] });
    for (const request_id of ["request:1", "request.1"]) expectInvalid({ ...boundary, assistantTargets: { ...boundary.assistantTargets, request_id } });
  });

  it.each([null, undefined, true, "agent_purge_batch", [], {}, { assistantTargets: null }])("fails closed for malformed input %j", value => {
    expectInvalid(value);
  });
});
