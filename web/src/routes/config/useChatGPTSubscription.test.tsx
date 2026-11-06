// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelChatGPTSubscriptionLogin, chatgptSubscriptionKeys, fetchChatGPTSubscriptionModels,
  fetchChatGPTSubscriptionStatus, logoutChatGPTSubscription, startChatGPTSubscriptionLogin,
} from "../../api/chatgptSubscription";
import { openExternalUrl } from "../../api/desktopPlatform";
import type { ChatGPTSubscriptionStatus } from "../../api/types/chatgptSubscription";
import { useChatGPTSubscription } from "./useChatGPTSubscription";

vi.mock("../../api/chatgptSubscription", async (original) => ({
  ...await original<typeof import("../../api/chatgptSubscription")>(),
  fetchChatGPTSubscriptionStatus: vi.fn(), fetchChatGPTSubscriptionModels: vi.fn(),
  startChatGPTSubscriptionLogin: vi.fn(), cancelChatGPTSubscriptionLogin: vi.fn(), logoutChatGPTSubscription: vi.fn(),
}));
vi.mock("../../api/desktopPlatform", () => ({ openExternalUrl: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const signedOut: ChatGPTSubscriptionStatus = { state: "signed_out", connected: false, account: null, expiresAt: null, lastError: null, login: null };
const connected: ChatGPTSubscriptionStatus = { ...signedOut, state: "connected", connected: true, account: { subject: "account-1", email: "person@example.com" } };
const login = (attemptId = "attempt-identity-1") => ({ attemptId, authorizationUrl: "https://auth.openai.com/api/accounts/authorize?state=opaque", expiresAt: "2026-11-06T12:00:00Z" });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

let root: Root | null;
let client: QueryClient;
let current!: ReturnType<typeof useChatGPTSubscription>;
let serverStatus: ChatGPTSubscriptionStatus;

async function flush() { await act(async () => { await vi.advanceTimersByTimeAsync(0); }); }
async function mount() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } });
  root = createRoot(document.createElement("div"));
  function Harness() { current = useChatGPTSubscription(); return null; }
  await act(async () => root!.render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>));
  await flush();
}

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks();
  serverStatus = signedOut;
  vi.mocked(fetchChatGPTSubscriptionStatus).mockImplementation(async () => serverStatus);
  vi.mocked(fetchChatGPTSubscriptionModels).mockResolvedValue({ models: [], provider: { provider_id: "chatgpt" } });
  vi.mocked(startChatGPTSubscriptionLogin).mockImplementation(async () => {
    const result = login(); serverStatus = { ...signedOut, login: { attemptId: result.attemptId, state: "pending", expiresAt: result.expiresAt } }; return result;
  });
  vi.mocked(cancelChatGPTSubscriptionLogin).mockImplementation(async () => { serverStatus = signedOut; return { cancelled: true }; });
  vi.mocked(logoutChatGPTSubscription).mockImplementation(async () => { serverStatus = signedOut; return { revocationConfirmed: false }; });
  vi.mocked(openExternalUrl).mockResolvedValue(false);
});
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  root = null; client?.clear(); vi.useRealTimers();
});

