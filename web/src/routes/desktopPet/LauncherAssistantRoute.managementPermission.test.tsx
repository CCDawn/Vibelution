// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantEmbeddedRoute } from "./LauncherAssistantRoute";

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
let conversation: ConversationViewProps | undefined;
let mounts = 0;
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => {
    conversation = props;
    useEffect(() => { mounts += 1; }, []);
    return createElement("div", { "data-testid": "native-conversation" }, props.composerPrecedingContent,
      createElement("div", { "data-testid": "existing-toolbar" }, props.composerLeadingControl, props.composerModelControl));
  },
}));

let root: Root | undefined;
let container: HTMLDivElement;
let client: QueryClient;
let invoke: ReturnType<typeof vi.fn>;
let currentPreset = "request_approval";
let revision = 0;
let counter = 0;
let nativeApproval: Record<string, unknown> | undefined;
let finishWrite: ((receipt: unknown) => void) | undefined;
const purgeSummary = () => ({
  argumentKeys: ["action", "arguments_json"], assistantAction: "agent_purge_batch",
  assistantTargets: { project_id: "project-a", request_id: "batch-request", batchCount: "2" },
  assistantPurgeItems: [{ agent_id: "agent-a", expected_config_revision: "4" }, { agent_id: "agent-b", expected_config_revision: "9007199254740993123" }],
  assistantPurgeIrreversible: true, assistantPurgeEffects: ["agent", "sessions", "private_workspace", "team_room_mode_references"],
});
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined; client?.clear(); container?.remove();
  conversation = undefined; finishWrite = undefined; vi.unstubAllGlobals();
});
async function settle() { await act(async () => { await new Promise(done => setTimeout(done, 20)); }); }
async function renderRoute(options: { busy?: boolean; approval?: boolean; summary?: Record<string, unknown>; oldHost?: boolean; holdWrite?: boolean } = {}) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP forbidden in native assistant"); }));
  const sessionId = `permission-route-${++counter}`;
  currentPreset = "request_approval"; revision = 0; mounts = 0;
  nativeApproval = options.approval ? { requestId: "original-approval", sessionId, agentId: "a", turnId: "pending-turn", callId: "call",
    toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", argumentSummary: options.summary ?? purgeSummary(),
    availableDecisions: ["accept", "decline"] } : undefined;
  invoke = vi.fn(async request => {
    switch (request.operation) {
      case "status": return { assistant: { agentId: "a", directSessionId: sessionId, displayName: "Assistant" },
        settings: { ok: true, modelId: "model", displayName: "Assistant",
          preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "" },
          ...(!options.oldHost ? { managementPermission: { preset: currentPreset, revision } } : {}) } };
      case "detail": return { id: sessionId, agentId: "a", status: options.busy ? "running" : "ready", messages: [] };
      case "config": return { language: "zh" };
      case "approvals": return nativeApproval ? [nativeApproval] : [];
      case "dispatches": return { dispatches: [] };
      case "setManagementPermissionPreset": {
        if (options.holdWrite) return new Promise(resolve => { finishWrite = resolve; });
        currentPreset = request.preset; revision = request.expectedRevision + 1;
        return { preset: currentPreset, revision };
      }
      case "resolveApproval": nativeApproval = { ...nativeApproval, status: "accepted", decision: request.decision }; return nativeApproval;
      default: throw new Error(`unexpected operation: ${request.operation}`);
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root!.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantEmbeddedRoute))));
  await settle(); await settle();
}
async function choose(preset: string) {
  const trigger = container.querySelector<HTMLButtonElement>('[data-launcher-management-permission] button')!;
  expect(trigger.disabled).toBe(false);
  await act(async () => trigger.click());
  const option = document.querySelector<HTMLButtonElement>(`[role="option"][data-preset="${preset}"]`)!;
  await act(async () => option.click()); await settle();
}
const calls = (operation: string) => invoke.mock.calls.filter(([request]) => request.operation === operation);

