// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatToolApprovalDialog } from "./ChatToolApprovalDialog";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container!);
});

afterEach(async () => {
  if (root && container) {
    await act(async () => root!.unmount());
  }
  container?.remove();
  container = null;
  root = null;
});

function findButtonByText(text: string): HTMLButtonElement | null {
  const buttons = Array.from(container?.querySelectorAll("button") ?? []);
  return buttons.find((item) => item.textContent?.includes(text)) ?? null;
}

describe("ChatToolApprovalDialog interactions", () => {
  it("fires acceptForSessionTool from the tool-level remember button (b1)", async () => {
    const onApprove = vi.fn();
    const onApproveForSession = vi.fn();
    const onApproveForSessionTool = vi.fn();
    const onReject = vi.fn();
    await act(async () => {
      root!.render(
        <ChatToolApprovalDialog
          lang="zh"
          pending={false}
          rawTitle="exec_command"
          riskLabel="需要审批"
          scopeLabel="本次调用"
          actionPreview="$ pytest -q"
          toolName="exec_command"
          toolLabels={[{ id: "exec_command", label: "exec_command" }]}
          onApprove={onApprove}
          onApproveForSession={onApproveForSession}
          onApproveForSessionTool={onApproveForSessionTool}
          onReject={onReject}
        />,
      );
    });
    const button = findButtonByText("本会话此工具");
    expect(button).not.toBeNull();
    await act(async () => button!.click());
    expect(onApproveForSessionTool).toHaveBeenCalledTimes(1);
    expect(onApproveForSession).not.toHaveBeenCalled();
    expect(onApprove).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
  });

  it("fires acceptWithActionWindow and keeps the grant one-shot (b3)", async () => {
    const onApproveWithActionWindow = vi.fn();
    const onApprove = vi.fn();
    const onReject = vi.fn();
    await act(async () => {
      root!.render(
        <ChatToolApprovalDialog
          lang="zh"
          pending={false}
          rawTitle="personal_assistant_manage_tool"
          riskLabel="需要审批"
          scopeLabel="本次调用"
          actionPreview="创建会话"
          toolName="personal_assistant_manage_tool"
          toolLabels={[{ id: "personal_assistant_manage_tool", label: "平台管理" }]}
          assistantActionWindow={{
            eligible: true,
            remainingSeconds: 0,
            durationSeconds: 14400,
            activeWindows: [],
          }}
          onApprove={onApprove}
          onApproveWithActionWindow={onApproveWithActionWindow}
          onReject={onReject}
        />,
      );
    });
    const button = findButtonByText("同意并授权 4 小时");
    expect(button).not.toBeNull();
    await act(async () => button!.click());
    expect(onApproveWithActionWindow).toHaveBeenCalledTimes(1);
    expect(onApprove).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
  });

  it("disables the new grant buttons while a decision is pending", async () => {
    await act(async () => {
      root!.render(
        <ChatToolApprovalDialog
          lang="zh"
          pending
          rawTitle="exec_command"
          riskLabel="需要审批"
          scopeLabel="本次调用"
          toolName="exec_command"
          toolLabels={[{ id: "exec_command", label: "exec_command" }]}
          onApprove={() => undefined}
          onApproveForSession={() => undefined}
          onApproveForSessionTool={() => undefined}
          onApproveWithActionWindow={() => undefined}
          onReject={() => undefined}
        />,
      );
    });
    const buttons = Array.from(container?.querySelectorAll("button") ?? []);
    expect(buttons.length).toBeGreaterThan(0);
    expect(buttons.every((button) => button.hasAttribute("disabled"))).toBe(true);
  });
});
