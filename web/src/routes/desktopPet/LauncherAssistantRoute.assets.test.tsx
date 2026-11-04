// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { compile } from "tailwindcss";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";

const launcherCss = readFileSync(resolve(import.meta.dirname, "../../design/route-css/desktop-pet.tailwind.css"), "utf8");
const tokenCss = readFileSync(resolve(import.meta.dirname, "../../design/tokens.css"), "utf8");

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
let conversation: ConversationViewProps | undefined;
// Retain the real route, transport validators and QueryClient; replace only the
// expensive transcript renderer with its public user-image/composer contract.
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => {
    conversation = props;
    return createElement("div", { "data-testid": "native-conversation" },
      props.userAvatarImageUrl ? createElement("img", { alt: "user avatar", src: props.userAvatarImageUrl }) : null,
      props.assistantAvatarImageUrl ? createElement("img", { alt: "assistant avatar", src: props.assistantAvatarImageUrl }) : null,
      createElement("span", null, props.userDisplayName || "default user"),
      props.composerPrecedingContent, createElement("textarea", { "data-testid": "native-composer" }));
  },
}));

let root: Root | undefined;
let container: HTMLDivElement;
let client: QueryClient;
let detail: Record<string, unknown>;
let assets: { avatar: Record<string, unknown>; background: Record<string, unknown> };
let revisions: { avatar: string | null; background: string | null } | undefined;
let assistantRevision: string | null;
let assistantImage: Record<string, unknown> | null;
let assistantRead: (() => Promise<unknown>) | undefined;
let invoke: ReturnType<typeof vi.fn>;
let failingAvatar = false;
let navigationOwned = true;
let presentation: HTMLStyleElement | undefined;
let fetch: ReturnType<typeof vi.fn>;
const originalUrl = window.location.href;
const image = (dataBase64: string) => ({ contentType: "image/png", dataBase64, sha256: "a".repeat(64) });
const asset = (kind: "avatar" | "background", dataBase64: string | null, readability = "standard") => ({
  schemaVersion: 1, kind, image: dataBase64 === null ? null : image(dataBase64), readability,
});
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined;
  client?.clear(); container?.remove(); conversation = undefined;
  presentation?.remove(); presentation = undefined;
  delete document.documentElement.dataset.theme;
  window.location.href = originalUrl;
  vi.unstubAllGlobals(); vi.clearAllMocks(); vi.restoreAllMocks();
});
async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
}
async function showPage(show: boolean) {
  await act(async () => root!.render(createElement(QueryClientProvider, { client },
    show ? createElement(LauncherAssistantRoute, { embedded: true, navigationOwned, key: "page" }) : null)));
  await settle(); await settle();
}
function assetReads() { return invoke.mock.calls.filter(([request]) => request.operation === "operatorAsset").length; }
async function renderAssistant(options: { capability?: boolean; assistantCapability?: boolean; operatorName?: string; failAvatar?: boolean; approval?: Record<string, unknown>; dispatches?: Array<Record<string, unknown>>; boundPreview?: Record<string, unknown>; declineFailure?: boolean; language?: "zh" | "en"; patrol?: { state: "ready" | "unavailable"; deliveryStates: Record<string, number> }; startHidden?: boolean; legacyToolbar?: boolean } = {}) {
  window.location.href = "vibelution-launcher://launcher/launcher/assistant";
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  failingAvatar = Boolean(options.failAvatar);
  navigationOwned = !options.legacyToolbar;
  detail = { id: "s", agentId: "a", status: "ready", messages: [] };
  revisions = undefined;
  assistantRevision = "a".repeat(64); assistantImage = image("Bwg="); assistantRead = undefined;
  assets = { avatar: asset("avatar", "AQI="), background: asset("background", "AwQ=", "soft") };
  fetch = vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }); vi.stubGlobal("fetch", fetch);
  let dispatchRows = options.dispatches ?? [];
  invoke = vi.fn(async request => {
    switch (request.operation) {
      case "status": return {
        assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
        operatorProfile: { displayName: options.operatorName ?? "当前用户", avatarPreset: "initial" },
        ...(options.assistantCapability ? { assistantAvatarVersion: 1, assistantAvatarRevision: assistantRevision } : {}),
        ...(revisions ? { operatorAssetRevisions: revisions } : {}),
        ...(options.patrol ? { patrol: options.patrol } : {}),
        ...(options.capability === false ? {} : { operatorAssetsVersion: 1 }),
      };
      case "config": return { language: options.language ?? "zh" };
      case "detail": return detail;
      case "approvals": return options.approval ? [options.approval] : [];
      case "resolveApproval": return { ...options.approval, status: request.decision === "decline" ? "rejected" : "approved" };
      case "dispatches": return { dispatches: dispatchRows };
      case "previewDispatchApproval":
        if (!options.boundPreview) throw new Error("preview unavailable");
        return options.boundPreview;
      case "declineDispatchApproval":
        if (options.declineFailure) throw new Error("approval unavailable");
        dispatchRows = dispatchRows.map(row => row.dispatchId === request.dispatchId
          ? { ...row, receipt: { ...(row.receipt as Record<string, unknown>), pendingApprovals: [] } } : row);
        return { dispatchId: request.dispatchId, nativeTaskId: request.taskId };
      case "decideDispatchApproval":
        if (options.declineFailure) throw new Error("目标审批已变化");
        dispatchRows = dispatchRows.map(row => row.dispatchId === request.dispatchId
          ? { ...row, receipt: { ...(row.receipt as Record<string, unknown>), pendingApprovals: [] } } : row);
        return { dispatchId: request.dispatchId, taskId: request.taskId, approvalId: request.approvalId, revision: request.revision, decision: request.decision };
      case "computerState": return { available: false, status: "idle", message: "测试驱动未连接", grantId: null, window: null, pending: null };
      case "computerWindows": return { windows: [] };
      case "setExpanded": return { expanded: request.expanded };
      case "operatorAsset":
        if (Object.keys(request).sort().join(",") !== "kind,operation" || !["avatar", "background"].includes(request.kind)) throw new Error("invalid_asset_request");
        if (failingAvatar && request.kind === "avatar") throw new Error("image unavailable");
        return assets[request.kind as keyof typeof assets];
      case "assistantAvatar":
        if (Object.keys(request).join(",") !== "operation") throw new Error("invalid_avatar_request");
        return assistantRead ? assistantRead() : { schemaVersion: 1, agentId: "a", image: assistantImage };
      case "send": return { accepted: true, turnId: "sent-turn" };
      default: throw new Error("unexpected_operation");
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await showPage(!options.startHidden);
}
async function finishTurn(turnId: string) {
  detail = { ...detail, lastTurnTerminalTurnId: turnId, terminalReason: "success" };
  await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "detail"] }); });
  await settle(); await settle();
}

