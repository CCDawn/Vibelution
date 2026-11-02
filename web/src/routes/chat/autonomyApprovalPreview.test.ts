import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { autonomyActionIsKnown, autonomyApprovalPreviewIsValid, autonomyApprovalText } from "./autonomyApprovalPreview";

// Golden metadata produced by autonomy_approval.approval_summary with the real
// Launcher DTO registry. Integer target values are decimal strings on this wire.
const backendTargets: Record<string, Record<string, unknown>> = {
  delegation_goal_create: { goal_id: "goal-a", targets: [{ project_id: "project-a", agent_id: "agent-a" }],
    permission_profile: "read_only", max_tasks: "8", ttl_minutes: "60" },
  delegation_goal_revoke: { goal_id: "goal-a" },
  dispatch_derived: { project_id: "project-a", agent_id: "agent-a", dispatch_id: "dispatch-a", goal_id: "goal-a", permission_profile: "read_only" },
  research_command: { run_id: "run-a", team_id: "team-a", flow_id: "flow-a", command: "retry_node", expected_revision: "2",
    node_id: "node-a", task_id: "", decision: "", checkpoint_id: "", project_id: "project-a", request_id: "request-a" },
  authorization_reduce: { expected_scopes: ["agents:read", "operations:control"], expected_grant_revision: "3",
    remove_scopes: ["operations:control"], project_id: "project-a", request_id: "request-a" },
  authorization_revoke: { expected_scopes: ["agents:read", "operations:control"], expected_grant_revision: "3", project_id: "project-a", request_id: "request-a" },
};
const backendDigests: Record<string, string> = {
  delegation_goal_create: "1a48fb0543a7c1510babf7fdf05389b2c008fa85db4b04ac06bb35be1c0a3f78",
  delegation_goal_revoke: "11b5153958327e49767fa6491a7c92daf05854c1dccd6a248a8172899791c46b",
  dispatch_derived: "0d8cf7867f88cf1b1f81c9af0e54f6480d15c68d21c09b344d4829584a362186",
  research_command: "72e3efb06656b2da35eb22496e85ae64d2126fd54b172d68e997197fae3d6369",
  authorization_reduce: "520dbf545bb6ea14e635bb95bec559625c6e35fccf95197f2884d64b6d11f380",
  authorization_revoke: "7978d829cb367da2da20c80469ec0e85a12ad522692b13b4baa06cbaed22c11d",
};
const task = "检查 🧭 与 e\u0301\n保留全文。";
function metadata(action: string): Record<string, unknown> {
  return { assistantAction: action, assistantAutonomyPreviewVersion: 1, assistantParametersDigest: backendDigests[action],
    assistantDetailsOmitted: false, assistantTargets: structuredClone(backendTargets[action]),
    ...(action === "dispatch_derived" ? { assistantTask: task, assistantTaskChars: "15",
      assistantTaskDigest: "37658757dfe3fe366ce5f1973015dc411117f923abf4de3d16bcf26f9459541f", assistantRequestedPermission: "read_only" } : {}) };
}
const canonical = (value: unknown): string => Array.isArray(value) ? `[${value.map(canonical).join(",")}]`
  : value && typeof value === "object" ? `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`).join(",")}}`
    : JSON.stringify(value);
const sha = (value: string) => createHash("sha256").update(value).digest("hex");

describe("complete native autonomy approval metadata", () => {
  it.each(Object.keys(backendTargets))("matches the actual backend shape and checksum for %s", action => {
    const summary = metadata(action);
    expect(autonomyActionIsKnown(action)).toBe(true);
    expect(autonomyApprovalPreviewIsValid(summary)).toBe(true);
    const parameters = structuredClone(backendTargets[action]);
    for (const key of ["max_tasks", "ttl_minutes", "expected_grant_revision"]) if (key in parameters) parameters[key] = Number(parameters[key]);
    if (action === "dispatch_derived") {
      parameters.task = task;
      expect(Array.from(task)).toHaveLength(15);
      expect(sha(task)).toBe(summary.assistantTaskDigest);
    }
    expect(sha(canonical(parameters))).toBe(summary.assistantParametersDigest);
    for (const lang of ["zh", "en"] as const) {
      const text = autonomyApprovalText(summary, lang);
      expect(text).not.toContain("[object Object]");
      expect(text).not.toContain("无法核对");
      expect(text).not.toContain("cannot be verified");
    }
  });

  it.each(Object.keys(backendTargets))("rejects omitted or extra critical fields for %s", action => {
    for (const field of Object.keys(backendTargets[action])) {
      const summary = metadata(action);
      delete (summary.assistantTargets as Record<string, unknown>)[field];
      expect(autonomyApprovalPreviewIsValid(summary), field).toBe(false);
    }
    const summary = metadata(action);
    (summary.assistantTargets as Record<string, unknown>).actor = "forged";
    expect(autonomyApprovalPreviewIsValid(summary)).toBe(false);
  });

  it.each([undefined, "1", 2, true])("rejects missing/forged preview versions %s", version => {
    expect(autonomyApprovalPreviewIsValid({ ...metadata("delegation_goal_create"), assistantAutonomyPreviewVersion: version })).toBe(false);
  });
  it.each([
    { assistantAction: "delegated_goal_create" }, { assistantAction: "agent_update" }, { assistantDetailsOmitted: true },
    { assistantDetailsOmitted: undefined }, { assistantArgumentsInvalid: true }, { assistantParametersDigest: "0" },
    { assistantParametersDigest: "A".repeat(64) }, { unreviewed: "SECRET" }, { assistantTask: "SECRET" },
  ])("does not render unreviewable metadata %j", patch => {
    const summary = { ...metadata("delegation_goal_create"), ...patch };
    expect(autonomyApprovalPreviewIsValid(summary)).toBe(false);
    expect(autonomyApprovalText(summary, "zh")).toContain("无法核对");
    expect(autonomyApprovalText(summary, "zh")).not.toContain("SECRET");
  });

  it("shows every goal target and bounded permission, quota and expiry without shortening IDs", () => {
    const summary = metadata("delegation_goal_create"), targets = summary.assistantTargets as Record<string, unknown>;
    targets.targets = Array.from({ length: 16 }, (_, i) => ({ project_id: "p".repeat(157) + `-${i}`, agent_id: "a".repeat(160) }));
    targets.goal_id = "g".repeat(96);
    targets.permission_profile = "workspace_write";
    targets.max_tasks = "32";
    targets.ttl_minutes = "1440";
    expect(autonomyApprovalPreviewIsValid(summary)).toBe(true);
    const text = autonomyApprovalText(summary, "zh");
    for (const row of targets.targets as { project_id: string; agent_id: string }[]) {
      expect(text).toContain(row.project_id); expect(text).toContain(row.agent_id);
    }
    for (const value of [targets.goal_id, "32", "1440", "workspace_write"]) expect(text).toContain(value);
    expect(text).not.toContain("...");
    (targets.targets as unknown[]).push((targets.targets as unknown[])[0]);
    expect(autonomyApprovalPreviewIsValid(summary)).toBe(false);
  });

  it.each([{ max_tasks: "0" }, { max_tasks: "33" }, { max_tasks: 8 }, { max_tasks: "08" }, { ttl_minutes: "1441" },
    { permission_profile: "full_access" }, { goal_id: "goal\nforged" }, { targets: [] },
    { targets: [{ project_id: "p", agent_id: "a" }, { project_id: "p", agent_id: "a" }] }])("closes goal bounds and enums %j", patch => {
    const summary = metadata("delegation_goal_create"); Object.assign(summary.assistantTargets as object, patch);
    expect(autonomyApprovalPreviewIsValid(summary)).toBe(false);
  });

  it("keeps the full 12000-code-point derived task including emoji and the final character", () => {
    const summary = metadata("dispatch_derived"), full = "🧭".repeat(11999) + "终";
    Object.assign(summary, { assistantTask: full, assistantTaskChars: "12000", assistantTaskDigest: sha(full) });
    expect(full.length).toBe(23999);
    expect(autonomyApprovalPreviewIsValid(summary)).toBe(true);
    expect(autonomyApprovalText(summary, "zh")).toContain(full);
    expect(autonomyApprovalText(summary, "en")).toContain(full);
    summary.assistantTaskChars = String(full.length);
    expect(autonomyApprovalPreviewIsValid(summary)).toBe(false);
  });

  it.each([{ assistantTaskChars: "14" }, { assistantTaskChars: 15 }, { assistantTaskChars: undefined },
    { assistantTaskDigest: undefined }, { assistantRequestedPermission: "workspace_write" },
    { assistantTask: " altered " }, { assistantTask: "a\u202eb" }, { assistantTask: "a\u0000b" },
    { assistantTask: "a\ud800b" }, { assistantTask: "a".repeat(12001), assistantTaskChars: "12001" }])("rejects derived task truncation, controls or permission mismatch %j", patch => {
    expect(autonomyApprovalPreviewIsValid({ ...metadata("dispatch_derived"), ...patch })).toBe(false);
  });

  it("shows all research references, human decision and checkpoint with the exact large revision", () => {
    const summary = metadata("research_command"), targets = summary.assistantTargets as Record<string, unknown>;
    Object.assign(targets, { command: "resolve_human_task", node_id: "node-a", task_id: "task-a", decision: "revise",
      checkpoint_id: "checkpoint-a", expected_revision: "9223372036854775807" });
    expect(autonomyApprovalPreviewIsValid(summary)).toBe(true);
    for (const lang of ["zh", "en"] as const) for (const value of ["run-a", "team-a", "flow-a", "node-a", "task-a", "checkpoint-a", targets.expected_revision]) {
      expect(autonomyApprovalText(summary, lang)).toContain(value);
    }
    expect(autonomyApprovalText(summary, "zh")).toContain("修订");
  });

  it.each([{ command: "start_node" }, { expected_revision: "0" }, { expected_revision: "9223372036854775808" },
    { command: "reconcile_run" }, { task_id: "extra-task" }, { checkpoint_id: "forged" },
    { command: "resolve_human_task", task_id: "task-a", decision: "revise" },
    { command: "resolve_human_task", task_id: "task-a", decision: "accept", checkpoint_id: "forged" }])("closes research command combinations %j", patch => {
    const summary = metadata("research_command"); Object.assign(summary.assistantTargets as object, patch);
    expect(autonomyApprovalPreviewIsValid(summary)).toBe(false);
  });

  it("displays the exact previous, removed and remaining permissions and the revoke consequence", () => {
    const reduce = autonomyApprovalText(metadata("authorization_reduce"), "zh");
    for (const value of ["原权限", "撤销权限", "保留权限", "agents:read", "operations:control", "3"]) expect(reduce).toContain(value);
    const revoke = autonomyApprovalText(metadata("authorization_revoke"), "zh");
    for (const value of ["全部", "失效", "agents:read", "operations:control"]) expect(revoke).toContain(value);
    expect(autonomyApprovalText(metadata("delegation_goal_revoke"), "zh")).toContain("已有任务");
  });

  it.each([{ expected_scopes: ["operations:control", "agents:read"] }, { expected_scopes: ["agents:read", "agents:read"] },
    { remove_scopes: ["agents:read", "operations:control"] }, { remove_scopes: ["agents:purge"] },
    { remove_scopes: [] }, { expected_scopes: ["root:all"] }, { expected_grant_revision: "9007199254740991" },
    { expected_grant_revision: "3\n" }])("closes sorted unique self-subject scope reductions %j", patch => {
    const summary = metadata("authorization_reduce"); Object.assign(summary.assistantTargets as object, patch);
    expect(autonomyApprovalPreviewIsValid(summary)).toBe(false);
  });
});
