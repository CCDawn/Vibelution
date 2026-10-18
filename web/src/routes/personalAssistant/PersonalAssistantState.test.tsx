// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PersonalAssistantState } from "./PersonalAssistantState";
import type { usePersonalAssistant } from "./usePersonalAssistant";

let mockLang: "zh" | "en" = "zh";
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: mockLang }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type AssistantState = ReturnType<typeof usePersonalAssistant>;
function assistantState(overrides: Record<string, unknown>): AssistantState {
  return {
    selectionMismatch: false,
    ready: false,
    setup: { error: null, isError: false, isPending: false, refetch: vi.fn() },
    binding: { error: null, isSuccess: false, isPending: false, refetch: vi.fn() },
    route: { selection: { kind: "session" } },
    ...overrides,
  } as unknown as AssistantState;
}
const mismatchState = () => assistantState({
  selectionMismatch: true,
  assistant: { directSessionId: "personal-session" },
  route: { selection: { kind: "session" }, openSession: vi.fn() },
});

let root: Root, container: HTMLDivElement;
beforeEach(() => {
  mockLang = "zh";
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
async function render(state: AssistantState) { await act(async () => root.render(<PersonalAssistantState state={state} />)); }

describe("personal assistant state surfaces", () => {
  it("keeps the original Chinese copy for the selection mismatch entrance", async () => {
    await render(mismatchState());
    expect(document.body.textContent).toContain("会话与个人助理身份不匹配");
    expect(document.body.textContent).toContain("这个入口只接受个人助理自己的原生会话。");
    expect([...document.querySelectorAll("button")].some(button => button.textContent === "返回个人助理会话")).toBe(true);
  });

  it("localizes state surfaces to the active shell language", async () => {
    mockLang = "en";
    await render(mismatchState());
    expect(document.body.textContent).toContain("Session does not match the personal assistant");
    expect(document.body.textContent).toContain("This entrance only accepts the personal assistant's own native session.");
    await render(assistantState({ setup: { error: "offline", isError: false, isPending: false, refetch: vi.fn() } }));
    expect(document.body.textContent).toContain("The personal assistant cannot connect right now");
    expect(document.body.textContent).toContain("Please try again later.");
  });

  it("shows the recovery surface when nothing is ready", async () => {
    await render(assistantState({}));
    expect(document.body.textContent).toContain("个人助理需要恢复");
    expect(document.body.textContent).toContain("智能体与会话绑定尚未就绪，暂时不能开始聊天。");
  });
});
