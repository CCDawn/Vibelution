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
      createElement("span", null, props.userDisplayName || "default user"));
  },
}));

let root: Root | undefined;
let container: HTMLDivElement;
let client: QueryClient;
let detail: Record<string, unknown>;
let assets: { avatar: Record<string, unknown>; background: Record<string, unknown> };
let revisions: { avatar: string | null; background: string | null } | undefined;
let invoke: ReturnType<typeof vi.fn>;
let failingAvatar = false;
let presentation: HTMLStyleElement | undefined;
let fetch: ReturnType<typeof vi.fn>;
const image = (dataBase64: string) => ({ contentType: "image/png", dataBase64, sha256: "a".repeat(64) });
const asset = (kind: "avatar" | "background", dataBase64: string | null, readability = "standard") => ({
  schemaVersion: 1, kind, image: dataBase64 === null ? null : image(dataBase64), readability,
});
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined;
  client?.clear(); container?.remove(); conversation = undefined;
  presentation?.remove(); presentation = undefined;
  delete document.documentElement.dataset.theme;
  vi.unstubAllGlobals(); vi.clearAllMocks(); vi.restoreAllMocks();
});
async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
}
async function click(label: string) {
  await act(async () => {
    const button = container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
    expect(Boolean(button)).toBe(true); button?.click();
  });
  await settle(); await settle();
}
function assetReads() { return invoke.mock.calls.filter(([request]) => request.operation === "operatorAsset").length; }
async function renderAssistant(options: { capability?: boolean; failAvatar?: boolean; approval?: Record<string, unknown>; language?: "zh" | "en"; patrol?: { state: "ready" | "unavailable"; deliveryStates: Record<string, number> } } = {}) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  failingAvatar = Boolean(options.failAvatar);
  detail = { id: "s", agentId: "a", status: "ready", messages: [] };
  revisions = undefined;
  assets = { avatar: asset("avatar", "AQI="), background: asset("background", "AwQ=", "soft") };
  fetch = vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }); vi.stubGlobal("fetch", fetch);
  invoke = vi.fn(async request => {
    switch (request.operation) {
      case "status": return {
        assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
        operatorProfile: { displayName: "当前用户", avatarPreset: "initial" },
        ...(revisions ? { operatorAssetRevisions: revisions } : {}),
        ...(options.patrol ? { patrol: options.patrol } : {}),
        ...(options.capability === false ? {} : { operatorAssetsVersion: 1 }),
      };
      case "config": return { language: options.language ?? "zh" };
      case "detail": return detail;
      case "approvals": return options.approval ? [options.approval] : [];
      case "resolveApproval": return { ...options.approval, status: request.decision === "decline" ? "rejected" : "approved" };
      case "dispatches": return { dispatches: [] };
      case "computerState": return { available: false, status: "idle", message: "测试驱动未连接", grantId: null, window: null, pending: null };
      case "computerWindows": return { windows: [] };
      case "setExpanded": return { expanded: request.expanded };
      case "operatorAsset":
        if (Object.keys(request).sort().join(",") !== "kind,operation" || !["avatar", "background"].includes(request.kind)) throw new Error("invalid_asset_request");
        if (failingAvatar && request.kind === "avatar") throw new Error("image unavailable");
        return assets[request.kind as keyof typeof assets];
      case "send": return { accepted: true, turnId: "sent-turn" };
      default: throw new Error("unexpected_operation");
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root!.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantRoute))));
  await settle(); await settle();
}
async function finishTurn(turnId: string) {
  detail = { ...detail, lastTurnTerminalTurnId: turnId, terminalReason: "success" };
  await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "detail"] }); });
  await settle(); await settle();
}

