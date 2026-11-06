import { fetchJson, isFetchAbortError, isFetchJsonHttpError } from "./client";
import type { ChatGPTSubscriptionLoginStarted, ChatGPTSubscriptionModels, ChatGPTSubscriptionStatus } from "./types/chatgptSubscription";

export type { SubscriptionModel } from "./types/chatgptSubscription";

export const chatgptSubscriptionKeys = {
  all: ["chatgpt-subscription"] as const,
  status: ["chatgpt-subscription", "status"] as const,
  models: ["chatgpt-subscription", "models"] as const,
};

export class ChatGPTSubscriptionApiError extends Error {
  readonly code: string;
  readonly status: number | null;

  constructor(code: string, status: number | null = null) {
    // Show localized product copy; never echo raw upstream/transport failures.
    super(code);
    this.name = "ChatGPTSubscriptionApiError";
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    return await fetchJson<T>(`/api/config/chatgpt-subscription/${path}`, init);
  } catch (error) {
    if (isFetchAbortError(error)) throw error;
    if (isFetchJsonHttpError(error)) {
      throw new ChatGPTSubscriptionApiError(error.code || (error.status === 401 ? "reauth_required" : error.status === 429 ? "rate_limited" : "unavailable"), error.status);
    }
    throw new ChatGPTSubscriptionApiError("network");
  }
}

export function fetchChatGPTSubscriptionStatus(signal?: AbortSignal) {
  return request<ChatGPTSubscriptionStatus>("status", { signal });
}

export function startChatGPTSubscriptionLogin() {
  return request<ChatGPTSubscriptionLoginStarted>("login", { method: "POST" });
}

export function cancelChatGPTSubscriptionLogin(attemptId: string) {
  return request<{ cancelled: boolean }>("cancel", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ attemptId }),
  });
}

export function logoutChatGPTSubscription() {
  return request<{ revocationConfirmed: boolean }>("logout", { method: "POST" });
}

export function fetchChatGPTSubscriptionModels(signal?: AbortSignal) {
  return request<ChatGPTSubscriptionModels>("models", { signal });
}

/** Only the official authorization origin can be opened from a login result. */
export function isChatGPTSubscriptionAuthorizationUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.origin === "https://auth.openai.com" && url.pathname === "/api/accounts/authorize" && !url.username && !url.password;
  } catch {
    return false;
  }
}

export const CHATGPT_SUBSCRIPTION_USAGE_URL = "https://chatgpt.com/settings/usage";
