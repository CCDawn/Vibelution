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
  it("renders the composer decision once, retaining the complete recovery preview in details", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onApproveForSession = vi.fn();
    const preview = "重新授权旧提醒交接\n原记录保留。\n来源项目: project-a\n来源实例: instance-a\n来源助理: agent-a\n原操作 ID: initial-123\n当前来源快照摘要: deadbeef\n旧进程状态尚未证明。";
    await act(async () => root!.render(<ChatToolApprovalDialog lang="zh" variant="composer" pending={false}
      rawTitle="manage" riskLabel="需审批" scopeLabel="仅本次" toolLabels={[]} actionPreview={preview}
      argumentSummary={{ assistantAction: "reminder_handoff_recover" }} onApprove={onApprove} onApproveForSession={onApproveForSession} onReject={onReject} />));
    const dialog = container!.querySelector('[role="dialog"]')!;
    expect(dialog.querySelector("h2")?.textContent).toBe("允许重新授权旧提醒交接吗？");
    expect(dialog.querySelector("p")?.textContent).toContain("来源项目: project-a");
    expect(dialog.querySelector("p")?.textContent).not.toContain("deadbeef");
    expect(dialog.querySelector("details")?.textContent).toContain(preview);
    expect(container?.textContent).not.toContain("始终");
    await act(async () => findButtonByText("允许本次")!.click());
    await act(async () => (container!.querySelector('button[aria-label="拒绝并关闭"]') as HTMLButtonElement).click());
    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(1);
    expect(onApproveForSession).not.toHaveBeenCalled();
  });

  it("keeps composer shortcuts scoped and honors pending and disabled decisions", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const props = { lang: "zh" as const, variant: "composer" as const, rawTitle: "run", riskLabel: "审批", scopeLabel: "本次", toolLabels: [], onApprove, onReject };
    await act(async () => root!.render(<ChatToolApprovalDialog {...props} pending={false} approveDisabled rejectDisabled />));
    const dialog = container!.querySelector('[role="dialog"]')!;
    const dispatch = (target: Element | Window, key: string, init: KeyboardEventInit = {}) => target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, ...init }));
    await act(async () => { dispatch(dialog, "1"); dispatch(dialog, "2"); (container!.querySelector('button[aria-label="拒绝并关闭"]') as HTMLButtonElement).click(); });
    expect(onApprove).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
    await act(async () => root!.render(<ChatToolApprovalDialog {...props} pending />));
    expect(Array.from(container!.querySelectorAll("button")).every((button) => button.disabled)).toBe(true);
    await act(async () => dispatch(dialog, "y"));
    expect(onApprove).not.toHaveBeenCalled();
    await act(async () => root!.render(<ChatToolApprovalDialog {...props} pending={false} />));
    const input = document.createElement("textarea");
    dialog.appendChild(input);
    await act(async () => { dispatch(window, "1"); dispatch(dialog, "1", { ctrlKey: true }); dispatch(input, "1"); dispatch(dialog, "1"); dispatch(dialog, "2"); });
    input.remove();
    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  it("ignores shortcuts outside the composer card and guards decisions inside it", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const props = { lang: "zh" as const, variant: "composer" as const, rawTitle: "run", riskLabel: "审批", scopeLabel: "本次", toolLabels: [], onApprove, onReject };
    await act(async () => root!.render(<ChatToolApprovalDialog {...props} pending={false} />));
    const dialog = container!.querySelector('[role="dialog"]')!;
    const dispatch = (target: Element | Window, key: string, init: KeyboardEventInit = {}) => target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }));
    const editable = ["input", "textarea", "select", "div"].map((tag) => {
      const element = document.createElement(tag);
      if (tag === "div") element.setAttribute("contenteditable", "true");
      document.body.appendChild(element);
      return element;
    });
    await act(async () => {
      for (const element of editable) { dispatch(element, "y"); dispatch(element, "n"); }
      dispatch(window, "y", { ctrlKey: true }); dispatch(window, "n", { shiftKey: true });
      dispatch(window, "y", { repeat: true });
      const prevented = new KeyboardEvent("keydown", { key: "y", cancelable: true });
      prevented.preventDefault(); window.dispatchEvent(prevented);
    });
    expect(onApprove).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
    const outsideButton = document.createElement("button");
    document.body.appendChild(outsideButton);
    await act(async () => { dispatch(window, "y"); dispatch(window, "n"); dispatch(window, "Escape"); dispatch(outsideButton, "y"); dispatch(outsideButton, "n"); dispatch(outsideButton, "Escape"); });
    expect(onApprove).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
    await act(async () => { dispatch(dialog, "y"); dispatch(dialog, "n"); dispatch(dialog, "Escape"); });
    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(2);
    await act(async () => root!.render(<ChatToolApprovalDialog {...props} pending={false} approveDisabled rejectDisabled />));
    await act(async () => { dispatch(dialog, "y"); dispatch(dialog, "n"); dispatch(dialog, "Escape"); });
    await act(async () => root!.render(<ChatToolApprovalDialog {...props} pending />));
    await act(async () => { dispatch(dialog, "y"); dispatch(dialog, "n"); });
    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(2);
    outsideButton.remove();
    editable.forEach((element) => element.parentNode?.removeChild(element));
    expect(dialog.querySelector("[data-approval-full-preview]")?.closest("[data-approval-scroll-body]")).not.toBeNull();
  });

  it("keeps dispatch arguments in details while showing the target and blocked explanation", async () => {
    const preview = "项目: project-a\nAgent: agent-a\n派遣 ID: dispatch-a\n目标动作摘要（不完整）:\n{\"path\":\"x\"}\n完整操作不可用，不能批准；你仍可拒绝本次请求。";
    await act(async () => root!.render(<ChatToolApprovalDialog lang="zh" variant="composer" pending={false} approveDisabled
      rawTitle="read_file_tool" riskLabel="审批" scopeLabel="目标任务 · 仅本次" toolLabels={[{ id: "read_file_tool", label: "读取文件" }]}
      actionPreview={preview} onApprove={() => {}} onReject={() => {}} />));
    const dialog = container!.querySelector('[role="dialog"]')!;
    expect(dialog.querySelector("h2")?.textContent).toBe("本次操作暂不能批准");
    expect(dialog.querySelector("p")?.textContent).toContain("项目: project-a");
    expect(dialog.querySelector("p")?.textContent).toContain("完整操作不可用");
    expect(dialog.querySelector("p")?.textContent).not.toContain("dispatch-a");
    expect(dialog.querySelector("details")?.textContent).toContain(preview);
  });

  it("disables rejection button and shortcuts when its identity cannot be bound", async () => {
    const onReject = vi.fn();
    await act(async () => root!.render(<ChatToolApprovalDialog lang="zh" pending={false} approveDisabled rejectDisabled
      rawTitle="exec_command" riskLabel="审批" scopeLabel="本次" toolLabels={[]} onApprove={() => {}} onReject={onReject} />));
    expect(findButtonByText("否")?.disabled).toBe(true);
    await act(async () => { findButtonByText("否")?.click(); window.dispatchEvent(new KeyboardEvent("keydown", { key: "n" })); window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(onReject).not.toHaveBeenCalled();
    expect(container?.textContent).not.toContain("处理中");
  });

  it("keeps both decision buttons usable with a full preview", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const content = Array.from({ length: 30 }, (_, i) => `scope:${i}`).join("\n");
    await act(async () => {
      root!.render(
        <ChatToolApprovalDialog lang="zh" pending={false} rawTitle="personal_assistant_manage_tool"
          riskLabel="需要审批" scopeLabel="本次调用" actionPreview={content} fullActionPreview
          toolName="personal_assistant_manage_tool" toolLabels={[{ id: "personal_assistant_manage_tool", label: "平台管理" }]}
          onApprove={onApprove} onReject={onReject} />,
      );
    });
    const preview = container!.querySelector("pre");
    expect(preview?.textContent).toBe(content);
    expect(preview?.tabIndex).toBe(0);
    await act(async () => findButtonByText("是")!.click());
    await act(async () => findButtonByText("否")!.click());
    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  it("blocks all approvals and shortcuts while keeping rejection available", async () => {
    const onApprove = vi.fn();
    const onApproveForSession = vi.fn();
    const onApproveForSessionTool = vi.fn();
    const onApproveWithActionWindow = vi.fn();
    const onReject = vi.fn();
    await act(async () => {
      root!.render(
        <ChatToolApprovalDialog lang="zh" pending={false} approveDisabled rawTitle="personal_assistant_manage_tool"
          riskLabel="需要审批" scopeLabel="本次调用" actionPreview="参数无法核对" fullActionPreview
          toolName="personal_assistant_manage_tool" toolLabels={[{ id: "personal_assistant_manage_tool", label: "平台管理" }]}
          onApprove={onApprove} onApproveForSession={onApproveForSession}
          onApproveForSessionTool={onApproveForSessionTool} onApproveWithActionWindow={onApproveWithActionWindow}
          onReject={onReject} />,
      );
    });
    for (const text of ["是", "始终（此 Agent）", "本会话此工具", "同意并授权 4 小时"]) {
      const button = findButtonByText(text);
      expect(button?.disabled).toBe(true);
      await act(async () => button!.click());
    }
    expect(findButtonByText("否")?.disabled).toBe(false);
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })));
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true })));
    expect(onApprove).not.toHaveBeenCalled();
    expect(onApproveForSession).not.toHaveBeenCalled();
    expect(onApproveForSessionTool).not.toHaveBeenCalled();
    expect(onApproveWithActionWindow).not.toHaveBeenCalled();
    await act(async () => findButtonByText("否")!.click());
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "n", bubbles: true })));
    expect(onReject).toHaveBeenCalledTimes(2);
  });

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
          rawTitle="web_search_tool"
          riskLabel="需要审批"
          scopeLabel="本次调用"
          actionPreview="query"
          toolName="web_search_tool"
          toolLabels={[{ id: "web_search_tool", label: "web_search" }]}
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

  it("fires the session-scoped always mapping for shell tools and the dev bundle (A2b/b3)", async () => {
    const onApprove = vi.fn();
    const onApproveForSession = vi.fn();
    const onApproveForDevelopmentBundle = vi.fn();
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
          onApproveForDevelopmentBundle={onApproveForDevelopmentBundle}
          onReject={onReject}
        />,
      );
    });
    // Real bridge props: the "A" button itself is the tool-session action for
    // shell tools; the standalone tool-session button is not provided again.
    const alwaysButton = findButtonByText("本会话此工具");
    expect(alwaysButton?.getAttribute("data-chat-approval-accept-session")).toBe("tool-session");
    expect(container?.querySelector('[data-chat-approval-accept-tool-session="true"]')).toBeNull();
    await act(async () => alwaysButton!.click());
    expect(onApproveForSession).toHaveBeenCalledTimes(1);

    // b3 one click: trust every execute/write development tool for the session.
    const bundleButton = findButtonByText("本会话信任开发操作");
    expect(bundleButton?.getAttribute("data-chat-approval-trust-development-session")).toBe("true");
    await act(async () => bundleButton!.click());
    expect(onApproveForDevelopmentBundle).toHaveBeenCalledTimes(1);
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
