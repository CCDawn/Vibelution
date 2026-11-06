import { useCallback, useRef, type MutableRefObject } from "react";

import { addDraftProvider, pinDraftProviderModel, suggestDraftProviderId } from "../../api/config";
import type { ConfigDraftMeta, ConfigWorkspace } from "../../api/types";
import type { SubscriptionModel } from "../../api/types/chatgptSubscription";
import { asRecord, getString, type PublicConfigShape } from "../configRouteLogic";
import type { AddSubscriptionModels } from "./ChatGPTSubscriptionPanel";
import type { ConfigApplyDraftOverride } from "./configApplyModel";

export type Options = {
  providerDraftRequestRef: MutableRefObject<{
    publicConfig: PublicConfigShape; draftMeta: ConfigDraftMeta; baseHash: string;
  } | null>;
  baseConfigRef?: MutableRefObject<{ baseConfig: PublicConfigShape | null; baseHash: string }>;
  syncWorkspace: (workspace: ConfigWorkspace, tone?: "neutral" | "success" | "error", options?: { resetBase?: boolean }) => void;
  handleApply: (pendingLabel?: string, draftOverride?: ConfigApplyDraftOverride) => Promise<boolean>;
  setSelectedProviderId: (id: string) => void;
  setupBlockedReason?: string;
  onSetupBusyChange?: (busy: boolean) => void;
  language?: "zh" | "en";
};

