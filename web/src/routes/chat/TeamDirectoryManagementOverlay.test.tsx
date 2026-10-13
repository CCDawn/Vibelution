/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Team, TeamListPayload } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import { archiveTeam, fetchTeam, updateTeam } from "../../api/teams";
import { fetchAgentConfigWorkspace } from "../../api/agents";
import { TeamDirectoryManagementOverlay } from "./TeamDirectoryManagementOverlay";
import { AgentConversationDirectory } from "../AgentConversationDirectory";

vi.mock("../../api/teams", () => ({ archiveTeam: vi.fn(), fetchTeam: vi.fn(), updateTeam: vi.fn(), syncTeamChatRoom: vi.fn() }));
vi.mock("../../api/agents", () => ({ fetchAgentConfigWorkspace: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({
  startUserAction: () => ({ succeeded: vi.fn(), failed: vi.fn() }),
}));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const team = { teamId: "team-a", name: "研发团队", status: "active", systemManaged: false, members: [], memberCount: 0,
  linkedChatRoomId: "room-a", linkedChatRoom: { roomId: "room-a", status: "active" } } as Team;
let root: Root | undefined;
let client: QueryClient;
async function render(ui: React.ReactNode) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(queryKeys.teams(), { teams: [team] });
  const host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => { root?.render(<QueryClientProvider client={client}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>); });
}
async function flush() { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); }); }
function button(text: string) { return [...document.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent === text)!; }
afterEach(async () => {
  await act(async () => root?.unmount());
  client?.clear();
  document.body.innerHTML = "";
  localStorage.clear();
  vi.resetAllMocks();
});
describe("team directory management", () => {
  it("sends only the new name, rejects a double submit and updates the rail cache", async () => {
    let resolveUpdate!: (result: Team) => void;
    vi.mocked(updateTeam).mockReturnValue(new Promise((resolve) => { resolveUpdate = resolve; }));
    const onClose = vi.fn();
    await render(<TeamDirectoryManagementOverlay action={{ teamId: team.teamId, mode: "rename" }} team={team} teams={[team]} lang="zh" onClose={onClose} />);
    const input = document.querySelector<HTMLInputElement>('input')!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(input, " 新研发团队 ");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { button("保存").click(); button("保存").click(); });
    expect(updateTeam).toHaveBeenCalledTimes(1);
    expect(updateTeam).toHaveBeenCalledWith(team.teamId, { name: "新研发团队" });
    await act(async () => resolveUpdate({ ...team, name: "新研发团队" }));
    await flush();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(client.getQueryData<TeamListPayload>(queryKeys.teams())?.teams[0].name).toBe("新研发团队");
  });
  it("keeps a failed archive visible and never archives before confirmation", async () => {
    vi.mocked(archiveTeam).mockRejectedValue(new Error("群聊正在运行，不能归档"));
    const onClose = vi.fn();
    await render(<TeamDirectoryManagementOverlay action={{ teamId: team.teamId, mode: "archive" }} team={team} teams={[team]} lang="zh" onClose={onClose} />);
    expect(document.body.textContent).toContain("群聊房间会被删除");
    expect(document.body.textContent).toContain("当前成员 Agent 会一并归档");
    expect(archiveTeam).not.toHaveBeenCalled();
    await act(async () => button("确认归档").click());
    await flush();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("群聊正在运行");
    expect(onClose).not.toHaveBeenCalled();
    expect(client.getQueryData<TeamListPayload>(queryKeys.teams())?.teams[0].status).toBe("active");
  });
  it("loads the full roster only for management and offers retry on load failure", async () => {
    vi.mocked(fetchTeam).mockRejectedValue(new Error("团队读取失败"));
    vi.mocked(fetchAgentConfigWorkspace).mockResolvedValue({ agents: [] } as never);
    await render(<TeamDirectoryManagementOverlay action={{ teamId: team.teamId, mode: "settings" }} team={team} teams={[team]} lang="zh" onClose={() => undefined} />);
    await flush();
    expect(fetchTeam).toHaveBeenCalledWith(team.teamId, expect.objectContaining({ detail: "full" }));
    expect(document.body.textContent).toContain("团队读取失败");
    vi.mocked(fetchTeam).mockResolvedValue(team);
    await act(async () => button("重试").click());
    await flush();
    expect(document.body.textContent).toContain("基本信息");
  });
  it("opens a header menu without expanding or navigating; hide survives reload and restores", async () => {
    const directory = <AgentConversationDirectory activeAgentId="" agents={[]} teams={[team]} avatarInitials={() => ""}
      filterText="" formatTime={() => ""} lang="zh" resolveModelLabel={() => undefined} sessions={[]}
      statusLabel={(value) => value} onContextMenu={() => undefined} onOpenAgent={() => undefined} />;
    await render(directory);
    const header = [...document.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent?.includes("研发团队"))!;
    expect(header.getAttribute("aria-expanded")).toBe("false");
    await act(async () => header.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 80, clientY: 110 })));
    expect(header.getAttribute("aria-expanded")).toBe("false");
    const hide = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) => item.textContent?.includes("隐藏团队"))!;
    await act(async () => hide.click());
    expect(document.querySelector('[aria-haspopup="menu"]')).toBeNull();
    expect(document.body.textContent).toContain("已隐藏团队（1）");
    expect(updateTeam).not.toHaveBeenCalled();
    expect(archiveTeam).not.toHaveBeenCalled();
    await act(async () => root?.unmount());
    root = undefined;
    await render(directory);
    expect(document.querySelector('[aria-haspopup="menu"]')).toBeNull();
    await act(async () => button("已隐藏团队（1）").click());
    await act(async () => button("恢复").click());
    expect(document.querySelector('[aria-haspopup="menu"]')?.textContent).toContain("研发团队");
  });
});
