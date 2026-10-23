import { describe, expect, it } from "vitest";

import {
  toolApprovalActionPreview,
  toolApprovalCodexButtonLabels,
  toolApprovalCodexTitle,
  toolApprovalDisplayName,
  toolApprovalSessionGrantDescription,
} from "./toolApprovalPreview";

describe("toolApprovalPreview", () => {
  it("explains the one-step team run and rejects an incomplete scope", () => {
    const summary = { assistantAction: "team_run", assistantTargets: { name: "验收团队", template_id: "dev-team" },
      assistantPlan: { memberCount: 4, goalPreview: "核对计算结果", startsImmediately: true, automaticRecovery: false, localIntegration: false } };
    const preview = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
    expect(preview).toContain("创建团队并运行");
    expect(preview).toContain("核对计算结果");
    expect(preview).toContain("规划师 → 开发 A → 开发 B → 评审员");
    expect(preview).toContain("立即启动");
    expect(preview).toContain("不启用自动恢复、自动合入或部署");
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en")).toContain("Create 4 members");
    expect(toolApprovalActionPreview({ ...summary, assistantPlan: undefined }, "personal_assistant_manage_tool", "zh"))
      .toContain("运行范围无法核对");
  });
  it("shows the assistant operation and concrete target in both languages", () => {
    const summary = { assistantAction: "session_create", assistantTargets: { agent_id: "agent-a", title: "Acceptance" } };
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh"))
      .toBe("创建会话\nagent_id: agent-a\ntitle: Acceptance");
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en"))
      .toContain("Create session");
    expect(toolApprovalActionPreview({ assistantAction: "session_delete", assistantArgumentsInvalid: true }, "personal_assistant_manage_tool", "zh"))
      .toContain("参数无法核对");
    expect(toolApprovalActionPreview({ assistantAction: "agent_update", assistantChangedFields: ["tool_policy_json"], assistantDetailsOmitted: true }, "personal_assistant_manage_tool", "en"))
      .toContain("Values omitted");
  });
  it("covers managed write actions with names, targets and changed fields", () => {
    expect(toolApprovalActionPreview(
      { assistantAction: "team_create", assistantTargets: { name: "交付团队", templateId: "dev-team" } },
      "personal_assistant_manage_tool", "zh",
    )).toBe("创建团队\nname: 交付团队\ntemplateId: dev-team");
    expect(toolApprovalActionPreview(
      { assistantAction: "knowledge_ingest", assistantTargets: { inboxSourceId: "isrc-1", ownerType: "team", ownerId: "team-1" } },
      "personal_assistant_manage_tool", "en",
    )).toContain("Ingest knowledge");
    expect(toolApprovalActionPreview(
      { assistantAction: "config_update", assistantChangedFields: ["ui.language", "llm.profiles.primary.model_ref"], assistantDetailsOmitted: true },
      "personal_assistant_manage_tool", "zh",
    )).toContain("修改字段: ui.language, llm.profiles.primary.model_ref");
    // An unknown manage action still renders the refuse-and-retry guidance.
    expect(toolApprovalActionPreview(
      { assistantAction: "config_write" }, "personal_assistant_manage_tool", "zh",
    )).toContain("参数无法核对");
  });

  it("prefers command preview for shell tools like Codex", () => {
    expect(toolApprovalActionPreview({
      commandPreview: "curl https://example.com",
      argumentKeys: ["cmd"],
    }, "web_fetch_tool")).toBe("$ curl https://example.com");
  });

  it("shows cwd and stdin while keeping session grants truthful", () => {
    expect(toolApprovalActionPreview({
      commandPreview: '.\\.venv\\Scripts\\python.exe -c "print(123)"',
      cwdPreview: "C:\\workspace\\repo",
    }, "exec_command")).toContain("cwd: C:\\workspace\\repo");
    expect(toolApprovalActionPreview({
      terminalSessionId: "sandbox-terminal-a",
      stdinPreview: "ORBIT-71\n",
      stdinChars: 9,
    }, "write_stdin")).toContain("stdin (9 chars):\nORBIT-71\n");
    expect(toolApprovalSessionGrantDescription({ kind: "terminal_session" }, "zh"))
      .toContain("同一终端");
  });

  it("falls back to path preview then tool label", () => {
    expect(toolApprovalActionPreview({
      pathPreview: "docs/readme.md",
    }, "read_file_tool")).toBe("docs/readme.md");
    expect(toolApprovalDisplayName("web_fetch_tool", "zh")).toBe("读取网页");
  });

  it("uses Codex-style title and Yes/Always/No labels", () => {
    expect(toolApprovalCodexTitle("zh")).toBe("允许执行？");
    expect(toolApprovalCodexTitle("en")).toBe("Allow this action?");
    expect(toolApprovalCodexButtonLabels("en")).toMatchObject({
      yes: "Yes",
      always: "Always (this agent)",
      no: "No",
    });
    expect(toolApprovalCodexButtonLabels("zh")).toMatchObject({
      yes: "是",
      always: "始终（此 Agent）",
      no: "否",
    });
    expect(toolApprovalSessionGrantDescription({ kind: "exact_arguments" }, "zh"))
      .toContain("永久");
  });
});
