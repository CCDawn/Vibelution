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
      rawTitle: "web_fetch_tool",
      riskLabel: "需要审批",
      scopeLabel: "当前会话",
      actionPreview: "https://example.com/research",
      sessionGrantScope: { kind: "exact_arguments" },
      toolName: "web_fetch_tool",
      toolLabels: [
        { id: "web_fetch_tool", label: "web_fetch" },
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
    expect(markup).toContain("https://example.com/research");
    // web_fetch keeps the durable always-tier; the copy states the origin scope.
    expect(markup).toContain("同一来源");
    expect(markup).not.toContain("是=本次");
    expect(markup.match(/Y 是 · A 始终 · N 否/g)?.length).toBe(1);
    expect(markup).toContain('role="list"');
    expect(markup.match(/role="listitem"/g)?.length).toBe(1);
    expect(markup).toContain("web_fetch");
  });

  it("maps the always button to the tool-session tier for shell/file tools (A2b)", () => {
    const markup = renderToStaticMarkup(createElement(ChatToolApprovalDialog, {
      lang: "zh",
      pending: false,
      rawTitle: "shell_command",
      riskLabel: "需要审批",
      scopeLabel: "本次调用",
      actionPreview: "$ pytest -q",
      sessionGrantScope: { kind: "shell_command_family", "family": "pytest" },
      toolName: "exec_command",
      toolLabels: [{ id: "exec_command", label: "exec_command" }],
      onApprove: () => undefined,
      onApproveForSession: () => undefined,
      onApproveForDevelopmentBundle: () => undefined,
      onReject: () => undefined,
    }));

    // The copy must match the actual decision: session-scoped tool grant.
    expect(markup).toContain("本会话此工具");
    expect(markup).toContain("本会话内此工具不再询问（A）");
    expect(markup).not.toContain("始终（此 Agent）");
    expect(markup).not.toContain("参数完全相同");
    expect(markup).toContain("本会话信任开发操作");
    expect(markup).toContain('data-chat-approval-accept-session="tool-session"');
    expect(markup).toContain('data-chat-approval-trust-development-session="true"');
  });

  it("keeps compact previews by default and offers an explicitly scrollable full preview", () => {
    const content = ["项目: project-a", ...Array.from({ length: 30 }, (_, i) => `scope:${i}`)].join("\n");
    const props = {
      lang: "zh" as const, pending: false, rawTitle: "personal_assistant_manage_tool", riskLabel: "需要审批",
      scopeLabel: "本次调用", actionPreview: content, toolName: "personal_assistant_manage_tool",
      toolLabels: [{ id: "personal_assistant_manage_tool", label: "平台管理" }],
      onApprove: () => undefined, onReject: () => undefined,
    };
    const compact = renderToStaticMarkup(createElement(ChatToolApprovalDialog, props));
    const expanded = renderToStaticMarkup(createElement(ChatToolApprovalDialog, { ...props, fullActionPreview: true }));
    const compactPre = compact.match(/<pre\b[^>]*>/)?.[0] || "";
    const expandedPre = expanded.match(/<pre\b[^>]*>/)?.[0] || "";
    expect(compactPre).toContain("[-webkit-line-clamp:2]");
    expect(compactPre).not.toContain('tabindex="0"');
    expect(expandedPre).toContain("overflow-y-auto");
    expect(expandedPre).toContain("max-h-48");
    expect(expandedPre).toContain('tabindex="0"');
    expect(expandedPre).not.toContain("line-clamp");
    expect(expandedPre).not.toContain("overflow-hidden");
    expect(expanded).toContain("scope:0");
    expect(expanded).toContain("scope:29");
    expect(expanded).toContain("是");
    expect(expanded).toContain("否");
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
