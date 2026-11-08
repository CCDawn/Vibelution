// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { addDraftProvider, pinDraftProviderModel, suggestDraftProviderId, type ConfigDraftEnvelope } from "../../api/config";
import type { ConfigDraftMeta, ConfigWorkspace } from "../../api/types";
import type { SubscriptionModel } from "../../api/types/chatgptSubscription";
import { asRecord, type PublicConfigShape } from "../configRouteLogic";
import { useChatGPTSubscriptionModelSetup, type Options } from "./useChatGPTSubscriptionModelSetup";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
vi.mock("../../api/config", () => ({ addDraftProvider: vi.fn(), pinDraftProviderModel: vi.fn(), suggestDraftProviderId: vi.fn() }));

const provider = {
  label: "ChatGPT 订阅", service_class: "official_api", vendor: "openai", driver: "openai",
  auth_kind: "oauth", credential_ref: "oauth:chatgpt", requires_credential: true,
  base_url: "https://api.openai.com/v1", protocols: { default: "responses", allowed: ["responses"], routes: { responses: "responses" } },
  discovery: { adapter: "openai" }, models: {},
};

function model(slug: string, context: number | null = 128000, levels = ["low", "medium", "high"]): SubscriptionModel {
  return { slug, display_name: `Official ${slug}`, visibility: "list", supported_in_api: true,
    context_window: context, input_modalities: ["text"], supported_reasoning_levels: levels.map((effort) => ({ effort })) };
}

function options(providers: Record<string, unknown> = {}): Options {
  const baseline: PublicConfigShape = { ui: { theme: "saved" }, llm: {
    providers, profiles: { primary: { model_ref: "api/existing" } },
    role_bindings: { primary: "api/existing" }, model_aliases: { default: "api/existing" },
  } };
  const publicConfig = structuredClone(baseline);
  publicConfig.ui = { theme: "unsaved-change" };
  const draftMeta: ConfigDraftMeta = { pending_api_keys: { OTHER_API_KEY: "existing-opaque-pending" }, pending_cleared_api_keys: [] };
  return { providerDraftRequestRef: { current: { publicConfig, draftMeta, baseHash: "draft-hash" } },
    baseConfigRef: { current: { baseConfig: baseline, baseHash: "frozen-baseline" } },
    syncWorkspace: vi.fn(), handleApply: vi.fn().mockResolvedValue(true), setSelectedProviderId: vi.fn(), language: "zh" };
}

function workspace(request: ConfigDraftEnvelope, publicConfig: PublicConfigShape, stage: string): ConfigWorkspace {
  return { publicConfig, draftMeta: { ...(request.draftMeta as ConfigDraftMeta), stage },
    baseHash: "server-draft-response", hash: stage } as unknown as ConfigWorkspace;
}

function mockDraftApis() {
  vi.mocked(suggestDraftProviderId).mockResolvedValue({ suggestedProviderId: "chatgpt" });
  vi.mocked(addDraftProvider).mockImplementation(async (request) => {
    const config = structuredClone(request.publicConfig) as PublicConfigShape;
    const llm = asRecord(config.llm);
    config.llm = { ...llm, providers: { ...asRecord(llm.providers), [String(request.providerId)]: request.provider } };
    return workspace(request, config, "added");
  });
  vi.mocked(pinDraftProviderModel).mockImplementation(async (providerId, request) => {
    const config = structuredClone(request.publicConfig) as PublicConfigShape;
    const llm = asRecord(config.llm);
    const providers = asRecord(llm.providers);
    const current = asRecord(providers[providerId]);
    const key = String(request.upstreamId);
    config.llm = { ...llm, providers: { ...providers, [providerId]: { ...current,
      models: { ...asRecord(current.models), [key]: { upstream_id: key, label: request.label, ...asRecord(request.overrides) } },
    } } };
    return workspace(request, config, `pinned-${key}`);
  });
}

async function run(input: Options, action: (
  callback: ReturnType<typeof useChatGPTSubscriptionModelSetup>,
  rerender: (changes: Partial<Options>) => Promise<void>,
) => Promise<void>) {
  const root = createRoot(document.createElement("div"));
  let callback!: ReturnType<typeof useChatGPTSubscriptionModelSetup>;
  let currentOptions = input;
  function Harness() { callback = useChatGPTSubscriptionModelSetup(currentOptions); return null; }
  const rerender = async (changes: Partial<Options>) => {
    currentOptions = { ...currentOptions, ...changes };
    await act(async () => root.render(<Harness />));
  };
  try { await act(async () => root.render(<Harness />)); await action(callback, rerender); }
  finally { await act(async () => root.unmount()); }
}

