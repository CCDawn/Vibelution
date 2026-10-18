/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VButton, VuiProvider } from "../../components/vui";
import {
  ChatComposerBudgetPopover,
  SESSION_BUDGET_MAX_CALLS_LIMITS,
  SESSION_BUDGET_THINKING_CHARS_LIMITS,
  validateSessionBudgetField,
  type ChatComposerBudgetPanelLabels,
} from "./ChatComposerBudgetPopover";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const labels: ChatComposerBudgetPanelLabels = {
  composerBudgetTitle: "预算与额度",
  composerBudgetDescription: "按会话限制每回合工具调用次数与思考预算字数。",
  composerBudgetMaxCallsLabel: "每回合工具调用额度",
  composerBudgetMaxCallsPlaceholder: "未配置=按模型策略，常见 32",
  composerBudgetClearMaxCalls: "清除工具调用额度，恢复默认",
  composerBudgetThinkingLabel: "思考预算字数",
  composerBudgetThinkingPlaceholder: "未配置=默认 500",
  composerBudgetClearThinking: "清除思考预算，恢复默认",
  composerBudgetSave: "保存",
  composerBudgetCancel: "取消",
  composerBudgetLoading: "读取预算配置…",
  composerBudgetLoadFailed: "预算配置读取失败",
};

describe("validateSessionBudgetField", () => {
  it("treats an empty draft as a valid null (restore defaults)", () => {
    expect(validateSessionBudgetField("", SESSION_BUDGET_MAX_CALLS_LIMITS, "zh"))
      .toEqual({ value: null, valid: true, error: "" });
  });
  it("accepts integers inside the domain", () => {
    expect(validateSessionBudgetField("32", SESSION_BUDGET_MAX_CALLS_LIMITS, "zh"))
      .toEqual({ value: 32, valid: true, error: "" });
    expect(validateSessionBudgetField("4000", SESSION_BUDGET_THINKING_CHARS_LIMITS, "en"))
      .toEqual({ value: 4000, valid: true, error: "" });
  });
  it("rejects non-integers", () => {
    const result = validateSessionBudgetField("3.5", SESSION_BUDGET_MAX_CALLS_LIMITS, "zh");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("整数");
  });
  it("rejects out-of-range values in both languages", () => {
    expect(validateSessionBudgetField("0", SESSION_BUDGET_MAX_CALLS_LIMITS, "zh").error).toContain("不能小于 1");
    expect(validateSessionBudgetField("201", SESSION_BUDGET_MAX_CALLS_LIMITS, "en").error).toContain("200");
    expect(validateSessionBudgetField("49", SESSION_BUDGET_THINKING_CHARS_LIMITS, "zh").valid).toBe(false);
    expect(validateSessionBudgetField("4001", SESSION_BUDGET_THINKING_CHARS_LIMITS, "en").valid).toBe(false);
  });
});