describe("Launcher operator image consumption", () => {
  it("shows the complete project lifecycle request before approval", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "project_lifecycle", assistantTargets: {
        project_id: "registered:1", operation: "restart", request_id: "lifecycle-1",
      } } } });
    await click("展开个人助理聊天");
    expect(container.textContent).toContain("项目: registered:1");
    expect(container.textContent).toContain("操作: 重启");
    expect(container.textContent).toContain("请求 ID: lifecycle-1");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("是"));
    expect(approve?.disabled).toBe(false);
  });

  it("blocks approval when project lifecycle details cannot be verified", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "project_lifecycle", assistantTargets: { project_id: "registered:1", operation: "stop" } } } });
    await click("展开个人助理聊天");
    expect(container.textContent).toContain("参数无法核对");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("是"));
    expect(approve?.disabled).toBe(true);
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })));
    await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval")).toBe(false);
  });

  it("shows the complete project permission request on the actual assistant route", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "authorization_upgrade", assistantTargets: { project_id: "registered:1" },
        assistantAddedScopes: ["source:read", "tasks:read"] } } });
    await click("展开个人助理聊天");
    const preview = container.querySelector("pre");
    expect(preview?.textContent).toContain("registered:1");
    expect(preview?.textContent).toContain("source:read");
    expect(preview?.textContent).toContain("tasks:read");
    expect(preview?.className).toContain("overflow-y-auto");
    expect(preview?.tabIndex).toBe(0);
  });

  it("shows the complete write dispatch before allowing approval", async () => {
    const task = `请修改项目\n${"完整任务内容".repeat(100)}\n任务结尾`;
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "dispatch_write", assistantTargets: { project_id: "registered:1", agent_id: "agent-1", dispatch_id: "dispatch-1" },
        assistantRequestedPermission: "workspace_write", assistantTask: task } } });
    await click("展开个人助理聊天");
    const preview = container.querySelector("pre");
    for (const value of ["registered:1", "agent-1", "dispatch-1", "workspace_write", task]) expect(preview?.textContent).toContain(value);
    expect(preview?.className).toContain("overflow-y-auto");
    expect(preview?.tabIndex).toBe(0);
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("是"));
    expect(approve?.disabled).toBe(false);
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })));
    await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(true);
  });

  it("blocks button and keyboard approval when the write dispatch task is missing", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: "dispatch_write", assistantTargets: { project_id: "registered:1", agent_id: "agent-1", dispatch_id: "dispatch-1" },
        assistantRequestedPermission: "workspace_write" } } });
    await click("展开个人助理聊天");
    expect(container.textContent).toContain("参数无法核对");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("是"));
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("否"));
    expect(approve?.disabled).toBe(true);
    expect(reject?.disabled).toBe(false);
    await act(async () => { approve?.click(); window.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })); });
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(false);
  });

  it.each([null, {}, { assistantAction: "unknown_action" }])("fails closed for a missing or unknown management action while allowing rejection", async argumentSummary => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"], argumentSummary } });
    await click("展开个人助理聊天");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("是"));
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("否"));
    expect(approve?.disabled).toBe(true);
    expect(reject?.disabled).toBe(false);
    await act(async () => { approve?.click(); window.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })); });
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(false);
    await act(async () => reject?.click()); await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "decline")).toBe(true);
  });

  it.each(["episodic_sync", "initial_migration_queue", "knowledge_sync_queue", "knowledge_sync_recover", "reminder_handoff_queue"])("allows a recognized native management action %s", async action => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantAction: action, assistantOperationDescription: "原生迁移说明" } } });
    await click("展开个人助理聊天");
    expect(container.querySelector("pre")?.textContent).toContain("原生迁移说明");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("是"));
    expect(approve?.disabled).toBe(false);
    await act(async () => approve?.click()); await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(true);
  });

  it("prevents approval when the requested permissions cannot be verified", async () => {
    await renderAssistant({ approval: { requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "personal_assistant_manage_tool", status: "pending", risk: "high", availableDecisions: ["accept", "decline"],
      argumentSummary: { assistantArgumentsInvalid: true } } });
    await click("展开个人助理聊天");
    expect(container.textContent).toContain("参数无法核对");
    const approve = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("是"));
    const reject = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("否"));
    expect(approve?.disabled).toBe(true);
    expect(reject?.disabled).toBe(false);
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "y", bubbles: true })));
    expect(invoke.mock.calls.some(([request]) => request.operation === "resolveApproval" && request.decision === "accept")).toBe(false);
  });

  it("shows when task receipts cannot be reported automatically", async () => {
    await renderAssistant({ patrol: { state: "ready", deliveryStates: { unknown: 1 } } });
    await click("展开个人助理聊天");
    expect(container.textContent).toContain("部分任务回执无法自动汇报，请查看派发回执");
  });
  it("opens computer controls only on request and returns to the conversation", async () => {
    await renderAssistant();
    await click("展开个人助理聊天");
    expect(invoke.mock.calls.some(([request]) => request.operation === "computerWindows")).toBe(false);
    const button = [...container.querySelectorAll("button")].find(item => item.textContent?.includes("电脑操作"));
    expect(button).toBeTruthy();
    await act(async () => { button?.click(); });
    await settle(); await settle();
    expect(invoke.mock.calls.some(([request]) => request.operation === "computerWindows")).toBe(true);
    expect(container.textContent).toContain("测试驱动未连接");
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeNull();
    const collapse = container.querySelector<HTMLButtonElement>('button[aria-label="收起电脑操作栏"]');
    expect(collapse).toBeTruthy();
    await act(async () => { collapse?.click(); });
    await settle(); await settle();
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
  });
  it("paints the expanded recipe in both themes, including below a transparent wallpaper, and keeps the avatar transparent", async () => {
    await renderAssistant({ capability: false });
    const collapsed = container.querySelector<HTMLElement>('[data-expanded="false"]')!;
    expect(["", "transparent", "rgba(0, 0, 0, 0)"]).toContain(getComputedStyle(collapsed).backgroundColor);
    await click("展开个人助理聊天");
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
    await click("收起聊天");
    expect(["", "transparent", "rgba(0, 0, 0, 0)"]).toContain(getComputedStyle(container.querySelector<HTMLElement>('[data-expanded="false"]')!).backgroundColor);
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

  it("shows current images on initial expansion and switches or clears once per native terminal", async () => {
    await renderAssistant();
    expect(assetReads()).toBe(0);
    expect(container.querySelector("[data-theme-background]")).toBeNull();
    await click("展开个人助理聊天");
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
    await settle(); await click("展开个人助理聊天");
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

  it("does not read images while collapsed and reads the current choice on reopening", async () => {
    await renderAssistant(); await click("展开个人助理聊天");
    await click("收起聊天"); const reads = assetReads();
    assets.background = asset("background", "CQo=");
    await finishTurn("collapsed-settings-turn");
    expect(assetReads()).toBe(reads);
    expect(client.getQueryState(["launcher-assistant", "operator-asset", "background", "s"])?.isInvalidated).toBe(true);
    expect(container.querySelector('[data-expanded="false"]')).toBeTruthy();
    expect(container.querySelector("[data-theme-background]")).toBeNull();
    await click("展开个人助理聊天");
    expect(assetReads()).toBe(reads + 2);
    expect(container.querySelector<HTMLElement>('[data-expanded="true"]')?.style.getPropertyValue("--workbench-theme-background-image").includes("CQo=")).toBe(true);
    await settle(); expect(assetReads()).toBe(reads + 2);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps old hosts on the default native identity without any image IPC", async () => {
    await renderAssistant({ capability: false }); await click("展开个人助理聊天");
    await finishTurn("old-host-turn"); await click("收起聊天"); await click("展开个人助理聊天");
    expect(assetReads()).toBe(0); expect(container.querySelector("img")).toBeNull();
    expect(conversation?.userDisplayName).toBe("当前用户"); expect(fetch).not.toHaveBeenCalled();
  });

  it("defers expanded image reads while the document is hidden", async () => {
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await renderAssistant(); await click("展开个人助理聊天");
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
    await renderAssistant({ failAvatar: true }); await click("展开个人助理聊天");
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
