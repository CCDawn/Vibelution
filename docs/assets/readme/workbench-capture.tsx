// Full production Chat route, isolated from all backends and model providers.
import React from "react";
import { createRoot } from "react-dom/client";
import { VuiProvider } from "../../../web/src/components/vui";
import type { AgentInstance, ChatWorkbenchBootstrap, ConfigSummary, ConversationMessage, GitFileDiff, GitStatusSummary, RuntimeSummary, SessionDetail, SessionQueryResponse, SessionSummary } from "../../../web/src/api/types";
import "./workbench-capture.css";

const lang = new URLSearchParams(location.search).get("lang") === "en" ? "en" : "zh";
const en = lang === "en";
const overview = new URLSearchParams(location.search).get("view") === "workbench-overview";
const pick = (zh: string, english: string) => en ? english : zh;
const timestamp = "2026-10-11T08:00:00Z";
const sessionId = "showcase-session";
const workspace = "example/task-board";
const avatarImageUrl = "/web/public/vibelution-icon-192.png";
document.documentElement.lang = lang;
document.documentElement.dataset.theme = "light";

const agents: AgentInstance[] = [
  ["reviewer", pick("项目评审", "Project reviewer"), sessionId],
  ["researcher", pick("资料研究", "Research assistant"), "source-session"],
].map(([agentId, displayName, directSessionId]) => ({
  agentId, agentCode: agentId, displayName, directSessionId, avatarImageUrl,
  kind: "persistent", primaryMode: "chat", roleKey: "general",
  llmBindings: {}, promptTemplateId: "default", workspacePath: workspace,
  toolPolicyId: "example", memoryPolicyId: "example", createdBy: "public-example",
  status: "idle", metadata: {}, createdAt: timestamp, updatedAt: timestamp,
  configSchemaVersion: 1, configRevision: 1, configHash: "public-example",
  permissionPreset: "request_approval",
  runtimePermissions: { preset: "request_approval", sandboxMode: "workspace_write", approvalPolicy: "on_request", approvalsReviewer: "user" },
}));
const sessions: SessionSummary[] = [
  { id: sessionId, title: pick("键盘操作指南", "Keyboard guide"), agentId: "reviewer", agentDisplayName: agents[0].displayName, taskSummary: pick("检查任务看板，整理文档与改动", "Review the task board and document changes") },
  { id: "source-session", title: pick("整理项目资料", "Organize project sources"), agentId: "researcher", agentDisplayName: agents[1].displayName, taskSummary: pick("归纳资料来源与待核对项", "Collect sources and follow-up checks") },
].map((session) => ({ ...session, agentAvatarImageUrl: avatarImageUrl, status: "idle", currentPhase: "ready", lastActive: timestamp, updatedAt: timestamp, createdAt: timestamp, workspacePath: workspace, agentPrimaryMode: "chat", sessionKind: "main", sessionRole: "primary" }));
const answer = pick(
  `## 键盘操作说明已整理\n\n用法与验证项已写入 \`docs/keyboard.md\`。\n\n${overview ? "| 操作 | 使用方式 |\n| --- | --- |\n| 切换焦点 | Tab / Shift + Tab |\n| 打开任务 | Enter |\n| 退出详情 | Escape |" : "- **Tab / Shift + Tab**：切换焦点\n- **Enter**：打开任务\n- **Escape**：退出详情"}\n\n**下一步：** 在浏览器核对关闭详情后的焦点返回。`,
  `## Keyboard guide drafted\n\nAdded usage and checks to \`docs/keyboard.md\`.\n\n${overview ? "| Action | Keys |\n| --- | --- |\n| Move focus | Tab / Shift + Tab |\n| Open a task | Enter |\n| Close details | Escape |" : "- **Tab / Shift + Tab:** move focus\n- **Enter:** open a task\n- **Escape:** close details"}\n\n**Next:** check that focus returns to the task card after closing details.`,
);
const messages: ConversationMessage[] = [
  { id: "example-user", role: "user", timestamp, content: pick("为任务看板补充键盘操作指南，并列出浏览器验证项。", "Write a keyboard guide for the task board and list the browser checks.") },
  { id: "example-assistant", role: "assistant", timestamp, status: "completed", turnId: "example-turn", turnItems: [
    { id: "example-read", itemId: "example-read", version: 3, sessionId, turnId: "example-turn", type: "tool_call", callId: "example-read", toolName: "read_file_tool", status: "completed", revision: 1, sequence: 1, input: '{"path":"src/TaskBoard.tsx"}', summary: "src/TaskBoard.tsx", output: pick("已读取键盘处理与焦点管理代码。", "Read keyboard handlers and focus-management code.") },
    { id: "example-write", itemId: "example-write", version: 3, sessionId, turnId: "example-turn", type: "tool_call", callId: "example-write", toolName: "apply_patch_tool", status: "completed", revision: 1, sequence: 2, input: '{"path":"docs/keyboard.md"}', summary: "docs/keyboard.md", output: pick("已整理操作说明与浏览器检查项。", "Drafted the keyboard guide and browser checks.") },
    { id: "example-answer", itemId: "example-answer", version: 3, sessionId, turnId: "example-turn", type: "agent_message", phase: "final_answer", status: "completed", revision: 1, sequence: 3, text: answer, terminal: true },
  ] },
];
const detail: SessionDetail = { ...sessions[0], defaultFileContext: "workspace", previewTabs: [], activePreviewPath: "", changedFiles: ["docs/keyboard.md"], readFiles: ["src/TaskBoard.tsx"], messages, stopRequested: false, stopRequestedAt: "", stopReason: "", messageWindow: { mode: "window", totalMessages: 2, returnedMessages: 2, oldestMessageIndex: 0, newestMessageIndex: 1, hasEarlier: false, hasLater: false, transcriptScope: "window" } };
const sessionPage: SessionQueryResponse = { items: sessions, nextCursor: "", totalEstimate: sessions.length, filters: { q: "", agentId: "", sessionKind: "", state: "", sort: "", limit: 50, cursor: "" } };
const bootstrap: ChatWorkbenchBootstrap = { activeSessionId: sessionId, sessionPage, agents, conversations: [], directoryReady: true };
const availability = { chat: true, self_evolution: true, supervised_evolution: true };
const domains = { chat: true, evolution: true, config: true };
const config: ConfigSummary = { hash: "public-example", language: lang, runtimeProfile: "example", defaultMode: "chat", defaultRoute: "/chat", intakeMode: "manual", modeAvailability: availability, domainAvailability: domains, modelLibraryCount: 0, modelLabels: {}, modelImageInputSupport: {}, blockingCount: 0, warningCount: 0, sections: [] };
const runtime = { status: "idle", mode: "chat", model: "", profile: "example", defaultRoute: "/chat", intakeMode: "manual", modeAvailability: availability, domainAvailability: domains, agentName: agents[0].displayName, userName: pick("你", "You"), agentStatusLine: "", sessionTitle: sessions[0].title, taskSummary: sessions[0].taskSummary, currentPhase: "ready", sessionState: "idle", sessionStateLine: "", sessionNeedsResponse: false, sessionToolName: "", sessionUpdatedAt: timestamp, activeTools: [], changedFilesCount: 1, recentAction: "", contextUsage: { used: 0, limit: 0 }, runtimeManager: { running: false, runtimeState: "idle", managerPid: 0, stateVersion: 0 } } satisfies Partial<RuntimeSummary>;
const fileContent = pick("# 键盘操作\n\n- Tab：切换焦点\n- Enter：打开任务\n- Escape：关闭详情\n\n## 浏览器检查\n\n- [ ] 关闭详情后焦点返回任务卡片\n- [ ] Shift + Tab 能反向导航\n", "# Keyboard guide\n\n- Tab: move focus\n- Enter: open a task\n- Escape: close details\n\n## Browser checks\n\n- [ ] Focus returns to the task card\n- [ ] Shift + Tab navigates backwards\n");
const gitDiff: GitFileDiff = { available: true, error: "", path: "docs/keyboard.md", status: "A", statusLabel: pick("新增", "Added"), summary: pick("键盘操作与浏览器检查项", "Keyboard guide and browser checks"), diff: `diff --git a/docs/keyboard.md b/docs/keyboard.md\nnew file mode 100644\n--- /dev/null\n+++ b/docs/keyboard.md\n@@ -0,0 +1,11 @@\n${fileContent.trimEnd().split("\n").map((line) => `+${line}`).join("\n")}\n`, content: fileContent, language: "markdown", truncated: false, binary: false };
const gitStatus: GitStatusSummary = { available: true, error: "", branch: "docs/keyboard-guide", headRev: "", headRevShort: "", upstream: { name: "", remote: "", ahead: 0, behind: 0, hasUpstream: false }, snapshotId: "public-example", createdAt: timestamp, dirty: true, requiresAttention: false, statusLevel: "dirty", summary: pick("1 个文件待审查", "1 file to review"), counts: { total: 1, staged: 0, unstaged: 0, untracked: 1, deleted: 0 }, localCommits: { available: true, error: "", total: 0, commits: [], truncated: false }, worktrees: { available: true, error: "", total: 0, external: 0, withCommits: 0, items: [], truncated: false }, files: [{ path: "docs/keyboard.md", status: "??", statusLabel: pick("新增", "Added"), staged: false, unstaged: false, untracked: true, deleted: false, oldPath: "" }], totalFiles: 1, truncated: false };
const noTasks = { revision: "public-example", running: [], ended: { items: [], total: 0, nextCursor: "" } };

