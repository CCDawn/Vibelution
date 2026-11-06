// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatGPTSubscriptionApiError } from "../../api/chatgptSubscription";
import type { ChatGPTSubscriptionModels, ChatGPTSubscriptionStatus } from "../../api/types/chatgptSubscription";
import { ChatGPTSubscriptionPanel, type AddSubscriptionModels } from "./ChatGPTSubscriptionPanel";
import { useChatGPTSubscription } from "./useChatGPTSubscription";
import { subscriptionErrorContent, CHATGPT_SUBSCRIPTION_COPY } from "./chatgptSubscriptionCopy";
import registrySource from "../ConfigProviderRegistryPanel.tsx?raw";

vi.mock("./useChatGPTSubscription", () => ({ useChatGPTSubscription: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const status: ChatGPTSubscriptionStatus = {
  state: "connected", connected: true, account: { subject: "private-subject", email: "person@example.com" }, expiresAt: null, lastError: null, login: null,
};
const catalog: ChatGPTSubscriptionModels = {
  models: [{ slug: "actual-model", display_name: "Account model", visibility: "list", supported_in_api: true, context_window: 128000, input_modalities: ["text"], supported_reasoning_levels: [{ effort: "high" }] }],
  provider: { auth: "oauth:chatgpt", driver: "chatgpt_subscription" },
};
let state: ReturnType<typeof useChatGPTSubscription>;
let container: HTMLDivElement;
let root: Root;
let add: AddSubscriptionModels;

async function render(language: "zh" | "en" = "zh", setupBlockedReason?: string) {
  vi.mocked(useChatGPTSubscription).mockReturnValue(state);
  await act(async () => root.render(<MemoryRouter><ChatGPTSubscriptionPanel language={language} setupBlockedReason={setupBlockedReason} onAddModels={add} /></MemoryRouter>));
}
function button(label: string) { return [...container.querySelectorAll("button")].find((item) => item.textContent?.includes(label))!; }

beforeEach(() => {
  state = {
    statusQuery: { data: status, error: null, isPending: false, isError: false },
    modelsQuery: { data: catalog, error: null, isPending: false, isSuccess: true, isError: false, isFetching: false },
    authorization: null, manualAuthorization: false, actionError: null, disconnectNotice: null,
    pending: false, commandPending: false, starting: false, cancelling: false, disconnecting: false,
    startLogin: vi.fn(), cancelLogin: vi.fn(), reopenAuthorization: vi.fn(), disconnect: vi.fn(), refresh: vi.fn(),
  } as unknown as ReturnType<typeof useChatGPTSubscription>;
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  add = vi.fn().mockResolvedValue(undefined);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.clearAllMocks(); });

describe("ChatGPT subscription card", () => {
  it("renders only the real account and catalog without claiming a subscription tier or model verification", async () => {
    await render();
    expect(container.textContent).toContain("person@example.com");
    expect(container.textContent).toContain("Account model");
    expect(container.textContent).toContain("模型是否可用以实际调用结果为准");
    expect(container.textContent).not.toMatch(/private-subject|Pro|GPT-5|demo@|access_token/);
    expect(button("添加所选模型").disabled).toBe(true);
    const toggle = container.querySelector<HTMLInputElement>('input[role="switch"]') ?? container.querySelector<HTMLInputElement>('input[type="checkbox"]');
    expect(toggle).not.toBeNull();
    await act(async () => toggle!.click());
    await act(async () => button("添加所选模型").click());
    expect(add).toHaveBeenCalledWith(catalog.models, catalog.provider);
    expect(container.textContent).toContain("原有默认保持不变");
  });

  it("retains the selected model through quota, network and reauthorization failures, and keeps failed saves retryable", async () => {
    await render();
    const toggle = container.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    await act(async () => toggle.click());
    for (const code of ["rate_limited", "network", "reauth_required"]) {
      state = { ...state, actionError: new ChatGPTSubscriptionApiError(code), statusQuery: { ...state.statusQuery, data: code === "reauth_required" ? { ...status, connected: false, state: "reauth_required" } : status } };
      await render();
      expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
      expect(container.querySelector('[role="alert"]')).not.toBeNull();
    }
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')?.disabled).toBe(true);
    state = { ...state, actionError: null, statusQuery: { ...state.statusQuery, data: status } };
    add = vi.fn().mockRejectedValue(new Error("apply failed")); await render();
    await act(async () => button("添加所选模型").click());
    expect(container.textContent).toContain("模型暂未保存");
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
    expect(button("添加所选模型").disabled).toBe(false);
  });

  it("shows the explicit unconfirmed remote revocation notice and bilingual copy", async () => {
    state = { ...state, disconnectNotice: "local_only" };
    await render(); expect(container.textContent).toContain("远端撤销尚未确认");
    await render("en"); expect(container.textContent).toContain("Remote revocation is not confirmed");
    expect(container.textContent).toContain("Model availability is confirmed by an actual request");
  });

  it("keeps the subscription panel behind the optional integration callback", () => {
    expect(registrySource).toContain("onAddSubscriptionModels?: AddSubscriptionModels");
    expect(registrySource).toContain("{onAddSubscriptionModels ? <ChatGPTSubscriptionPanel");
    expect(registrySource).toContain("setupBlockedReason={subscriptionSetupBlockedReason}");
  });

  it("blocks only adding while another settings draft is pending and retains selection after unblocking", async () => {
    const reason = "请先保存或还原其他设置草稿，再添加订阅模型";
    await render();
    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await render("zh", reason);
    expect(container.textContent).toContain(reason);
    const toggle = container.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    expect(toggle.checked).toBe(true);
    expect(toggle.disabled).toBe(false);
    expect(button("断开连接").disabled).toBe(false);
    expect(button("添加所选模型").disabled).toBe(true);
    await act(async () => button("添加所选模型").click());
    expect(add).not.toHaveBeenCalled();
    await act(async () => toggle.click());
    expect(toggle.checked).toBe(false);
    await act(async () => toggle.click());
    await render();
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
    expect(button("添加所选模型").disabled).toBe(false);
    await act(async () => button("添加所选模型").click());
    expect(add).toHaveBeenCalledWith(catalog.models, catalog.provider);
  });

  it("keeps official sign-in available while model setup is blocked", async () => {
    state = { ...state, statusQuery: { ...state.statusQuery, data: { ...status, state: "signed_out", connected: false, account: null } } };
    await render("zh", "请先保存或还原其他设置草稿，再添加订阅模型");
    expect(button("Continue with ChatGPT").disabled).toBe(false);
    await act(async () => button("Continue with ChatGPT").click());
    expect(state.startLogin).toHaveBeenCalledOnce();
    expect(add).not.toHaveBeenCalled();
  });

  it("allows signing in after logout when the backend retains the registered account", async () => {
    state = { ...state, statusQuery: { ...state.statusQuery, data: { ...status, state: "signed_out", connected: false, lastError: null } } };
    await render("zh", "请先保存或还原其他设置草稿，再添加订阅模型");
    expect(container.textContent).toContain("person@example.com");
    const connect = button("Continue with ChatGPT");
    expect(connect).toBeDefined();
    expect(connect.disabled).toBe(false);
    await act(async () => connect.click());
    expect(state.startLogin).toHaveBeenCalledOnce();
    expect(button("添加所选模型").disabled).toBe(true);
  });

  it("offers reauthorization for a remembered account and cancellation while its next login is pending", async () => {
    state = { ...state, statusQuery: { ...state.statusQuery, data: { ...status, state: "reauth_required", connected: false, lastError: null } } };
    await render();
    const relogin = button("重新登录");
    expect(relogin.disabled).toBe(false);
    await act(async () => relogin.click());
    expect(state.startLogin).toHaveBeenCalledOnce();
    state = { ...state, pending: true, statusQuery: { ...state.statusQuery, data: { ...status, state: "signed_out", connected: false, login: { attemptId: "attempt-identity-2", state: "pending", expiresAt: "2026-11-06T12:00:00Z" } } } };
    await render();
    expect(button("Continue with ChatGPT")).toBeUndefined();
    expect(button("取消授权").disabled).toBe(false);
    await act(async () => button("取消授权").click());
    expect(state.cancelLogin).toHaveBeenCalledOnce();
  });

  it("offers distinct recovery for quota, authorization and network failures", () => {
    expect(subscriptionErrorContent("rate_limited", CHATGPT_SUBSCRIPTION_COPY.zh).recovery).toBe("usage");
    expect(subscriptionErrorContent("reauth_required", CHATGPT_SUBSCRIPTION_COPY.en).recovery).toBe("login");
    expect(subscriptionErrorContent("network", CHATGPT_SUBSCRIPTION_COPY.zh).recovery).toBe("retry");
  });
});