describe("Launcher permission composer toolbar integration", () => {
  const providerSummary = () => ({ argumentKeys: ["action", "arguments_json"], assistantAction: "provider_model_resolve",
    assistantProviderPreviewVersion: 1, assistantParametersDigest: "a".repeat(64), assistantDetailsOmitted: false,
    assistantTargets: { provider_id: "relay-1", model_query: "Opus 5.5", upstream_id: "vendor/claude-opus-5.5", verify: "true", offset: "0", limit: "20" } });
  it("allows a complete native provider-model request and sends its original approval ID once", async () => {
    await renderRoute({ approval: true, summary: providerSummary() });
    const approval = container.querySelector<HTMLElement>('[data-chat-tool-approval-variant="composer"]')!;
    expect(approval.textContent).toContain("relay-1");
    expect(approval.textContent).toContain("Opus 5.5");
    expect(approval.textContent).toContain("vendor/claude-opus-5.5");
    expect(approval.textContent).toContain("可能产生费用");
    const accept = [...approval.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent?.includes("允许本次"))!;
    expect(accept.disabled).toBe(false);
    await act(async () => accept.click()); await settle();
    expect(calls("resolveApproval").map(([request]) => request)).toEqual([{ operation: "resolveApproval", requestId: "original-approval", decision: "accept" }]);
  });
  it.each(["legacy", "omitted", "wrong-type"])("keeps %s provider-model previews unapprovable", async kind => {
    const summary: Record<string, unknown> = providerSummary();
    if (kind === "legacy") delete summary.assistantProviderPreviewVersion;
    if (kind === "omitted") summary.assistantDetailsOmitted = true;
    if (kind === "wrong-type") summary.assistantTargets = { ...providerSummary().assistantTargets, verify: true };
    await renderRoute({ approval: true, summary });
    const approval = container.querySelector<HTMLElement>('[data-chat-tool-approval-variant="composer"]')!;
    expect(approval.textContent).toContain("参数无法核对");
    const accept = [...approval.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent?.includes("允许本次"))!;
    expect(accept.disabled).toBe(true);
    await act(async () => accept.click()); await settle();
    expect(calls("resolveApproval")).toHaveLength(0);
  });
  const configSummary = (action: string) => ({ argumentKeys: ["action", "arguments_json"], assistantAction: action,
    assistantPlatformPreviewVersion: 1, assistantParametersDigest: "a".repeat(64), assistantDetailsOmitted: false,
    assistantContentOmitted: action === "agent_prompt_update",
    assistantTargets: { project_id: "project-a", request_id: "config-request", agent_id: "agent-a", expected_config_revision: "3",
      ...(action === "agent_prompt_update" ? { expected_template_id: "role-a", expected_content_hash: `sha256:${"b".repeat(64)}` } : { kind: "budget" }) },
    assistantChangedFields: action === "agent_prompt_update" ? ["promptContent", "promptTemplateId"] : ["budget"],
    assistantDelta: action === "agent_prompt_update" ? { scope: "single_agent_copy_on_write", contentChars: "40", contentDigest: "c".repeat(64), activation: "next_submission" }
      : { maxCallsPerTurn: null } });
  it.each(["agent_parameters_update", "agent_prompt_update"])("allows complete %s native approvals", async action => {
    await renderRoute({ approval: true, summary: configSummary(action) });
    const approval = container.querySelector<HTMLElement>('[data-chat-tool-approval-variant="composer"]')!;
    expect(approval.textContent).toContain("agent-a");
    if (action === "agent_prompt_update") expect(approval.textContent).toContain("下一次新提交");
    const accept = [...approval.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent?.includes("允许本次"))!;
    expect(accept.disabled).toBe(false);
    await act(async () => accept.click()); await settle();
    expect(calls("resolveApproval").map(([request]) => request)).toEqual([{ operation: "resolveApproval", requestId: "original-approval", decision: "accept" }]);
  });
  it.each(["agent_parameters_update", "agent_prompt_update"])("blocks incomplete %s native approvals", async action => {
    const input = configSummary(action); input.assistantDetailsOmitted = true;
    await renderRoute({ approval: true, summary: input });
    const approval = container.querySelector<HTMLElement>('[data-chat-tool-approval-variant="composer"]')!;
    expect(approval.textContent).toContain("参数无法核对");
    const accept = [...approval.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent?.includes("允许本次"))!;
    expect(accept.disabled).toBe(true);
    await act(async () => accept.click()); await settle();
    expect(calls("resolveApproval")).toHaveLength(0);
  });
  it.each([false, true])("saves while busy=%s, preserves the mounted composer and leaves existing approvals undecided", async busy => {
    await renderRoute({ busy, approval: true, holdWrite: true });
    await act(async () => conversation!.onComposerChange!("保留这份草稿")); await settle();
    const composerDisabled = conversation!.composerDisabled;
    const actionMode = conversation!.composerActionMode;
    expect(container.querySelectorAll('[data-launcher-management-permission]')).toHaveLength(1);
    expect(container.querySelector('[data-testid="existing-toolbar"] [data-launcher-management-permission]')).not.toBeNull();
    expect(container.querySelector('[data-launcher-management-permission]')?.closest('[data-testid="native-conversation"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="existing-toolbar"]')?.textContent).not.toContain("仅 Launcher 助理");
    expect(conversation!.permissionControl).toBeUndefined();
    expect(container.querySelector('[data-testid="existing-toolbar"]')?.textContent).toContain("model");
    await choose("full_access");
    expect(calls("setManagementPermissionPreset")).toHaveLength(0);
    const confirm = [...document.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent === "启用完全访问")!;
    await act(async () => confirm.click()); await settle();
    expect(calls("setManagementPermissionPreset")).toHaveLength(1);
    expect(container.querySelector<HTMLButtonElement>('[data-launcher-management-permission] button')?.disabled).toBe(true);
    expect(conversation!.composerValue).toBe("保留这份草稿");
    expect(conversation!.composerDisabled).toBe(composerDisabled);
    expect(conversation!.composerActionMode).toBe(actionMode);
    currentPreset = "full_access"; revision = 1;
    await act(async () => finishWrite!({ preset: currentPreset, revision })); await settle();
    expect(mounts).toBe(1); expect(conversation!.composerValue).toBe("保留这份草稿");
    expect(calls("resolveApproval")).toHaveLength(0);
    const approval = container.querySelector('[data-chat-tool-approval-variant="composer"]')!;
    expect(approval.textContent).toContain("agent-a");
    expect(approval.textContent).toContain("agent-b");
    expect(approval.textContent).toContain("9007199254740993123");
    expect(approval.textContent).toContain("无法撤销");
    const accept = [...approval.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent?.includes("允许本次"))!;
    expect(accept.disabled).toBe(false);
    await act(async () => accept.click()); await settle();
    expect(calls("resolveApproval").map(([request]) => request)).toEqual([{ operation: "resolveApproval", requestId: "original-approval", decision: "accept" }]);
  });

  it("blocks an incomplete batch purge manifest even after the full-access level is selected", async () => {
    await renderRoute({ approval: true, summary: { ...purgeSummary(), assistantPurgeItems: [{ agent_id: "agent-a", expected_config_revision: "4" }] } });
    await choose("full_access");
    const confirm = [...document.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent === "启用完全访问")!;
    await act(async () => confirm.click()); await settle();
    const approval = container.querySelector<HTMLElement>('[data-chat-tool-approval-variant="composer"]')!;
    expect(approval.textContent).toContain("参数无法核对");
    const accept = [...approval.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent?.includes("允许本次"))!;
    expect(accept.disabled).toBe(true);
    await act(async () => approval.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })));
    expect(calls("resolveApproval")).toHaveLength(0);
  });

  it("shows an honest disabled control for a legacy host and keeps the existing model and plus controls", async () => {
    await renderRoute({ oldHost: true });
    const footer = container.querySelector('[data-launcher-management-permission]')!;
    expect(footer.textContent).toContain("权限暂不可用");
    expect(footer.textContent).toContain("当前版本暂不支持");
    expect(footer.querySelector<HTMLButtonElement>("button")?.disabled).toBe(true);
    expect(footer.querySelector("[data-preset]")).toBeNull();
    expect(conversation!.composerLeadingControl).toBeTruthy(); expect(conversation!.composerModelControl).toBeTruthy();
    expect(calls("setManagementPermissionPreset")).toHaveLength(0);
  });
});