describe("ChatGPT subscription lifecycle", () => {
  it("opens official authorization, polls each second and reads the real catalog after success", async () => {
    await mount();
    await act(async () => current.startLogin()); await flush();
    expect(openExternalUrl).toHaveBeenCalledWith(login().authorizationUrl);
    expect(current.manualAuthorization).toBe(true);
    expect(current.pending).toBe(true);
    expect(fetchChatGPTSubscriptionModels).not.toHaveBeenCalled();
    serverStatus = { ...connected, login: { attemptId: login().attemptId, state: "succeeded", expiresAt: login().expiresAt } };
    await act(async () => { await vi.advanceTimersByTimeAsync(1_010); }); await flush();
    expect(current.statusQuery.data?.account?.email).toBe("person@example.com");
    expect(current.pending).toBe(false);
    expect(current.authorization).toBeNull();
    expect(fetchChatGPTSubscriptionModels).toHaveBeenCalledOnce();
  });

  it("cancels only the active attempt and ignores an old status request that finishes after a new login", async () => {
    await mount();
    await act(async () => current.startLogin()); await flush();
    const oldPoll = deferred<ChatGPTSubscriptionStatus>();
    vi.mocked(fetchChatGPTSubscriptionStatus).mockImplementationOnce(() => oldPoll.promise);
    let previous!: Promise<unknown>;
    await act(async () => { previous = current.statusQuery.refetch(); });
    await act(async () => current.cancelLogin()); await flush();
    expect(cancelChatGPTSubscriptionLogin).toHaveBeenCalledWith(login().attemptId, expect.anything());
    vi.mocked(startChatGPTSubscriptionLogin).mockImplementationOnce(async () => {
      const next = login("attempt-identity-2");
      serverStatus = { ...signedOut, login: { attemptId: next.attemptId, state: "pending", expiresAt: next.expiresAt } }; return next;
    });
    await act(async () => current.startLogin()); await flush();
    await act(async () => { oldPoll.resolve(connected); await previous; }); await flush();
    expect(client.getQueryData<ChatGPTSubscriptionStatus>(chatgptSubscriptionKeys.status)?.login?.attemptId).toBe("attempt-identity-2");
    expect(current.statusQuery.data?.connected).toBe(false);
  });

  it("does not let a late cancellation clear a newer authorization", async () => {
    await mount(); await act(async () => current.startLogin()); await flush();
    const lateCancel = deferred<{ cancelled: boolean }>();
    vi.mocked(cancelChatGPTSubscriptionLogin).mockImplementationOnce(() => lateCancel.promise);
    let cancel!: Promise<void>;
    await act(async () => { cancel = current.cancelLogin(); });
    vi.mocked(startChatGPTSubscriptionLogin).mockImplementationOnce(async () => login("attempt-identity-2"));
    await act(async () => current.startLogin());
    await act(async () => { lateCancel.resolve({ cancelled: true }); await cancel; }); await flush();
    expect(current.authorization?.attemptId).toBe("attempt-identity-2");
  });

  it("distinguishes local removal from confirmed remote revocation and never logs out on unmount", async () => {
    serverStatus = connected; await mount();
    await act(async () => current.disconnect()); await flush();
    expect(current.disconnectNotice).toBe("local_only");
    expect(current.statusQuery.data?.state).toBe("signed_out");
    expect(logoutChatGPTSubscription).toHaveBeenCalledOnce();
    await act(async () => root!.unmount()); root = null;
    expect(logoutChatGPTSubscription).toHaveBeenCalledOnce();
  });

  it("keeps the authorized account when leaving settings", async () => {
    serverStatus = connected; await mount();
    await act(async () => root!.unmount()); root = null;
    expect(logoutChatGPTSubscription).not.toHaveBeenCalled();
    expect(cancelChatGPTSubscriptionLogin).not.toHaveBeenCalled();
    expect(client.getQueryData<ChatGPTSubscriptionStatus>(chatgptSubscriptionKeys.status)?.account).toEqual(connected.account);
  });

  it("accepts the remembered signed-out account after logout and can start a new login", async () => {
    serverStatus = connected;
    vi.mocked(logoutChatGPTSubscription).mockImplementationOnce(async () => {
      serverStatus = { ...signedOut, account: connected.account };
      return { revocationConfirmed: false };
    });
    await mount();
    await act(async () => current.disconnect()); await flush();
    expect(current.statusQuery.data).toMatchObject({ state: "signed_out", connected: false, account: connected.account, lastError: null });
    await act(async () => current.startLogin()); await flush();
    expect(startChatGPTSubscriptionLogin).toHaveBeenCalledOnce();
    expect(current.pending).toBe(true);
    expect(openExternalUrl).toHaveBeenCalledWith(login().authorizationUrl);
  });
});