describe("Launcher operator image consumption", () => {
  it("includes the permission toolbar styles in the Launcher Tailwind bundle", () => {
    expect(launcherCss).toContain('@source "../../routes/desktopPet/LauncherManagementPermissionControl.styles.ts";');
  });

  it("shows the fixed assistant image, refreshes revisions without retaining old content, and stops reading when hidden", async () => {
    await renderAssistant({ assistantCapability: true, startHidden: true, operatorName: "  " });
    const reads = () => invoke.mock.calls.filter(([request]) => request.operation === "assistantAvatar").length;
    expect(reads()).toBe(0);
    await showPage(true);
    expect(reads()).toBe(1);
    expect(conversation?.userDisplayName).toBe("操作者");
    expect(container.querySelector('img[alt="assistant avatar"]')?.getAttribute("src")).toBe("data:image/png;base64,Bwg=");
    let finish!: (value: unknown) => void;
    assistantRead = () => new Promise(resolve => { finish = resolve; });
    assistantRevision = "b".repeat(64);
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "status"] }); });
    await settle();
    expect(reads()).toBe(2);
    expect(container.querySelector('img[alt="assistant avatar"]')).toBeNull();
    await act(async () => finish({ schemaVersion: 1, agentId: "a", image: image("CQo=") }));
    await settle();
    expect(container.querySelector('img[alt="assistant avatar"]')?.getAttribute("src")).toBe("data:image/png;base64,CQo=");
    await showPage(false);
    const before = reads();
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "assistant-avatar"] }); });
    expect(reads()).toBe(before);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not read an assistant image while the document is hidden", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await renderAssistant({ assistantCapability: true });
    expect(invoke.mock.calls.some(([request]) => request.operation === "assistantAvatar")).toBe(false);
    await act(async () => { visibility.mockReturnValue("visible"); document.dispatchEvent(new Event("visibilitychange")); });
    await settle();
    expect(invoke.mock.calls.filter(([request]) => request.operation === "assistantAvatar")).toHaveLength(1);
  });

  it("clears an identity-mismatched avatar and retries the failed resource", async () => {
    await renderAssistant({ assistantCapability: true });
    assistantRead = async () => ({ schemaVersion: 1, agentId: "other", image: image("CQo=") });
    assistantRevision = "b".repeat(64);
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "status"] }); });
    await settle(); await settle();
    expect(container.querySelector('img[alt="assistant avatar"]')).toBeNull();
    expect(container.textContent).toContain("部分外观图片暂不可用");
    assistantRead = undefined; assistantImage = image("Cww=");
    await act(async () => Array.from(container.querySelectorAll("button")).find(button => button.textContent === "重试")?.click());
    await settle(); await settle();
    expect(container.querySelector('img[alt="assistant avatar"]')?.getAttribute("src")).toBe("data:image/png;base64,Cww=");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("displays the complete fixed tool preset and dynamic directories before creation approval", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "agent_create", assistantTargets: { project_id: "registered:1", display_name: "Worker", model_id: "model-1" },
        assistantCreatePreset: "project_files_v1", assistantCreateTools: ["glob_tool", "grep_search_tool", "read_file_tool", "apply_diff_edit_tool", "write_file_tool"],
        assistantOperationDescription: "固定文件工具权限持续生效；写入按当前权限和协作模式审批，edit/yolo 等模式可能自动批准。目标派遣任务的审批只有在完整预览、版本和执行参数均可验证时才能批准。平台允许的动态目录包括项目、Agent 工作区、项目存储、工具目录、系统临时目录和用户配置允许目录，未来可能变化。不能执行命令或测试。" } } });
    const preview = container.querySelector<HTMLElement>("[data-approval-full-preview]");
    for (const value of ["registered:1", "model-1", "project_files_v1", "glob_tool", "grep_search_tool", "read_file_tool", "apply_diff_edit_tool", "write_file_tool", "项目存储", "系统临时目录", "用户配置允许目录", "edit/yolo", "可能自动批准", "完整预览", "版本和执行参数"]) expect(preview?.textContent).toContain(value);
    expect(preview?.tabIndex).toBe(0);
    expect([...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"))?.disabled).toBe(false);
  });

  it("blocks creation approval when the file-tool preset disclosure is incomplete", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "agent_create", assistantTargets: { project_id: "registered:1", display_name: "Worker", model_id: "model-1" },
        assistantCreatePreset: "project_files_v1", assistantCreateTools: ["glob_tool"],
        assistantOperationDescription: "固定文件工具权限持续生效；写入按当前权限和协作模式审批，edit/yolo 等模式可能自动批准。目标派遣任务的审批只有在完整预览、版本和执行参数均可验证时才能批准。平台允许的动态目录包括项目、Agent 工作区、项目存储、工具目录、系统临时目录和用户配置允许目录，未来可能变化。不能执行命令或测试。" } } });
    expect(container.textContent).toContain("参数无法核对");
    expect([...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"))?.disabled).toBe(true);
  });

  it("shows complete bound arguments before allowing a single native approval", async () => {
    const request = { approvalId: "approval-1", toolName: "exec_command", risk: "write", targetSummary: { commandPreview: "echo fixture", commandTruncated: false }, revision: "fp-1", availableDecisions: ["accept", "decline"] };
    const row = { dispatchId: "dispatch-1", projectId: "registered:1", agentId: "worker-1", nativeTaskId: "task-1", receipt: { taskId: "task-1", status: "awaiting_approval", shouldPoll: true, pendingApprovals: [request] } };
    const boundPreview = { taskId: "task-1", sessionId: "session-1", agentId: "worker-1", requestId: "approval-1", turnId: "turn-1", callId: "call-1", toolName: "exec_command", revision: "a".repeat(64), approval: "always", risk: "write", permissionPreset: "request_approval", decisionFingerprint: "fp-1", configRevision: 1, configHash: "hash", argumentsJson: '{"cmd":"\\u4f60\\u597d", "large":9007199254740993}', executionArgumentsJson: '{"cmd":"\\u4f60\\u597d", "large":9007199254740993,"timeout":60}' };
    await renderAssistant({ dispatches: [row], boundPreview });
    const preview = container.querySelector<HTMLElement>("[data-approval-full-preview]");
    for (const value of ["registered:1", "worker-1", "dispatch-1", "task-1", "approval-1", "你好", "9007199254740993", "timeout"]) expect(preview?.textContent).toContain(value);
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"));
    expect(approve?.disabled).toBe(false);
    expect(reject?.disabled).toBe(false);
    await act(async () => { approve?.click(); approve?.click(); }); await settle(); await settle();
    const calls = invoke.mock.calls.filter(([payload]) => payload.operation === "decideDispatchApproval");
    expect(calls).toEqual([[{ operation: "decideDispatchApproval", dispatchId: "dispatch-1", taskId: "task-1", approvalId: "approval-1", revision: "a".repeat(64), decision: "accept" }]]);
    expect(container.textContent).not.toContain("9007199254740993");
  });

  it("shows only the assistant approval when both sessions require a decision", async () => {
    const approval = { requestId: "own", sessionId: "s", turnId: "t", agentId: "a", toolName: "exec_command", status: "pending", risk: "write", argumentSummary: { commandPreview: "own command" }, availableDecisions: ["accept", "decline"] };
    const target = { approvalId: "target", toolName: "unknown_tool", risk: "write", targetSummary: { argumentKeys: ["path"] }, revision: "fp", availableDecisions: ["decline"] };
    await renderAssistant({ approval, dispatches: [{ dispatchId: "d", nativeTaskId: "task", receipt: { taskId: "task", pendingApprovals: [target] } }] });
    expect(container.querySelectorAll('[data-chat-tool-approval-variant="composer"]')).toHaveLength(1);
    const dock = container.querySelector("[data-launcher-assistant-approval-dock]")!;
    expect(dock.closest('[data-testid="native-conversation"]')).not.toBeNull();
    expect(dock.compareDocumentPosition(container.querySelector('[data-testid="native-composer"]')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container.textContent).toContain("own command");
    await act(async () => container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "n", bubbles: true }))); await settle();
    expect(invoke.mock.calls.filter(([payload]) => payload.operation === "resolveApproval")).toHaveLength(1);
    expect(invoke.mock.calls.some(([payload]) => payload.operation === "decideDispatchApproval")).toBe(false);
  });

  it("re-reads a fresh bound preview after an unconfirmed decline and retries only on explicit clicks", async () => {
    const target = { approvalId: "a", toolName: "write_file_tool", risk: "write", targetSummary: { pathPreview: "fixture" }, revision: "old", availableDecisions: ["accept", "decline"] };
    const preview = { taskId: "t", sessionId: "s2", agentId: "worker", requestId: "a", turnId: "turn", callId: "call", toolName: "write_file_tool", revision: "b".repeat(64), approval: "always", risk: "write", permissionPreset: "request_approval", decisionFingerprint: "policy", configRevision: 1, configHash: "hash", argumentsJson: '{"content":"PRIVATE-FIXTURE"}', executionArgumentsJson: '{"content":"PRIVATE-FIXTURE"}' };
    await renderAssistant({ declineFailure: true, boundPreview: preview, dispatches: [{ dispatchId: "d", agentId: "worker", nativeTaskId: "t", receipt: { taskId: "t", pendingApprovals: [target] } }] });
    expect(container.textContent).toContain("PRIVATE-FIXTURE");
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"));
    await act(async () => { reject?.click(); }); await settle(); await settle();
    // The route itself never re-sends the unconfirmed decision without a click.
    expect(invoke.mock.calls.filter(([payload]) => payload.operation === "decideDispatchApproval")).toHaveLength(1);
    expect(container.textContent).toContain("审批结果未确认");
    // The failed decision re-reads the host-validated bound preview, so both
    // decisions re-arm instead of deadlocking behind the error card.
    expect([...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"))?.hasAttribute("disabled")).toBe(false);
    expect([...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"))?.hasAttribute("disabled")).toBe(false);
    // An explicit second click re-sends the same bound decision, and the route
    // adds no further attempt on its own.
    const retryReject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"));
    await act(async () => { retryReject?.click(); }); await settle(); await settle();
    expect(invoke.mock.calls.filter(([payload]) => payload.operation === "decideDispatchApproval")).toHaveLength(2);
  });

  it("drops the private full preview when leaving the assistant page", async () => {
    const target = { approvalId: "a", toolName: "write_file_tool", risk: "write", targetSummary: {}, revision: "old", availableDecisions: ["accept", "decline"] };
    const preview = { taskId: "t", sessionId: "s2", agentId: "worker", requestId: "a", turnId: "turn", callId: "call", toolName: "write_file_tool", revision: "b".repeat(64), approval: "always", risk: "write", permissionPreset: "request_approval", decisionFingerprint: "policy", configRevision: 1, configHash: "hash", argumentsJson: '{"content":"PRIVATE-FIXTURE"}', executionArgumentsJson: '{"content":"PRIVATE-FIXTURE"}' };
    await renderAssistant({ boundPreview: preview, dispatches: [{ dispatchId: "d", agentId: "worker", nativeTaskId: "t", receipt: { taskId: "t", pendingApprovals: [target] } }] });
    expect(container.textContent).toContain("PRIVATE-FIXTURE");
    expect(JSON.stringify(client.getQueryCache().getAll().map(query => query.state.data))).not.toContain("PRIVATE-FIXTURE");
    await showPage(false);
    expect(container.textContent).not.toContain("PRIVATE-FIXTURE");
  });

  it("shows the target summary but disables all decisions and shortcuts when revision is empty", async () => {
    const target = { approvalId: "target", toolName: "exec_command", risk: "write", targetSummary: { commandPreview: "echo fixture" }, revision: "", availableDecisions: ["accept", "decline"] };
    await renderAssistant({ dispatches: [{ dispatchId: "d", nativeTaskId: "task", receipt: { taskId: "task", pendingApprovals: [target] } }] });
    expect(container.textContent).toContain("echo fixture");
    expect(container.textContent).toContain("完整操作暂不可核对");
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"));
    expect(reject?.disabled).toBe(true);
    await act(async () => { reject?.click(); container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "n" })); container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); });
    expect(invoke.mock.calls.some(([payload]) => payload.operation === "decideDispatchApproval")).toBe(false);
  });

  it("declines one bound summary when full preview cannot be read", async () => {
    const target = { approvalId: "target", toolName: "exec_command", risk: "write", targetSummary: { commandPreview: "partial", commandTruncated: true }, revision: "policy-1", availableDecisions: ["accept", "decline"] };
    await renderAssistant({ dispatches: [{ dispatchId: "d", agentId: "worker", nativeTaskId: "task", receipt: { taskId: "task", pendingApprovals: [target] } }] });
    expect(container.textContent).toContain("完整操作不可用，不能批准");
    expect([...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"))?.disabled).toBe(true);
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"));
    await act(async () => { reject?.click(); reject?.click(); }); await settle(); await settle();
    expect(invoke.mock.calls.filter(([payload]) => payload.operation === "declineDispatchApproval")).toEqual([[{ operation: "declineDispatchApproval", dispatchId: "d", taskId: "task", approvalId: "target", revision: "policy-1" }]]);
    expect(invoke.mock.calls.some(([payload]) => payload.operation === "decideDispatchApproval")).toBe(false);
  });

  it.each([
    { toolName: "exec_command", targetSummary: { commandPreview: "partial", commandTruncated: true } },
    { toolName: "write_file_tool", targetSummary: { pathPreview: "example.txt" } },
    { toolName: "unknown_tool", targetSummary: { argumentKeys: ["target"] } },
  ])("permits only a single decline when the full preview is unavailable", async ({ toolName, targetSummary }) => {
    const target = { approvalId: "target", toolName, risk: "write", targetSummary, revision: "fp", availableDecisions: ["accept", "decline"] };
    await renderAssistant({ declineFailure: true, dispatches: [{ dispatchId: "d", nativeTaskId: "task", receipt: { taskId: "task", pendingApprovals: [target] } }] });
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"));
    expect(approve?.disabled).toBe(true);
    expect(reject?.disabled).toBe(false);
    await act(async () => { reject?.click(); reject?.click(); }); await settle();
    expect(container.textContent).toContain("完整操作暂不可核对");
    expect(container.textContent).toContain("审批结果未确认");
    expect(invoke.mock.calls.filter(([payload]) => payload.operation === "declineDispatchApproval")).toHaveLength(1);
    expect(reject?.disabled).toBe(true);
    expect(invoke.mock.calls.some(([payload]) => payload.operation === "decideDispatchApproval")).toBe(false);
  });
  it("shows the zero-tool limitation when approving Launcher agent creation", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "agent_create", assistantTargets: { project_id: "registered:1", display_name: "Worker", model_id: "model-1" },
        assistantOperationDescription: "新 Agent 默认没有工具和读写范围，不能保证读取或修改项目；派遣写任务不会自动增加工具权限。" } } });
    const preview = container.querySelector<HTMLElement>("[data-approval-full-preview]");
    expect(preview?.textContent).toContain("registered:1");
    expect(preview?.textContent).toContain("模型: model-1");
    expect(preview?.textContent).toContain("没有工具和读写范围");
    expect(preview?.textContent).toContain("派遣写任务不会自动增加工具权限");
    expect(preview?.tabIndex).toBe(0);
    expect([...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"))?.disabled).toBe(false);
  });

  it("refuses Launcher agent creation approval without the zero-tool limitation", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "agent_create", assistantTargets: { project_id: "registered:1", display_name: "Worker" } } } });
    expect([...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"))?.disabled).toBe(true);
  });

  it.each([["avatar", "头像"], ["background", "壁纸"]])("approves a verified %s image upload", async (kind, label) => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "operator_image_upload", assistantTargets: { kind } } } });
    expect(container.textContent).toContain(label);
    expect(container.textContent).toContain("上传并应用");
    expect(container.textContent).toContain("取消不修改");
    expect([...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"))?.disabled).toBe(false);
    await act(async () => container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })));
    await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(true);
  });

  it.each([undefined, {}, {kind: "other"}, {kind: "avatar", path: "secret"}])("blocks both approval paths for an unverifiable image target %j", async assistantTargets => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "operator_image_upload", assistantTargets } } });
    expect(container.textContent).toContain("参数无法核对");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"));
    expect(approve?.disabled).toBe(true); expect(reject?.disabled).toBe(false);
    await act(async () => { approve?.click(); container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })); });
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(false);
  });

  it("shows the complete project lifecycle request before approval", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "project_lifecycle", assistantTargets: {
        project_id: "registered:1", operation: "restart", request_id: "lifecycle-1",
      } } } });
    expect(container.textContent).toContain("项目: registered:1");
    expect(container.textContent).toContain("操作: 重启");
    expect(container.textContent).toContain("请求 ID: lifecycle-1");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
    expect(approve?.disabled).toBe(false);
  });

  it("blocks approval when project lifecycle details cannot be verified", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "project_lifecycle", assistantTargets: { project_id: "registered:1", operation: "stop" } } } });
    expect(container.textContent).toContain("参数无法核对");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
    expect(approve?.disabled).toBe(true);
    await act(async () => container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })));
    await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval")).toBe(false);
  });

  it("shows the complete project permission request on the actual assistant route", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "authorization_upgrade", assistantTargets: { project_id: "registered:1" },
        assistantAddedScopes: ["source:read", "tasks:read"] } } });
    const preview = container.querySelector<HTMLElement>("[data-approval-full-preview]");
    expect(preview?.textContent).toContain("registered:1");
    expect(preview?.textContent).toContain("source:read");
    expect(preview?.textContent).toContain("tasks:read");
    expect(preview?.closest("[data-approval-scroll-body]")?.className).toContain("overflow-y-auto");
    expect(preview?.tabIndex).toBe(0);
  });

  it("shows the complete write dispatch before allowing approval", async () => {
    const task = `请修改项目\n${"完整任务内容".repeat(100)}\n任务结尾`;
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "dispatch_write", assistantTargets: { project_id: "registered:1", agent_id: "agent-1", dispatch_id: "dispatch-1" },
        assistantRequestedPermission: "workspace_write", assistantTask: task } } });
    const preview = container.querySelector<HTMLElement>("[data-approval-full-preview]");
    for (const value of ["registered:1", "agent-1", "dispatch-1", "workspace_write", task]) expect(preview?.textContent).toContain(value);
    expect(preview?.closest("[data-approval-scroll-body]")?.className).toContain("overflow-y-auto");
    expect(preview?.tabIndex).toBe(0);
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
    expect(approve?.disabled).toBe(false);
    await act(async () => container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })));
    await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(true);
  });

  it("shows the complete recovery request and allows its native approval", async () => {
    const suffix = "a".repeat(40);
    const targets = { sourceProjectId: "source-1", instanceId: "instance-1", assistantAgentId: "agent-1", operationId: `initial-${suffix}`,
      syncId: `affairs-${suffix}`, sourceSnapshotDigest: "b".repeat(64), previousAuthorizationHead: "c".repeat(64) };
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a", toolName: "personal_assistant_manage_tool",
      status: "pending", risk: "high", availableDecisions: ["accept", "decline"], argumentSummary: { assistantAction: "reminder_handoff_recover",
        assistantOperationDescription: "重新审批当前来源快照并继续原编号交接；原记录保留。旧进程实际权限与发送者停止尚未证明；不重放已开始或未知的写入。", assistantTargets: targets } } });
    const preview = container.querySelector<HTMLElement>("[data-approval-full-preview]");
    for (const value of Object.values(targets)) expect(preview?.textContent).toContain(value);
    expect(preview?.textContent).toContain("旧进程实际权限与发送者停止尚未证明");
    expect(preview?.textContent).toContain("不重放已开始或未知的写入");
    expect(preview?.tabIndex).toBe(0);
    expect([...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"))?.disabled).toBe(false);
    await act(async () => container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true }))); await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(true);
  });

  it.each(["missing", "extra", "forged", "truncated", "description"])("blocks recovery approval and Y for %s details", async invalid => {
    const suffix = "a".repeat(40);
    const targets: Record<string, unknown> = { sourceProjectId: "source-1", instanceId: "instance-1", assistantAgentId: "agent-1", operationId: `initial-${suffix}`,
      syncId: `affairs-${suffix}`, sourceSnapshotDigest: "b".repeat(64), previousAuthorizationHead: "c".repeat(64) };
    if (invalid === "missing") delete targets.instanceId;
    if (invalid === "extra") targets.extra = "forged";
    if (invalid === "forged") targets.syncId = `affairs-${"d".repeat(40)}`;
    if (invalid === "truncated") targets.sourceSnapshotDigest = "b".repeat(63);
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a", toolName: "personal_assistant_manage_tool",
      status: "pending", risk: "high", availableDecisions: ["accept", "decline"], argumentSummary: { assistantAction: "reminder_handoff_recover",
        assistantOperationDescription: invalid === "description" ? undefined : "重新审批当前来源快照并继续原编号交接；原记录保留。旧进程实际权限与发送者停止尚未证明；不重放已开始或未知的写入。", assistantTargets: targets } } });
    expect(container.textContent).toContain("参数无法核对");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"));
    expect(approve?.disabled).toBe(true);
    expect(reject?.disabled).toBe(false);
    await act(async () => { approve?.click(); container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })); });
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(false);
  });

  it("blocks button and keyboard approval when the write dispatch task is missing", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "dispatch_write", assistantTargets: { project_id: "registered:1", agent_id: "agent-1", dispatch_id: "dispatch-1" },
        assistantRequestedPermission: "workspace_write" } } });
    expect(container.textContent).toContain("参数无法核对");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"));
    expect(approve?.disabled).toBe(true);
    expect(reject?.disabled).toBe(false);
    await act(async () => { approve?.click(); container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })); });
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(false);
  });

  it.each([null, {}, { assistantAction: "unknown_action" }])("fails closed for a missing or unknown management action while allowing rejection", async argumentSummary => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"], argumentSummary } });
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"));
    expect(approve?.disabled).toBe(true);
    expect(reject?.disabled).toBe(false);
    await act(async () => { approve?.click(); container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })); });
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(false);
    await act(async () => reject?.click()); await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "decline")).toBe(true);
  });

  it.each(["episodic_sync", "initial_migration_queue", "knowledge_sync_queue", "knowledge_sync_recover", "reminder_handoff_queue"])("allows a recognized native management action %s", async action => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: action, assistantOperationDescription: "原生迁移说明" } } });
    expect(container.querySelector<HTMLElement>("[data-approval-full-preview]")?.textContent).toContain("原生迁移说明");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
    expect(approve?.disabled).toBe(false);
    await act(async () => approve?.click()); await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(true);
  });

  it("prevents approval when the requested permissions cannot be verified", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantArgumentsInvalid: true } } });
    expect(container.textContent).toContain("参数无法核对");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("拒绝"));
    expect(approve?.disabled).toBe(true);
    expect(reject?.disabled).toBe(false);
    await act(async () => container.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })));
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(false);
  });

  it("shows when task receipts cannot be reported automatically", async () => {
    await renderAssistant({ patrol: { state: "ready", deliveryStates: { unknown: 1 } } });
    expect(container.textContent).toContain("部分任务结果暂未汇报，可在对话中让助理查询");
  });
  it("keeps the conversation mounted while opening and dismissing unavailable computer controls", async () => {
    await renderAssistant({ legacyToolbar: true });
    const transcript = container.querySelector('[data-testid="native-conversation"]');
    expect(invoke.mock.calls.some(([request]) => request.operation === "computerWindows")).toBe(false);
    const button = [...container.querySelectorAll("button")].find(item => item.textContent?.includes("电脑操作"));
    expect(button).toBeTruthy();
    await act(async () => { button?.click(); });
    await settle(); await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "computerWindows")).toBe(false);
    expect(container.textContent).toContain("测试驱动未连接");
    expect(container.querySelector('[data-testid="native-conversation"]')).toBe(transcript);
    const collapse = [...container.querySelectorAll("button")].find(item => item.textContent === "暂不允许");
    expect(collapse).toBeTruthy();
    await act(async () => { collapse?.click(); });
    await settle(); await settle();
    expect(container.querySelector('[data-testid="native-conversation"]')).toBe(transcript);
    expect(container.textContent).not.toContain("测试驱动未连接");
  });
  it("paints the embedded recipe in both themes, including below a transparent wallpaper", async () => {
    await renderAssistant({ capability: false });
    const expanded = container.querySelector<HTMLElement>('[data-expanded="true"]')!;
    // Compile the real component classes, including the VUI recipe defaults.
    // DOM style resolution catches both competing utilities and the wallpaper
    // shorthand clearing an otherwise opaque background-color.
    const compiler = await compile("@tailwind utilities;");
    presentation = document.createElement("style");
    presentation.textContent = tokenCss + compiler.build(expanded.className.split(/\s+/))
      + launcherCss.replace(/^@(import|source)\s[^\n]+/gm, "");
    document.head.append(presentation);
    for (const [theme, color] of [["light", "#ffffff"], ["dark", "#252629"]]) {
      document.documentElement.dataset.theme = theme;
      expanded.dataset.themeBackground = "default";
      expect(getComputedStyle(expanded).backgroundColor, `${theme} default`).toBe(color);
      expanded.dataset.themeBackground = "custom";
      expanded.style.setProperty("--workbench-theme-background-image", "linear-gradient(transparent, transparent)");
      expect(getComputedStyle(expanded).backgroundColor, `${theme} wallpaper underlay`).toBe(color);
    }
  });

  it("binds the canonical readable composite where the recipe-local overlay is defined", () => {
    const imageOwner = launcherCss.match(/\.launcher-assistant-chat-window\[data-theme-background="custom"\]\s*\{([^}]+)\}/)?.[1] || "";
    const readable = (source: string) => source.match(/--vui-gradient-background-readable:\s*([^;]+);/)?.[1].replace(/\s+/g, " ").trim();
    // An inherited :root composite cannot see a variable first declared on a
    // descendant. Its invalid layer would discard the entire image shorthand.
    expect(readable(imageOwner)).toBeTruthy();
    expect(readable(imageOwner)).toBe(readable(tokenCss));
    expect(imageOwner).toContain("--theme-background-overlay-mid:");
    expect(imageOwner).toContain("background-image: var(--vui-gradient-background-readable), var(--workbench-theme-background-image), var(--vui-gradient-route-soft)");
  });

  it("shows current images when the page opens and switches or clears once per native terminal", async () => {
    await renderAssistant({ startHidden: true });
    expect(assetReads()).toBe(0);
    expect(container.querySelector("[data-theme-background]")).toBeNull();
    await showPage(true);
    expect(assetReads()).toBe(2);
    expect(container.querySelector("img")?.getAttribute("src")).toBe("data:image/png;base64,AQI=");
    const expanded = () => container.querySelector<HTMLElement>('[data-expanded="true"]')!;
    expect(expanded().dataset.operatorAvatar).toBe("custom");
    expect(expanded().dataset.themeBackground).toBe("custom");
    expect(expanded().dataset.themeBackgroundReadability).toBe("soft");
    expect(expanded().style.getPropertyValue("--workbench-theme-background-image").includes("AwQ=")).toBe(true);
    assets.avatar = asset("avatar", "BQY="); assets.background = asset("background", "Bwg=", "strong");
    await finishTurn("image-turn-1");
    expect(assetReads()).toBe(4);
    expect(container.querySelector("img")?.getAttribute("src")).toBe("data:image/png;base64,BQY=");
    expect(expanded().dataset.themeBackgroundReadability).toBe("strong");
    await finishTurn("image-turn-1"); expect(assetReads()).toBe(4);
    assets.avatar = asset("avatar", null); assets.background = asset("background", null);
    await finishTurn("image-turn-2");
    expect(assetReads()).toBe(6);
    expect(container.querySelector("img")).toBeNull();
    expect(expanded().dataset.operatorAvatar).toBe("default");
    expect(expanded().dataset.themeBackground).toBe("default");
    expect(expanded().style.getPropertyValue("--workbench-theme-background-image")).toBe("");
    expect(conversation?.userDisplayName).toBe("当前用户");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("refreshes only changed image revisions on idle status updates", async () => {
    await renderAssistant();
    revisions = { avatar: "a".repeat(64), background: "b".repeat(64) };
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "status"] }); });
    await settle();
    expect(assetReads()).toBe(2);
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "status"] }); });
    await settle(); expect(assetReads()).toBe(2);
    assets.avatar = asset("avatar", "BQY=");
    revisions = { ...revisions, avatar: "c".repeat(64) };
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "status"] }); });
    await settle(); await settle();
    expect(assetReads()).toBe(3);
    expect(container.querySelector("img")?.getAttribute("src")).toBe("data:image/png;base64,BQY=");
    assets.background = asset("background", "Bwg=", "strong");
    revisions = { ...revisions, background: "d".repeat(64) };
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "status"] }); });
    await settle(); await settle();
    expect(assetReads()).toBe(4);
    expect(container.querySelector<HTMLElement>('[data-expanded="true"]')?.style.getPropertyValue("--workbench-theme-background-image")).toContain("Bwg=");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not read images after leaving the page and reads the current choice on reopening", async () => {
    await renderAssistant();
    await showPage(false); const reads = assetReads();
    assets.background = asset("background", "CQo=");
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "operator-asset"] }); });
    expect(assetReads()).toBe(reads);
    expect(client.getQueryState(["launcher-assistant", "operator-asset", "background", "s"])?.isInvalidated).toBe(true);
    expect(container.querySelector("[data-theme-background]")).toBeNull();
    await showPage(true);
    expect(assetReads()).toBe(reads + 2);
    expect(container.querySelector<HTMLElement>('[data-expanded="true"]')?.style.getPropertyValue("--workbench-theme-background-image").includes("CQo=")).toBe(true);
    await settle(); expect(assetReads()).toBe(reads + 2);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps old hosts on the default native identity without any image IPC", async () => {
    await renderAssistant({ capability: false });
    await finishTurn("old-host-turn"); await showPage(false); await showPage(true);
    expect(assetReads()).toBe(0); expect(container.querySelector("img")).toBeNull();
    expect(invoke.mock.calls.some(([request]) => request.operation === "assistantAvatar")).toBe(false);
    expect(conversation?.userDisplayName).toBe("当前用户"); expect(fetch).not.toHaveBeenCalled();
  });

  it("defers expanded image reads while the document is hidden", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await renderAssistant();
    expect(assetReads()).toBe(0);
    await act(async () => {
      visibility.mockReturnValue("visible"); document.dispatchEvent(new Event("visibilitychange"));
    });
    await settle(); await settle();
    expect(assetReads()).toBe(2);
    expect(container.querySelector("img")).toBeTruthy();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps image errors local, allows sending, and retries only the failed resource", async () => {
    await renderAssistant({ failAvatar: true });
    expect(container.textContent).toContain("部分外观图片暂不可用，聊天仍可使用");
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
    expect(container.querySelector('[data-theme-background="custom"]')).toBeTruthy();
    expect(conversation?.composerDisabled).toBe(false);
    await act(async () => conversation!.onComposerChange!("hello"));
    await act(async () => conversation!.onSubmit!()); await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "send" && request.message === "hello")).toBe(true);
    const reads = assetReads(); failingAvatar = false;
    await act(async () => Array.from(container.querySelectorAll("button")).find(button => button.textContent === "重试")?.click());
    await settle(); await settle();
    expect(assetReads()).toBe(reads + 1);
    expect(container.querySelector("img")).toBeTruthy();
    expect(container.textContent).not.toContain("部分外观图片暂不可用");
    expect(fetch).not.toHaveBeenCalled();
  });
});
