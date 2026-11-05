// @vitest-environment happy-dom
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LauncherAssistantQuestionCard, type LauncherAssistantQuestionCardProps } from "./LauncherAssistantQuestionCard";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
let onChange: ReturnType<typeof vi.fn>;
let onSubmit: ReturnType<typeof vi.fn>;
let fetchMock: ReturnType<typeof vi.fn>;
let invoke: ReturnType<typeof vi.fn>;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  onChange = vi.fn();
  onSubmit = vi.fn();
  fetchMock = vi.fn(() => { throw new Error("Question cards must not use HTTP"); });
  invoke = vi.fn(() => { throw new Error("Question cards must not invoke the launcher"); });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(invoke).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});

async function render(props: Partial<LauncherAssistantQuestionCardProps> = {}) {
  await act(async () => root.render(<LauncherAssistantQuestionCard questionId="q-1" questionText="先处理哪一项？"
    value="" onChange={onChange} onSubmit={onSubmit} lang="zh" {...props} />));
}

function input() { return container.querySelector("textarea")!; }
function button() { return container.querySelector("button")!; }
async function submitForm() {
  await act(async () => { container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
}
async function pressEnter(options: KeyboardEventInit = {}) {
  const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true, ...options });
  await act(async () => { input().dispatchEvent(event); });
  return event;
}

describe("LauncherAssistantQuestionCard", () => {
  it("uses controlled text, preserves whitespace, and focuses only when the answer row is clicked", async () => {
    function ControlledCard() {
      const [value, setValue] = useState("");
      return <LauncherAssistantQuestionCard questionId="q-1" questionText="先处理哪一项？" value={value}
        onChange={next => { onChange(next); setValue(next); }} onSubmit={onSubmit} lang="zh" />;
    }
    await act(async () => root.render(<ControlledCard />));
    expect(document.activeElement).not.toBe(input());
    const next = "  先修复显示\n保留草稿  ";
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    await act(async () => {
      setValue.call(input(), next);
      input().dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith(next);
    expect(input().value).toBe(next);
    expect(input().getAttribute("aria-label")).toBe("回答此问题");
    expect(container.querySelector("[data-launcher-assistant-pending-question]")?.getAttribute("data-launcher-assistant-pending-question")).toBe("q-1");
    await act(async () => { (container.querySelector("[data-launcher-assistant-answer-row]") as HTMLElement).click(); });
    expect(document.activeElement).toBe(input());
    expect(onSubmit).not.toHaveBeenCalled();
    await act(async () => button().click());
    expect(onSubmit).toHaveBeenCalledOnce();
    expect(input().value).toBe(next);
  });

  it("blocks whitespace-only answers through both the form and Enter", async () => {
    await render({ value: " \n " });
    expect(button().disabled).toBe(true);
    expect(input().disabled).toBe(false);
    await submitForm();
    await pressEnter();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it.each([{ pending: true }, { disabled: true }, { disabled: true, unconfirmed: true }])(
    "blocks all submission while %j", async state => {
      await render({ value: "保留回答", ...state });
      expect(input().disabled).toBe(true);
      expect(button().disabled).toBe(true);
      await submitForm();
      await pressEnter();
      await act(async () => button().click());
      expect(onSubmit).not.toHaveBeenCalled();
      expect(input().value).toBe("保留回答");
    },
  );

  it("locks an unconfirmed answer and lets the parent retry without changing the value", async () => {
    await render({ value: "原回答", unconfirmed: true, error: "提交结果未确认，请重试。" });
    expect(input().disabled).toBe(true);
    expect(button().disabled).toBe(false);
    expect(button().textContent).toBe("重试");
    const error = container.querySelector('[role="alert"]')!;
    expect(error.textContent).toBe("提交结果未确认，请重试。");
    expect(input().getAttribute("aria-describedby")).toBe(error.id);
    expect(input().getAttribute("aria-invalid")).toBe("true");
    await act(async () => button().click());
    expect(onSubmit).toHaveBeenCalledOnce();
    expect(input().value).toBe("原回答");
    expect(onChange).not.toHaveBeenCalled();

    await render({ value: "", unconfirmed: true, lang: "en" });
    expect(input().getAttribute("aria-label")).toBe("Answer this question");
    expect(button().textContent).toBe("Retry");
    expect(button().disabled).toBe(false);
    await submitForm();
    expect(onSubmit).toHaveBeenCalledTimes(2);
  });

  it("submits on Enter while Shift + Enter and IME confirmation stay in the field", async () => {
    await render({ value: "先处理显示" });
    const shifted = await pressEnter({ shiftKey: true });
    const composing = await pressEnter({ isComposing: true });
    const legacyComposing = await pressEnter({ keyCode: 229 });
    expect(shifted.defaultPrevented).toBe(false);
    expect(composing.defaultPrevented).toBe(false);
    expect(legacyComposing.defaultPrevented).toBe(false);
    expect(onSubmit).not.toHaveBeenCalled();
    const enter = await pressEnter();
    expect(enter.defaultPrevented).toBe(true);
    expect(onSubmit).toHaveBeenCalledOnce();
  });
});