// Exact GET fixtures and one inert route-selection response; no mutations.
const fixtures = new Map<string, unknown>([
  ["/api/control-token", { header: "X-Vibelution-Control-Token", controlToken: "PUBLIC-DOCUMENTATION-EXAMPLE-NOT-A-CREDENTIAL" }],
  ["/api/health", { status: "ok" }],
  ["/api/config/public", config],
  ["/api/runtime/summary", runtime],
  ["/api/sessions/bootstrap?limit=50", bootstrap],
  ["/api/sessions/query?limit=50", sessionPage],
  ["/api/sessions/query?limit=50&sort=updatedAt_desc", sessionPage],
  ["/api/sessions/query?limit=100&agentId=reviewer", { ...sessionPage, items: [sessions[0]], totalEstimate: 1 }],
  ["/api/sessions/showcase-session/child-sessions", []],
  ["/api/sessions/active", { activeSessionId: sessionId }],
  ["/api/agents?detail=summary", agents],
  ["/api/agents/reviewer", agents[0]],
  ["/api/sessions/showcase-session?messageLimit=40&transcriptScope=window", detail],
  ["/api/sessions/showcase-session?messageLimit=40&transcriptScope=window&includeSecondary=false", detail],
  ["/api/sessions/showcase-session", detail],
  ["/api/sessions/showcase-session/tool-approvals?status=pending", []],
  ["/api/sessions/showcase-session/llm-options", { sessionId, currentModelId: "", currentReasoningEffort: "", model: null, choices: [] }],
  ["/api/sessions/showcase-session/curation", { sessionId, captureEnabled: false, items: [], countsByModel: [] }],
  ["/api/skills", []],
  ["/api/teams", { schemaVersion: 1, teams: [], summary: { teamCount: 0, activeTeamCount: 0, memberCount: 0, staleMemberCount: 0 }, updatedAt: timestamp, storage: { teamsPath: "", teamRoot: "" } }],
  ["/api/conversations?limit=100&type=group_room", { items: [], nextCursor: "", filters: {} }],
  ["/api/git/status?limit=200", gitStatus],
  ["/api/git/status?limit=500", gitStatus],
  ["/api/git/diff?path=docs%2Fkeyboard.md", gitDiff],
  ["/api/files/content?path=docs%2Fkeyboard.md", { path: "docs/keyboard.md", language: "markdown", content: fileContent, truncated: false }],
  ["/api/workbench/ui-preferences", { schemaVersion: 1, paneLayouts: {}, shell: { leftRailCollapsed: false, rightPaneCollapsed: false } }],
  ["/api/runtime-tasks?status=active&limit=50", noTasks],
  ["/api/runtime-tasks?status=active&parent_session_id=showcase-session&limit=50", noTasks],
  ["/api/runtime-tasks?status=ended&parent_session_id=showcase-session&limit=1", noTasks],
  ["/api/launcher/settings/startup", { runtime: { profile: "example", preflightDoctor: false, requireVenv: false, profileOptions: [] }, workbench: { backendPort: 0, frontendPort: 0, effectiveBackendPort: 0, effectiveFrontendPort: 0, backendPortEnvOverride: 0, frontendPortEnvOverride: 0, windowMode: "browser", effectiveWindowMode: "browser", windowModeEnvOverride: "", windowModeOptions: [] }, interface: { language: lang, languageOptions: ["zh", "en"] }, configPath: "", configHash: "example", restartRequired: false }],
]);
const requests: Array<{ method: string; path: string; served: boolean }> = [];
Object.assign(window, { __readmeRequests: requests });
window.fetch = async (input, init) => {
  const url = new URL(typeof input === "string" ? input : input instanceof Request ? input.url : input.href, location.origin);
  const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  const path = url.pathname + url.search;
  // Route selection gets a fixed response; it cannot alter even the fixture.
  if (method === "POST" && url.origin === location.origin && path === "/api/sessions/showcase-session/select") {
    requests.push({ method, path, served: true });
    return Response.json(detail);
  }
  if (method === "GET" && url.origin === location.origin && path === "/api/sessions/showcase-session/events?initial=none") {
    requests.push({ method, path, served: true });
    // An inert local stream: no network, no events, no simulated running turn.
    return new Response(new ReadableStream({ start(controller) { init?.signal?.addEventListener("abort", () => controller.close(), { once: true }); } }), { headers: { "content-type": "text/event-stream" } });
  }
  const served = method === "GET" && url.origin === location.origin && fixtures.has(path);
  requests.push({ method, path, served });
  return served ? Response.json(fixtures.get(path)) : Response.json({ detail: "Documentation fixture denies this request" }, { status: 403 });
};
// The router sees the real product URL; the static entry is already loaded.
history.replaceState(null, "", `/chat?session=${sessionId}`);
const { App } = await import("../../../web/src/app/App");
createRoot(document.getElementById("root")!).render(<VuiProvider><App /></VuiProvider>);
