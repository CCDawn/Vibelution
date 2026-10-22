import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatToolApprovalDialog } from "./ChatToolApprovalDialog";

describe("ChatToolApprovalDialog", () => {
  it("marks a resolving approval as busy without dropping the dialog", () => {
    const markup = renderToStaticMarkup(createElement(ChatToolApprovalDialog, {
      lang: "en",
      pending: true,
      rawTitle: "very_long_tool_name_that_should_wrap_inside_the_dialog_surface",
      riskLabel: "Approval required",
      scopeLabel: "current session",
      toolLabels: [
        { id: "long", label: "very_long_tool_name_that_should_wrap_inside_the_dialog_surface" },
      ],
      onApprove: () => undefined,
      onReject: () => undefined,
    }));

    expect(markup).toContain('role="dialog"');
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain("Resolving");
    expect(markup).toContain("Allow this action?");
    expect(markup.match(/disabled=""/g)?.length).toBe(2);
    expect(markup).toContain("very_long_tool_name_that_should_wrap_inside_the_dialog_surface");
  });

  it("renders labels, the command preview, and tools as one accessible dialog", () => {
    const markup = renderToStaticMarkup(createElement(ChatToolApprovalDialog, {
      lang: "zh",
      pending: false,
      rawTitle: "shell_command, read_file",
      riskLabel: "需要审批",
      scopeLabel: "当前会话",
      actionPreview: '$ .\\.venv\\Scripts\\python.exe -c "print(123)"\ncwd: C:\\workspace\\repo',
      sessionGrantScope: { kind: "exact_arguments" },
      toolName: "exec_command",
      toolLabels: [
        { id: "shell", label: "shell_command" },
        { id: "read", label: "read_file" },
      ],
      onApprove: () => undefined,
      onApproveForSession: () => undefined,
      onReject: () => undefined,
    }));

    expect(markup).toContain('role="dialog"');
    expect(markup).not.toContain('aria-modal="true"');
    expect(markup).toContain("aria-labelledby=");
    expect(markup).toContain("aria-describedby=");
    expect(markup).toContain("允许执行？");
    expect(markup).toContain("是");
    expect(markup).toContain("始终（此 Agent）");
    expect(markup).toContain("否");
    expect(markup).toContain("需要审批");
    expect(markup).toContain("当前会话");
    expect(markup).toContain("python.exe -c");
    expect(markup).toContain("C:\\workspace\\repo");
    expect(markup).toContain("参数完全相同");
    expect(markup).not.toContain("是=本次");
    expect(markup.match(/Y 是 · A 始终 · N 否/g)?.length).toBe(1);
    expect(markup).toContain('role="list"');
    expect(markup.match(/role="listitem"/g)?.length).toBe(2);
    expect(markup).toContain("shell_command");
    expect(markup).toContain("read_file");
  });

  it("offers the tool-level session grant only when the handler is provided", () => {
    const markup = renderToStaticMarkup(createElement(ChatToolApprovalDialog, {
      lang: "zh",
      pending: false,
      rawTitle: "exec_command",
      riskLabel: "需要审批",
      scopeLabel: "本次调用",
      actionPreview: "$ pytest -q",
      toolName: "exec_command",
      toolLabels: [{ id: "exec_command", label: "exec_command" }],
      onApprove: () => undefined,
      onApproveForSession: () => undefined,
      onApproveForSessionTool: () => undefined,
      onReject: () => undefined,
    }));

    expect(markup).toContain("本会话此工具");
    expect(markup).toContain('data-chat-approval-accept-tool-session="true"');
  });

  it("does not offer the tool-level grant without the handler (CUA / risky tools)", () => {
    const markup = renderToStaticMarkup(createElement(ChatToolApprovalDialog, {
      lang: "zh",
      pending: false,
      rawTitle: "personal_assistant_computer_action_tool",
      riskLabel: "逐次审批",
      scopeLabel: "本次调用",
      toolName: "personal_assistant_computer_action_tool",
      toolLabels: [{ id: "personal_assistant_computer_action_tool", label: "电脑操控" }],
      onApprove: () => undefined,
      onApproveForSession: () => undefined,
      onReject: () => undefined,
    }));

    expect(markup).not.toContain("本会话此工具");
    expect(markup).not.toContain("data-chat-approval-accept-tool-session");
  });

  it("shows the action-window grant and remaining delegated time for manage approvals", () => {
    const markup = renderToStaticMarkup(createElement(ChatToolApprovalDialog, {
      lang: "zh",
      pending: false,
      rawTitle: "personal_assistant_manage_tool",
      riskLabel: "需要审批",
      scopeLabel: "本次调用",
      actionPreview: "创建会话",
      toolName: "personal_assistant_manage_tool",
      toolLabels: [{ id: "personal_assistant_manage_tool", label: "平台管理" }],
      assistantActionWindow: {
        eligible: true,
        remainingSeconds: 0,
        durationSeconds: 14400,
        activeWindows: [
          { action: "session_stop", remainingSeconds: 7380 },
        ],
      },
      onApprove: () => undefined,
      onApproveWithActionWindow: () => undefined,
      onReject: () => undefined,
    }));

    expect(markup).toContain("同意并授权 4 小时");
    expect(markup).toContain('data-chat-approval-accept-action-window="true"');
    expect(markup).toContain("停止会话任务：授权剩余 2 小时 3 分");
  });

  it("omits the action-window surface without the handler or active windows", () => {
    const markup = renderToStaticMarkup(createElement(ChatToolApprovalDialog, {
      lang: "zh",
      pending: false,
      rawTitle: "exec_command",
      riskLabel: "需要审批",
      scopeLabel: "本次调用",
      toolName: "exec_command",
      toolLabels: [{ id: "exec_command", label: "exec_command" }],
      assistantActionWindow: {
        eligible: false,
        remainingSeconds: 0,
        durationSeconds: 14400,
        activeWindows: [],
      },
      onApprove: () => undefined,
      onApproveForSession: () => undefined,
      onReject: () => undefined,
    }));

    expect(markup).not.toContain("同意并授权 4 小时");
    expect(markup).not.toContain("data-chat-approval-accept-action-window");
  });
});