describe("ChatGPT subscription models use the existing shared config draft", () => {
  beforeEach(() => { vi.resetAllMocks(); mockDraftApis(); });

  it("accumulates two models without waiting for refs to rerender, preserves baseline and unrelated edits", async () => {
    const api = { auth_kind: "api_key", credential_ref: "env:SAVED_KEY", models: { existing: { upstream_id: "existing" } } };
    const input = options({ api });
    const original = structuredClone(input.providerDraftRequestRef.current);
    await run(input, async (add) => { await add([model("first"), model("second")], provider); });
    expect(addDraftProvider).toHaveBeenCalledOnce();
    expect(pinDraftProviderModel).toHaveBeenCalledTimes(2);
    const second = vi.mocked(pinDraftProviderModel).mock.calls[1][1];
    expect(asRecord(asRecord(asRecord(asRecord(second.publicConfig).llm).providers).chatgpt).models).toHaveProperty("first");
    expect(asRecord(second.draftMeta).stage).toBe("pinned-first");
    for (const request of [vi.mocked(suggestDraftProviderId).mock.calls[0][0], vi.mocked(addDraftProvider).mock.calls[0][0], ...vi.mocked(pinDraftProviderModel).mock.calls.map(([, request]) => request)]) {
      expect(request.baseConfig).toEqual(input.baseConfigRef!.current.baseConfig);
      expect(request.baseHash).toBe("frozen-baseline");
      expect(asRecord(request.publicConfig).ui).toEqual({ theme: "unsaved-change" });
      expect(asRecord(asRecord(asRecord(request.publicConfig).llm).providers).api).toEqual(api);
      expect(request).not.toHaveProperty("credentialValue");
    }
    const applied = vi.mocked(input.handleApply).mock.calls[0][1]!;
    expect(asRecord(applied.draftMeta).stage).toBe("pinned-second");
    expect(input.handleApply).toHaveBeenCalledWith(undefined, input.providerDraftRequestRef.current);
    expect(asRecord(asRecord(asRecord(applied.publicConfig.llm).providers).chatgpt).models).toHaveProperty("first");
    expect(asRecord(asRecord(asRecord(applied.publicConfig.llm).providers).chatgpt).models).toHaveProperty("second");
    expect(asRecord(applied.publicConfig.llm).profiles).toEqual(asRecord(original!.publicConfig.llm).profiles);
    expect(asRecord(applied.publicConfig.llm).role_bindings).toEqual(asRecord(original!.publicConfig.llm).role_bindings);
    expect(asRecord(applied.publicConfig.llm).model_aliases).toEqual(asRecord(original!.publicConfig.llm).model_aliases);
    expect(input.setSelectedProviderId).toHaveBeenCalledWith("chatgpt");
    expect(input.syncWorkspace).toHaveBeenLastCalledWith(expect.anything(), "neutral", { resetBase: false });
  });

  it("reuses the canonical OAuth provider and deduplicates aliases and repeated upstream selections", async () => {
    const existing = { ...provider, models: { canonical_alias: { upstream_id: "first", label: "Keep existing", context_window: 64000 } } };
    const input = options({ chatgpt_existing: existing });
    await run(input, async (add) => { await add([model("first"), model("first"), model("second"), model("second")], provider); });
    expect(suggestDraftProviderId).not.toHaveBeenCalled();
    expect(addDraftProvider).not.toHaveBeenCalled();
    expect(pinDraftProviderModel).toHaveBeenCalledOnce();
    expect(pinDraftProviderModel).toHaveBeenCalledWith("chatgpt_existing", expect.objectContaining({ upstreamId: "second" }));
    const models = asRecord(asRecord(asRecord(asRecord(input.providerDraftRequestRef.current!.publicConfig.llm).providers).chatgpt_existing).models);
    expect(models.canonical_alias).toEqual(existing.models.canonical_alias);
    expect(input.setSelectedProviderId).toHaveBeenCalledWith("chatgpt_existing");
  });

  it("reuses an existing subscription with metadata headers, a trailing slash and a canonical credential alias", async () => {
    const existing = { ...provider, credential_ref: " OAuth: chatgpt ", base_url: "https://api.openai.com/v1/",
      extra_headers: { "X-Client-Name": "Existing metadata" }, models: {} };
    const input = options({ saved_subscription: existing });
    await run(input, async (add) => { await add([model("first")], provider); });
    expect(suggestDraftProviderId).not.toHaveBeenCalled();
    expect(addDraftProvider).not.toHaveBeenCalled();
    expect(pinDraftProviderModel).toHaveBeenCalledWith("saved_subscription", expect.anything());
    const saved = asRecord(asRecord(asRecord(input.providerDraftRequestRef.current!.publicConfig.llm).providers).saved_subscription);
    expect(saved.extra_headers).toEqual(existing.extra_headers);
    expect(saved.base_url).toBe(existing.base_url);
    expect(saved.credential_ref).toBe(existing.credential_ref);
    expect(input.setSelectedProviderId).toHaveBeenCalledWith("saved_subscription");
  });

  it("pins only official context and reasoning levels, without inventing unknown context or a medium level", async () => {
    const input = options({ chatgpt: provider });
    await run(input, async (add) => { await add([model("first", 196000), model("second", null, ["high", "low", "high"])], provider); });
    const [first, second] = vi.mocked(pinDraftProviderModel).mock.calls.map(([, request]) => request);
    expect(first.label).toBe("Official first");
    expect(first.overrides).toEqual({ context_window: 196000, wire_protocol: "responses", model_protocol: "openai_responses", interaction_contract: "tool_chat",
      defaults: { reasoning_effort_values: ["low", "medium", "high"], default_reasoning_effort: "medium", reasoning_effort_adapter: "reasoning_object" } });
    expect(second.overrides).not.toHaveProperty("context_window");
    expect(asRecord(second.overrides).defaults).toEqual({ reasoning_effort_values: ["high", "low"], reasoning_effort_adapter: "reasoning_object", default_reasoning_effort: "high" });
  });

  it("explicitly disables reasoning when the official catalog provides no levels", async () => {
    const input = options({ chatgpt: provider });
    await run(input, async (add) => { await add([model("plain", null, [])], provider); });
    expect(vi.mocked(pinDraftProviderModel).mock.calls[0][1].overrides).toEqual({
      wire_protocol: "responses", model_protocol: "", interaction_contract: "tool_chat",
      defaults: { reasoning_effort_values: [], reasoning_effort_adapter: "none", default_reasoning_effort: "" },
    });
  });

  it("uses an allowlisted descriptor and never copies provider secrets or changes existing API services", async () => {
    const api = { ...provider, auth_kind: "api_key", credential_ref: "env:PAID_API", models: {} };
    const input = options({ paid_api: api });
    await run(input, async (add) => { await add([model("first")], { ...provider, api_key: "must-not-copy", access_token: "must-not-copy", refresh_token: "must-not-copy", fallback: "paid_api" }); });
    const request = vi.mocked(addDraftProvider).mock.calls[0][0];
    expect(request.provider).toEqual(provider);
    expect(JSON.stringify(request.provider)).not.toContain("must-not-copy");
    expect(asRecord(asRecord(asRecord(request.publicConfig).llm).providers).paid_api).toEqual(api);
    expect(input.providerDraftRequestRef.current!.draftMeta.pending_api_keys).toEqual({ OTHER_API_KEY: "existing-opaque-pending" });
  });

  it("rejects a suggested ID collision instead of replacing an API provider", async () => {
    const input = options({ chatgpt: { auth_kind: "api_key", credential_ref: "env:API_KEY" } });
    const original = structuredClone(input.providerDraftRequestRef.current);
    await run(input, async (add) => { await expect(add([model("first")], provider)).rejects.toThrow("草稿已保留"); });
    expect(addDraftProvider).not.toHaveBeenCalled();
    expect(pinDraftProviderModel).not.toHaveBeenCalled();
    expect(input.handleApply).not.toHaveBeenCalled();
    expect(input.providerDraftRequestRef.current).toEqual(original);
  });

  it("preserves partial draft progress on pin failure, hides raw errors, and retries without duplicating the first pin", async () => {
    const input = options();
    const pin = vi.mocked(pinDraftProviderModel).getMockImplementation()!;
    vi.mocked(pinDraftProviderModel).mockImplementationOnce(pin).mockRejectedValueOnce(new Error("raw-token-must-not-leak"));
    await run(input, async (add) => {
      const failed = add([model("first"), model("second")], provider);
      await expect(failed).rejects.toThrow("草稿已保留");
      await expect(failed).rejects.not.toThrow("raw-token");
      const partial = input.providerDraftRequestRef.current!;
      expect(asRecord(asRecord(asRecord(partial.publicConfig.llm).providers).chatgpt).models).toHaveProperty("first");
      expect(input.handleApply).not.toHaveBeenCalled();
      expect(input.setSelectedProviderId).not.toHaveBeenCalled();
      await add([model("first"), model("second")], provider);
    });
    expect(addDraftProvider).toHaveBeenCalledOnce();
    expect(vi.mocked(pinDraftProviderModel).mock.calls.map(([, request]) => request.upstreamId)).toEqual(["first", "second", "second"]);
    expect(input.handleApply).toHaveBeenCalledOnce();
  });

  it("does not report success or switch defaults when apply returns false", async () => {
    const input = options();
    vi.mocked(input.handleApply).mockResolvedValue(false);
    await run(input, async (add) => { await expect(add([model("first")], provider)).rejects.toThrow("尚未保存"); });
    expect(input.handleApply).toHaveBeenCalledOnce();
    expect(input.setSelectedProviderId).not.toHaveBeenCalled();
    expect(input.providerDraftRequestRef.current!.baseHash).toBe("frozen-baseline");
    expect(asRecord(asRecord(input.providerDraftRequestRef.current!.publicConfig.llm).role_bindings).primary).toBe("api/existing");
    expect(asRecord(asRecord(asRecord(input.providerDraftRequestRef.current!.publicConfig.llm).providers).chatgpt).models).toHaveProperty("first");
  });

  it("shares one in-flight operation for duplicate clicks", async () => {
    const input = options();
    input.onSetupBusyChange = vi.fn();
    let complete!: (value: { suggestedProviderId: string }) => void;
    vi.mocked(suggestDraftProviderId).mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
    await run(input, async (add) => {
      const first = add([model("first")], provider);
      const repeated = add([model("second")], provider);
      expect(repeated).toBe(first);
      expect(suggestDraftProviderId).toHaveBeenCalledOnce();
      expect(input.onSetupBusyChange).toHaveBeenCalledExactlyOnceWith(true);
      complete({ suggestedProviderId: "chatgpt" });
      await Promise.all([first, repeated]);
    });
    expect(addDraftProvider).toHaveBeenCalledOnce();
    expect(pinDraftProviderModel).toHaveBeenCalledOnce();
    expect(input.handleApply).toHaveBeenCalledOnce();
    expect(vi.mocked(input.onSetupBusyChange!).mock.calls).toEqual([[true], [false]]);
  });

  it.each(["suggest", "add", "pin", "apply"])("holds global setup busy throughout a pending %s operation", async (stage) => {
    const input = options();
    input.onSetupBusyChange = vi.fn();
    let resume!: () => void;
    let signalStarted!: () => void;
    const gate = new Promise<void>((resolve) => { resume = resolve; });
    const started = new Promise<void>((resolve) => { signalStarted = resolve; });
    const wait = async () => { signalStarted(); await gate; };
    const addProvider = vi.mocked(addDraftProvider).getMockImplementation()!;
    const pinModel = vi.mocked(pinDraftProviderModel).getMockImplementation()!;
    if (stage === "suggest") vi.mocked(suggestDraftProviderId).mockImplementationOnce(async () => {
      await wait(); return { suggestedProviderId: "chatgpt" };
    });
    if (stage === "add") vi.mocked(addDraftProvider).mockImplementationOnce(async (request) => {
      await wait(); return addProvider(request);
    });
    if (stage === "pin") vi.mocked(pinDraftProviderModel).mockImplementationOnce(async (id, request) => {
      await wait(); return pinModel(id, request);
    });
    if (stage === "apply") vi.mocked(input.handleApply).mockImplementationOnce(async () => {
      await wait(); return true;
    });
    await run(input, async (add) => {
      const operation = add([model("first")], provider);
      await started;
      expect(input.onSetupBusyChange).toHaveBeenCalledExactlyOnceWith(true);
      resume();
      await operation;
    });
    expect(vi.mocked(input.onSetupBusyChange!).mock.calls).toEqual([[true], [false]]);
  });

  it.each(["suggest", "add", "pin", "apply"])("releases global setup busy on %s failure", async (stage) => {
    const input = options();
    input.onSetupBusyChange = vi.fn();
    const error = new Error("private failure text");
    if (stage === "suggest") vi.mocked(suggestDraftProviderId).mockRejectedValueOnce(error);
    if (stage === "add") vi.mocked(addDraftProvider).mockRejectedValueOnce(error);
    if (stage === "pin") vi.mocked(pinDraftProviderModel).mockRejectedValueOnce(error);
    if (stage === "apply") vi.mocked(input.handleApply).mockResolvedValueOnce(false);
    await run(input, async (add) => { await expect(add([model("first")], provider)).rejects.toThrow("草稿已保留"); });
    expect(vi.mocked(input.onSetupBusyChange!).mock.calls).toEqual([[true], [false]]);
    expect(input.setSelectedProviderId).not.toHaveBeenCalled();
  });

  it("does not overwrite another editor's changes while a draft request is pending", async () => {
    const input = options({ chatgpt: provider });
    let complete!: (value: ConfigWorkspace) => void;
    vi.mocked(pinDraftProviderModel).mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
    await run(input, async (add) => {
      const operation = add([model("first")], provider);
      const latest = { ...input.providerDraftRequestRef.current!, publicConfig: { editedDuringRequest: true } };
      input.providerDraftRequestRef.current = latest;
      complete(workspace({}, { stale: true }, "old-response"));
      await expect(operation).rejects.toThrow("草稿已保留");
      expect(input.providerDraftRequestRef.current).toBe(latest);
    });
    expect(input.syncWorkspace).not.toHaveBeenCalled();
    expect(input.handleApply).not.toHaveBeenCalled();
  });

  it("blocks initially unsaved form or JSON drafts before any API call", async () => {
    const input = options();
    input.onSetupBusyChange = vi.fn();
    input.setupBlockedReason = "请先保存或还原其他设置草稿，再添加订阅模型";
    const original = input.providerDraftRequestRef.current;
    await run(input, async (add) => {
      await expect(add([model("first")], provider)).rejects.toThrow("草稿已保留");
    });
    expect(suggestDraftProviderId).not.toHaveBeenCalled();
    expect(addDraftProvider).not.toHaveBeenCalled();
    expect(pinDraftProviderModel).not.toHaveBeenCalled();
    expect(input.syncWorkspace).not.toHaveBeenCalled();
    expect(input.handleApply).not.toHaveBeenCalled();
    expect(input.providerDraftRequestRef.current).toBe(original);
    expect(input.onSetupBusyChange).not.toHaveBeenCalled();
  });

  it.each(["add", "pin"])("ignores a late %s response if another form draft appears after the operation starts", async (stage) => {
    const input = options(stage === "pin" ? { chatgpt: provider } : {});
    const original = input.providerDraftRequestRef.current;
    let complete!: (value: ConfigWorkspace) => void;
    let signalStarted!: () => void;
    const started = new Promise<void>((resolve) => { signalStarted = resolve; });
    const pending = () => {
      signalStarted();
      return new Promise<ConfigWorkspace>((resolve) => { complete = resolve; });
    };
    if (stage === "add") vi.mocked(addDraftProvider).mockImplementationOnce(pending);
    else vi.mocked(pinDraftProviderModel).mockImplementationOnce(pending);
    await run(input, async (add, rerender) => {
      const operation = add([model("first")], provider);
      await started;
      await rerender({ setupBlockedReason: "new-form-draft-private-details" });
      complete(workspace({}, { staleResponse: true }, "late"));
      await expect(operation).rejects.toThrow("草稿已保留");
      await expect(operation).rejects.not.toThrow("private-details");
    });
    expect(input.providerDraftRequestRef.current).toBe(original);
    expect(input.syncWorkspace).not.toHaveBeenCalled();
    expect(input.handleApply).not.toHaveBeenCalled();
    expect(input.setSelectedProviderId).not.toHaveBeenCalled();
  });

  it("preserves the current CAS hash when no separate baseline ref is available", async () => {
    const input = options({ chatgpt: provider });
    delete input.baseConfigRef;
    await run(input, async (add) => { await add([model("first"), model("second")], provider); });
    for (const [, request] of vi.mocked(pinDraftProviderModel).mock.calls) {
      expect(request.baseHash).toBe("draft-hash");
      expect(request.baseConfig).toBeNull();
    }
    expect(vi.mocked(input.handleApply).mock.calls[0][1]!.baseHash).toBe("draft-hash");
  });

  it.each(["missing", "empty", "unsupported"])("rejects %s input without writing or selecting a paid fallback", async (kind) => {
    const input = options();
    input.language = "en";
    if (kind === "missing") input.providerDraftRequestRef.current = null;
    await run(input, async (add) => {
      await expect(add(kind === "empty" ? [] : [{ ...model("first"), supported_in_api: kind !== "unsupported" }], provider)).rejects.toThrow("draft is preserved");
    });
    expect(addDraftProvider).not.toHaveBeenCalled();
    expect(pinDraftProviderModel).not.toHaveBeenCalled();
    expect(input.handleApply).not.toHaveBeenCalled();
    expect(input.setSelectedProviderId).not.toHaveBeenCalled();
  });
});
