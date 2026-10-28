import { describe, expect, it } from "vitest";

import {
  authorizationUpgradePreviewIsValid,
  dispatchWritePreviewIsValid,
  launcherAgentCreatePreviewIsValid,
  projectLifecyclePreviewIsValid,
  toolApprovalActionPreview,
  toolApprovalCodexButtonLabels,
  toolApprovalCodexTitle,
  toolApprovalDisplayName,
  toolApprovalSessionGrantDescription,
} from "./toolApprovalPreview";

describe("toolApprovalPreview", () => {
  it("requires and displays every fixed file-tool permission and the dynamic directory boundary", () => {
    const summary = { assistantAction: "agent_create", assistantTargets: { project_id: "project:1", display_name: "Worker", model_id: "model-1" },
      assistantCreatePreset: "project_files_v1", assistantCreateTools: ["glob_tool", "grep_search_tool", "read_file_tool", "apply_diff_edit_tool", "write_file_tool"],
      assistantOperationDescription: "固定文件工具权限持续生效；写入按当前权限和协作模式审批，edit/yolo 等模式可能自动批准。目标派遣任务的审批目前只能拒绝，不能在 Launcher 批准写入。平台允许的动态目录包括项目、Agent 工作区、项目存储、工具目录、系统临时目录和用户配置允许目录，未来可能变化。不能执行命令或测试。" };
    expect(launcherAgentCreatePreviewIsValid(summary)).toBe(true);
    const zh = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
    const en = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en");
    for (const name of summary.assistantCreateTools) { expect(zh).toContain(name); expect(en).toContain(name); }
    for (const value of ["项目存储", "工具目录", "系统临时目录", "用户配置允许目录", "协作模式审批", "edit/yolo", "可能自动批准", "只能拒绝", "不能在 Launcher 批准写入", "未来可能变化", "不能执行命令或测试"]) expect(zh).toContain(value);
    for (const value of ["project storage", "tools directory", "system temporary directories", "user-configured allowed directories", "collaboration mode", "approve automatically", "only be declined", "cannot approve writes", "may change"]) expect(en).toContain(value);
    for (const patch of [{ assistantCreateTools: undefined }, { assistantCreateTools: ["glob_tool"] },
      { assistantCreatePreset: "full_access" }, { assistantOperationDescription: "omitted" }]) {
      expect(launcherAgentCreatePreviewIsValid({ ...summary, ...patch })).toBe(false);
    }
  });
  it("shows the complete Launcher creation project and model in both languages and counts code points", () => {
    const summary = { assistantAction: "agent_create", assistantTargets: {
      project_id: "project:1", display_name: "😀".repeat(120), model_id: "m".repeat(200),
    }, assistantOperationDescription: "新 Agent 默认没有工具和读写范围，不能保证读取或修改项目；派遣写任务不会自动增加工具权限。" };
    expect(launcherAgentCreatePreviewIsValid(summary)).toBe(true);
    const zh = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
    const en = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en");
    expect(zh).toContain(`模型: ${summary.assistantTargets.model_id}`);
    expect(en).toContain(`Model: ${summary.assistantTargets.model_id}`);
    expect(en).toContain("Project: project:1");
    expect(en).toContain("has no tools or read/write scopes by default");
    expect(en).not.toContain("新 Agent 默认");
    expect(launcherAgentCreatePreviewIsValid({ ...summary, assistantTargets: { ...summary.assistantTargets, display_name: "😀".repeat(121) } })).toBe(false);
    expect(launcherAgentCreatePreviewIsValid({ ...summary, assistantTargets: { ...summary.assistantTargets, model_id: "bad\u202evalue" } })).toBe(false);
    expect(launcherAgentCreatePreviewIsValid({ ...summary, assistantTargets: { project_id: "project:1", display_name: "Worker" } })).toBe(false);
  });
  it("shows the exact project lifecycle request and rejects incomplete details", () => {
    const summary = { assistantAction: "project_lifecycle", assistantTargets: {
      project_id: "project:1", operation: "start", request_id: "request-1",
    } };
    expect(projectLifecyclePreviewIsValid(summary)).toBe(true);
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh"))
      .toBe("管理项目\n项目: project:1\n操作: 启动\n请求 ID: request-1");
    for (const targets of [undefined, { ...summary.assistantTargets, operation: "force-stop" },
      { ...summary.assistantTargets, project_id: "project\nforged" },
      { ...summary.assistantTargets, request_id: "x".repeat(129) },
      { ...summary.assistantTargets, extra: true }]) {
      const invalid = { ...summary, assistantTargets: targets };
      expect(projectLifecyclePreviewIsValid(invalid)).toBe(false);
      expect(toolApprovalActionPreview(invalid, "personal_assistant_manage_tool", "zh")).toContain("参数无法核对");
    }
  });
  it("shows the entire write dispatch request and rejects misleading or incomplete details", () => {
    const task = `修改这两个文件\n${"长任务".repeat(300)}\n保留其他内容。`;
    const summary = { assistantAction: "dispatch_write", assistantTargets: { project_id: "project-1", agent_id: "agent-1", dispatch_id: "dispatch-1" },
      assistantRequestedPermission: "workspace_write", assistantTask: task };
    expect(dispatchWritePreviewIsValid(summary)).toBe(true);
    const preview = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
    expect(preview).toContain("项目: project-1");
    expect(preview).toContain("Agent: agent-1");
    expect(preview).toContain("派遣 ID: dispatch-1");
    expect(preview).toContain("申请权限: workspace_write");
    expect(preview.endsWith(task)).toBe(true);
    for (const invalid of [
      { ...summary, assistantTargets: { ...summary.assistantTargets, agent_id: "agent\nforged" } },
      { ...summary, assistantRequestedPermission: "full_access" },
      { ...summary, assistantTask: "altered\u202Etext" },
      { ...summary, assistantTask: "x".repeat(12001) },
      { ...summary, assistantTask: undefined },
      { ...summary, assistantArgumentsInvalid: true },
    ]) {
      expect(dispatchWritePreviewIsValid(invalid)).toBe(false);
      expect(toolApprovalActionPreview(invalid, "personal_assistant_manage_tool", "zh")).toContain("参数无法核对");
    }
  });
  it("names semantic API operations and shows concrete targets and impact", () => {
    const preview = toolApprovalActionPreview({ assistantAction: "provider_update",
      assistantTargets: { provider_id: "local-ai" }, assistantChangedFields: ["enabled"],
      assistantOperationDescription: "修改连接名称、启用状态或地址。", assistantDetailsOmitted: true,
    }, "personal_assistant_manage_tool", "zh");
    expect(preview).toContain("修改模型连接");
    expect(preview).toContain("provider_id: local-ai");
    expect(preview).toContain("修改字段: enabled");
    expect(preview).toContain("修改连接名称、启用状态或地址");
    expect(toolApprovalActionPreview({ assistantAction: "session_archive" }, "personal_assistant_manage_tool", "en"))
      .toContain("Archive session");
    expect(toolApprovalActionPreview({ assistantAction: "http_proxy" }, "personal_assistant_manage_tool", "zh"))
      .toContain("参数无法核对");
  });
  it("shows every authorization upgrade scope and exact project in both languages", () => {
    const scopes = ["knowledge:catalog:read", "teams:directory:read", ...Array.from({ length: 20 }, (_, i) => `scope:${i}`)];
    const summary = { assistantAction: "authorization_upgrade", assistantTargets: { project_id: "project-123" }, assistantAddedScopes: scopes };
    expect(authorizationUpgradePreviewIsValid(summary)).toBe(true);
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh")).toBe(
      ["新增项目权限", "项目: project-123", "新增权限:", ...scopes.map((scope) => `- ${scope}`)].join("\n"));
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en")).toBe(
      ["Add project permissions", "Project: project-123", "Added permissions:", ...scopes.map((scope) => `- ${scope}`)].join("\n"));
  });
  it("rejects absent or unsafe authorization upgrade details", () => {
    const good = { assistantAction: "authorization_upgrade", assistantTargets: { project_id: "project-123" }, assistantAddedScopes: ["source:read"] };
    const invalid: Record<string, unknown>[] = [
      { ...good, assistantTargets: undefined }, { ...good, assistantTargets: { project_id: "" } },
      { ...good, assistantTargets: { project_id: "project\nforged" } },
      { ...good, assistantTargets: { project_id: "project\n" } },
      { ...good, assistantTargets: { project_id: "project\u202Eforged" } },
      { ...good, assistantAddedScopes: undefined }, { ...good, assistantAddedScopes: [] },
      { ...good, assistantAddedScopes: ["source:read", 3] }, { ...good, assistantAddedScopes: [""] },
      { ...good, assistantAddedScopes: ["source:read\nforged"] },
      { ...good, assistantAddedScopes: ["source:read\n"] },
      { ...good, assistantAddedScopes: ["source:read\u202E"] },
      { ...good, assistantAddedScopes: Array(1) },
    ];
    invalid.push({ ...good, assistantArgumentsInvalid: true });
    invalid.push({ ...good, assistantAction: "team_run" });
    expect(authorizationUpgradePreviewIsValid(null)).toBe(false);
    for (const summary of invalid) {
      expect(authorizationUpgradePreviewIsValid(summary)).toBe(false);
      if (summary.assistantAction !== "authorization_upgrade") continue;
      expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh")).toContain("参数无法核对");
      expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en")).toContain("Arguments cannot be verified");
    }
  });
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
it("shows the verified previous assistant for a history import", () => {
  const preview = toolApprovalActionPreview({ assistantAction: "history_import",
    assistantTargets: { sourceProjectId: "fixture-project", instanceId: "fixture-instance", assistantAgentId: "old-pa" },
    assistantOperationDescription: "只读导入所选旧助理的历史会话和附件。" }, "personal_assistant_manage_tool", "zh");
  expect(preview).toContain("导入旧助理历史");
  expect(preview).toContain("项目: fixture-project");
  expect(preview).toContain("旧助理: old-pa");
});
it("shows the verified previous assistant for an affairs sync", () => {
  const preview = toolApprovalActionPreview({ assistantAction: "affairs_sync",
    assistantTargets: { sourceProjectId: "fixture-project", instanceId: "fixture-instance", assistantAgentId: "old-pa" },
    assistantOperationDescription: "同步所选旧助理的个人事务。" }, "personal_assistant_manage_tool", "zh");
  expect(preview).toContain("同步旧助理事务");
  expect(preview).toContain("旧助理: old-pa");
  const recovery = toolApprovalActionPreview({ assistantAction: "affairs_sync",
    assistantTargets: { assistantAgentId: "old-pa", syncId: "affairs-" + "f".repeat(40) },
    assistantOperationDescription: "核对原事务同步回执，不会重新写入事务。" }, "personal_assistant_manage_tool", "zh");
  expect(recovery).toContain("原回执: affairs-");
});