function inputByLabel(label: string): HTMLInputElement | null {
  return document.body.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`);
}

function setInputValue(element: HTMLInputElement, value: string) {
  const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
  proto?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

function buttonByText(text: string): HTMLButtonElement | null {
  return (
    Array.from(document.body.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === text,
    ) ?? null
  );
}

function buttonByAriaLabel(label: string): HTMLButtonElement | null {
  return document.body.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
}

function triggerButton(): HTMLButtonElement | null {
  return document.body.querySelector<HTMLButtonElement>('[data-testid="budget-trigger"]');
}

type PanelHarnessProps = {
  sessionId?: string;
  revision?: number;
  maxCallsPerTurn?: number | null;
  thinkingBudgetChars?: number | null;
  pending?: boolean;
  errorMessage?: string;
  onSave?: ReturnType<typeof vi.fn>;
};

function harnessProps(props: PanelHarnessProps) {
  return {
    lang: "zh" as const,
    labels,
    trigger: (
      <VButton type="button" data-testid="budget-trigger" variant="ghost">
        预算与额度
      </VButton>
    ),
    sessionId: props.sessionId ?? "session-a",
    revision: props.revision === undefined && !("revision" in props) ? 3 : props.revision,
    maxCallsPerTurn: props.maxCallsPerTurn ?? null,
    thinkingBudgetChars: props.thinkingBudgetChars ?? null,
    pending: props.pending ?? false,
    errorMessage: props.errorMessage ?? "",
    onSave: props.onSave ?? vi.fn(),
  };
}

describe("ChatComposerBudgetPopover draft + save contract", () => {
  let root: Root | null = null;
  let container: HTMLDivElement;

  afterEach(async () => {
    await act(async () => root?.unmount());
    container?.remove();
    root = null;
  });

  async function renderPanel(props: PanelHarnessProps = {}, { open = true }: { open?: boolean } = {}) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    const view = (
      <VuiProvider>
        <ChatComposerBudgetPopover {...harnessProps(props)} />
      </VuiProvider>
    );
    await act(async () => root!.render(view));
    if (open) {
      await act(async () => triggerButton()?.click());
    }
    return { root: root!, view };
  }

  it("opens the side panel from the menu-row trigger on click", async () => {
    await renderPanel({}, { open: false });
    expect(document.body.querySelector('[data-testid="chat-composer-budget-popover-body"]')).toBeNull();
    await act(async () => triggerButton()?.click());
    const body = document.body.querySelector('[data-testid="chat-composer-budget-popover-body"]');
    expect(body?.textContent).toContain("预算与额度");
  });

  it("seeds drafts from server values and blocks save until values change", async () => {
    const onSave = vi.fn();
    await renderPanel({ maxCallsPerTurn: 32, thinkingBudgetChars: 500, onSave });
    expect(inputByLabel("每回合工具调用额度")?.value).toBe("32");
    expect(inputByLabel("思考预算字数")?.value).toBe("500");
    expect(buttonByText("保存")?.disabled).toBe(true);

    setInputValue(inputByLabel("每回合工具调用额度")!, "64");
    expect(buttonByText("保存")?.disabled).toBe(false);

    await act(async () => buttonByText("保存")?.click());
    expect(onSave).toHaveBeenCalledExactlyOnceWith({
      revision: 3,
      maxCallsPerTurn: 64,
      thinkingBudgetChars: 500,
    });
  });

  it("submits null for cleared fields and blocks invalid drafts", async () => {
    const onSave = vi.fn();
    await renderPanel({ maxCallsPerTurn: 32, thinkingBudgetChars: 500, onSave });

    await act(async () => buttonByAriaLabel("清除工具调用额度，恢复默认")?.click());
    expect(inputByLabel("每回合工具调用额度")?.value).toBe("");

    setInputValue(inputByLabel("思考预算字数")!, "300");
    await act(async () => buttonByText("保存")?.click());
    expect(onSave).toHaveBeenCalledExactlyOnceWith({
      revision: 3,
      maxCallsPerTurn: null,
      thinkingBudgetChars: 300,
    });

    setInputValue(inputByLabel("思考预算字数")!, "10");
    await act(async () => {});
    expect(document.body.querySelector('[role="alert"]')?.textContent).toContain("不能小于 50");
    expect(buttonByText("保存")?.disabled).toBe(true);
  });

  it("disables every control while a save is pending", async () => {
    await renderPanel({ maxCallsPerTurn: 32, pending: true });
    expect(inputByLabel("每回合工具调用额度")?.disabled).toBe(true);
    expect(inputByLabel("思考预算字数")?.disabled).toBe(true);
    expect(buttonByText("保存")?.disabled).toBe(true);
    expect(buttonByText("取消")?.disabled).toBe(true);
  });

  it("keeps the operator draft across a 409 revision conflict and retries with the fresh revision", async () => {
    const onSave = vi.fn();
    const { root: rootRef } = await renderPanel({ revision: 3, maxCallsPerTurn: 32, thinkingBudgetChars: 500, onSave });

    setInputValue(inputByLabel("每回合工具调用额度")!, "128");

    // Save starts (pending), then a 409 lands: the workbench invalidates and the
    // refreshed query pushes revision 4 with someone else's values.
    await act(async () => rootRef.render(
      <VuiProvider>
        <ChatComposerBudgetPopover {...harnessProps({ revision: 3, maxCallsPerTurn: 32, thinkingBudgetChars: 500, pending: true, onSave })} />
      </VuiProvider>,
    ));
    await act(async () => rootRef.render(
      <VuiProvider>
        <ChatComposerBudgetPopover {...harnessProps({
          revision: 4,
          maxCallsPerTurn: 48,
          thinkingBudgetChars: 500,
          pending: false,
          errorMessage: "配置已被其他修改更新，已刷新为最新值，请基于新值重试",
          onSave,
        })} />
      </VuiProvider>,
    ));

    expect(document.body.textContent).toContain("配置已被其他修改更新");
    // The draft survives the revision refresh.
    expect(inputByLabel("每回合工具调用额度")?.value).toBe("128");
    expect(buttonByText("保存")?.disabled).toBe(false);

    await act(async () => buttonByText("保存")?.click());
    expect(onSave).toHaveBeenCalledExactlyOnceWith({
      revision: 4,
      maxCallsPerTurn: 128,
      thinkingBudgetChars: 500,
    });
  });

  it("resets drafts when the session identity changes", async () => {
    const { root: rootRef } = await renderPanel({ sessionId: "session-a", maxCallsPerTurn: 32, thinkingBudgetChars: 500 });
    setInputValue(inputByLabel("每回合工具调用额度")!, "128");
    expect(inputByLabel("每回合工具调用额度")?.value).toBe("128");

    await act(async () => rootRef.render(
      <VuiProvider>
        <ChatComposerBudgetPopover {...harnessProps({ sessionId: "session-b", maxCallsPerTurn: 8, thinkingBudgetChars: 200 })} />
      </VuiProvider>,
    ));
    expect(inputByLabel("每回合工具调用额度")?.value).toBe("8");
    expect(inputByLabel("思考预算字数")?.value).toBe("200");
    expect(buttonByText("保存")?.disabled).toBe(true);
  });

  it("re-syncs drafts after a successful save settles", async () => {
    const { root: rootRef } = await renderPanel({ maxCallsPerTurn: 32, thinkingBudgetChars: 500 });
    setInputValue(inputByLabel("每回合工具调用额度")!, "64");

    // Pending, then the server confirms the new value without an error.
    await act(async () => rootRef.render(
      <VuiProvider>
        <ChatComposerBudgetPopover {...harnessProps({ maxCallsPerTurn: 32, thinkingBudgetChars: 500, pending: true })} />
      </VuiProvider>,
    ));
    await act(async () => rootRef.render(
      <VuiProvider>
        <ChatComposerBudgetPopover {...harnessProps({ maxCallsPerTurn: 64, thinkingBudgetChars: 500, pending: false })} />
      </VuiProvider>,
    ));
    expect(inputByLabel("每回合工具调用额度")?.value).toBe("64");
    expect(buttonByText("保存")?.disabled).toBe(true);
  });

  it("blocks saving while the budget query has not resolved a revision", async () => {
    await renderPanel({ revision: undefined, maxCallsPerTurn: 32 });
    setInputValue(inputByLabel("每回合工具调用额度")!, "64");
    expect(buttonByText("保存")?.disabled).toBe(true);
  });
});
