/** Safe renderer contract: authorization credentials never enter these DTOs. */
export type ChatGPTSubscriptionLoginState = "pending" | "exchanging" | "succeeded" | "failed" | "expired" | "cancelled";

export type ChatGPTSubscriptionStatus = {
  state: "connected" | "signed_out" | "reauth_required" | "unavailable";
  connected: boolean;
  account: { subject: string; email: string } | null;
  expiresAt: string | null;
  lastError: { code: string; message: string } | null;
  login: { attemptId: string; state: ChatGPTSubscriptionLoginState; expiresAt: string } | null;
};

export type ChatGPTSubscriptionLoginStarted = {
  attemptId: string;
  authorizationUrl: string;
  expiresAt: string;
};

export type SubscriptionModel = {
  slug: string;
  display_name: string;
  visibility: "list";
  supported_in_api: boolean;
  context_window?: number | null;
  input_modalities: string[];
  supported_reasoning_levels: Array<{ effort: string }>;
};

export type ChatGPTSubscriptionModels = {
  models: SubscriptionModel[];
  provider: Record<string, unknown>;
};
