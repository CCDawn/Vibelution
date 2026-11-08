import { afterEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests, seedControlTokenForTests } from "./client";
import {
  cancelChatGPTSubscriptionLogin, CHATGPT_SUBSCRIPTION_USAGE_URL, ChatGPTSubscriptionApiError, fetchChatGPTSubscriptionModels,
  fetchChatGPTSubscriptionStatus, isChatGPTSubscriptionAuthorizationUrl, logoutChatGPTSubscription, startChatGPTSubscriptionLogin,
} from "./chatgptSubscription";
import apiSource from "./chatgptSubscription.ts?raw";
import panelSource from "../routes/config/ChatGPTSubscriptionPanel.tsx?raw";
import hookSource from "../routes/config/useChatGPTSubscription.ts?raw";

afterEach(() => { vi.unstubAllGlobals(); resetControlTokenForTests(); });

describe("ChatGPT subscription transport", () => {
  it("owns the named endpoints and preserves cancellation attempt identity", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;
    await fetchChatGPTSubscriptionStatus(signal);
    await startChatGPTSubscriptionLogin();
    await cancelChatGPTSubscriptionLogin("attempt-identity-1234");
    await logoutChatGPTSubscription();
    await fetchChatGPTSubscriptionModels(signal);
    expect(fetchMock.mock.calls.map((call) => (call as unknown[])[0])).toEqual([
      "/api/config/chatgpt-subscription/status", "/api/config/chatgpt-subscription/login",
      "/api/config/chatgpt-subscription/cancel", "/api/config/chatgpt-subscription/logout", "/api/config/chatgpt-subscription/models",
    ]);
    const requests = fetchMock.mock.calls as unknown as Array<[string, RequestInit]>;
    expect(requests[0][1].signal).toBe(signal);
    expect(requests[1][1]).toMatchObject({ method: "POST" });
    expect(requests[1][1].body).toBeUndefined();
    expect(JSON.parse(String(requests[2][1].body))).toEqual({ attemptId: "attempt-identity-1234" });
    expect(requests[3][1]).toMatchObject({ method: "POST" });
    expect(requests[4][1].signal).toBe(signal);
  });

  it("normalizes safe domain errors without exposing transport details", async () => {
    seedControlTokenForTests();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { code: "reauth_required", message: "safe error" } }), { status: 409, headers: { "content-type": "application/json" } })));
    await expect(fetchChatGPTSubscriptionModels()).rejects.toMatchObject({ name: "ChatGPTSubscriptionApiError", code: "reauth_required", status: 409 });
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("private upstream body"); }));
    await expect(startChatGPTSubscriptionLogin()).rejects.toEqual(new ChatGPTSubscriptionApiError("network"));
  });

  it("only accepts the official authorization endpoint", () => {
    expect(isChatGPTSubscriptionAuthorizationUrl("https://auth.openai.com/api/accounts/authorize?state=opaque")).toBe(true);
    for (const url of ["javascript:alert(1)", "https://evil.example/", "https://auth.openai.com.evil.example/api/accounts/authorize", "https://x:secret@auth.openai.com/api/accounts/authorize", "http://auth.openai.com/api/accounts/authorize", "https://auth.openai.com/other"]) {
      expect(isChatGPTSubscriptionAuthorizationUrl(url)).toBe(false);
    }
  });

  it("uses the official account usage page", () => {
    expect(CHATGPT_SUBSCRIPTION_USAGE_URL).toBe("https://chatgpt.com/settings/usage");
  });

  it("keeps JSON transport and credential handling out of the route", () => {
    expect(apiSource).toContain("/api/config/chatgpt-subscription/");
    expect(`${panelSource}\n${hookSource}`).not.toMatch(/fetchJson|fetch\(|\/api\/config\/chatgpt-subscription/);
    expect(`${panelSource}\n${hookSource}`).not.toMatch(/localStorage|sessionStorage|access_token|refresh_token|id_token|renderers\/|@heroui/);
  });
});
