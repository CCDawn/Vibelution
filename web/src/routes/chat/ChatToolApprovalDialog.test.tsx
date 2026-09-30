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
    expect(markup).toContain('role="list"');
    expect(markup.match(/role="listitem"/g)?.length).toBe(2);
    expect(markup).toContain("shell_command");
    expect(markup).toContain("read_file");
  });
});