const API_BASE = "https://api.openai.com/v1";
const REASONING_EFFORTS = new Set(["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]);

function isSubscriptionProvider(value: unknown): boolean {
  const provider = asRecord(value);
  const protocols = asRecord(provider.protocols);
  const credential = getString(provider.credential_ref).trim().split(":");
  const subscriptionCredential = credential.length === 2 && credential[0].toLowerCase() === "oauth" && credential[1].trim() === "chatgpt";
  return provider.auth_kind === "oauth" && subscriptionCredential
    && provider.driver === "openai" && provider.service_class === "official_api"
    && getString(provider.base_url).trim().replace(/\/+$/, "") === API_BASE && protocols.default === "responses"
    && Array.isArray(protocols.allowed) && protocols.allowed.length === 1 && protocols.allowed[0] === "responses"
    && Object.entries(asRecord(protocols.routes)).every(([key, route]) => key === "responses" && route === "responses");
}

function safeProvider(source: Record<string, unknown>): Record<string, unknown> {
  // The backend descriptor supplies identity, never arbitrary transport fields,
  // credentials, pending secrets, defaults, or model bindings to merge blindly.
  if (!isSubscriptionProvider(source) || source.credential_ref !== "oauth:chatgpt" || source.base_url !== API_BASE
    || Object.keys(asRecord(source.extra_headers)).length > 0) throw new Error("invalid subscription descriptor");
  return {
    label: getString(source.label).slice(0, 100) || "ChatGPT",
    service_class: "official_api", vendor: "openai", driver: "openai", auth_kind: "oauth",
    credential_ref: "oauth:chatgpt", requires_credential: true, base_url: API_BASE,
    protocols: { default: "responses", allowed: ["responses"], routes: { responses: "responses" } },
    discovery: { adapter: "openai" }, models: {},
  };
}

function modelOverrides(model: SubscriptionModel): Record<string, unknown> {
  const levels = [...new Set(model.supported_reasoning_levels.map(({ effort }) => effort)
    .filter((effort) => REASONING_EFFORTS.has(effort)))];
  return {
    // An empty explicit model protocol keeps protocol-family defaults from
    // inventing reasoning levels absent from the official account catalog.
    wire_protocol: "responses", model_protocol: levels.length ? "openai_responses" : "", interaction_contract: "tool_chat",
    ...(typeof model.context_window === "number" && Number.isSafeInteger(model.context_window) && model.context_window > 0
      ? { context_window: model.context_window } : {}),
    defaults: { reasoning_effort_values: levels, reasoning_effort_adapter: levels.length ? "reasoning_object" : "none",
      default_reasoning_effort: levels.includes("medium") ? "medium" : levels[0] ?? "" },
  };
}

export function useChatGPTSubscriptionModelSetup(options: Options): AddSubscriptionModels {
  const { providerDraftRequestRef, baseConfigRef, syncWorkspace, handleApply, setSelectedProviderId, onSetupBusyChange, language = "zh" } = options;
  const inFlight = useRef<Promise<void> | null>(null);
  const setupBlockedReason = useRef(options.setupBlockedReason);
  setupBlockedReason.current = options.setupBlockedReason;

  return useCallback((models, descriptor) => {
    if (inFlight.current) return inFlight.current;
    const operation = (async () => {
      let setupStarted = false;
      try {
        const requireSetupAllowed = () => {
          if (setupBlockedReason.current) throw new Error("other config drafts must be saved or restored first");
        };
        requireSetupAllowed();
        const latest = providerDraftRequestRef.current;
        if (!latest) throw new Error("missing config draft");
        const baseline = baseConfigRef?.current;
        const baseConfig = baseline?.baseConfig ?? null;
        const baseHash = baseline?.baseHash || latest.baseHash;
        if (!baseHash) throw new Error("missing config baseline");
        let current: ConfigApplyDraftOverride = { ...latest, baseHash };
        const selected = [...new Map(models.map((model) => [model.slug.trim(), model])).entries()];
        if (!selected.length || selected.some(([slug, model]) => !slug || !model.supported_in_api || model.visibility !== "list")) {
          throw new Error("no eligible selected model");
        }
        const provider = safeProvider(descriptor);
        setupStarted = true;
        onSetupBusyChange?.(true);
        const draftProviders = asRecord(asRecord(current.publicConfig.llm).providers);
        let providerId = Object.keys(draftProviders).find((id) => isSubscriptionProvider(draftProviders[id]));
        const request = () => ({ ...current, baseConfig, baseHash });
        const requireCurrentDraft = () => {
          requireSetupAllowed();
          const live = providerDraftRequestRef.current;
          if (!live || live.publicConfig !== current.publicConfig || live.draftMeta !== current.draftMeta
            || (baseConfigRef && (baseConfigRef.current.baseHash !== baseline?.baseHash || baseConfigRef.current.baseConfig !== baseConfig))) {
            throw new Error("config draft changed during subscription setup");
          }
        };
        const accept = (workspace: ConfigWorkspace) => {
          requireCurrentDraft();
          // Responses are accumulated locally; React may not render between
          // consecutive requests. The existing shared ref remains the owner.
          current = { publicConfig: workspace.publicConfig, draftMeta: workspace.draftMeta, baseHash };
          providerDraftRequestRef.current = current;
          syncWorkspace({ ...workspace, baseHash }, "neutral", { resetBase: false });
        };
        if (!providerId) {
          const suggestion = await suggestDraftProviderId({ ...request(), provider });
          requireCurrentDraft();
          providerId = suggestion.suggestedProviderId;
          if (!providerId || Object.prototype.hasOwnProperty.call(draftProviders, providerId)) {
            throw new Error("provider identity collision");
          }
          accept(await addDraftProvider({ ...request(), providerId, provider }));
        }
        const pinned = asRecord(asRecord(asRecord(current.publicConfig.llm).providers)[providerId]);
        const upstreamIds = new Set(Object.entries(asRecord(pinned.models)).map(([key, value]) => getString(asRecord(value).upstream_id) || key));
        for (const [slug, model] of selected) {
          if (upstreamIds.has(slug)) continue;
          accept(await pinDraftProviderModel(providerId, {
            ...request(), providerId, upstreamId: slug, modelKey: "", label: model.display_name || slug,
            overrides: modelOverrides(model),
          }));
          upstreamIds.add(slug);
        }
        requireCurrentDraft();
        if (!await handleApply(undefined, current)) throw new Error("config apply failed");
        setSelectedProviderId(providerId);
      } catch {
        throw new Error(language === "en"
          ? "ChatGPT models were not saved. Your configuration draft is preserved; please retry."
          : "ChatGPT 模型尚未保存，配置草稿已保留，请重试。");
      } finally {
        if (setupStarted) onSetupBusyChange?.(false);
      }
    })();
    inFlight.current = operation;
    const release = () => { if (inFlight.current === operation) inFlight.current = null; };
    void operation.then(release, release);
    return operation;
  }, [baseConfigRef, handleApply, language, onSetupBusyChange, providerDraftRequestRef, setSelectedProviderId, syncWorkspace]);
}
