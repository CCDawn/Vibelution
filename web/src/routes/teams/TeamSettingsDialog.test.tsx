/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import type { AgentConfigWorkspaceAgent, Team } from "../../api/types";
import { TeamSettingsDialog, isReadOnlyTeam } from "./TeamSettingsDialog";
import { teamSettingsCopy } from "./teamSettingsModel";
import dialogSource from "./TeamSettingsDialog.tsx?raw";
import toolbarSource from "./TeamSettingsToolbarAction.tsx?raw";
import actionsSource from "./useTeamSettingsActions.ts?raw";
import frameSource from "./renderTeamsShellFrame.tsx?raw";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function makeAgent(agentId: string, displayName: string): AgentConfigWorkspaceAgent {
  return {
    agentId,
    agentCode: agentId.toUpperCase(),
    displayName,
    status: "active",
    llmBindings: {},
  } as AgentConfigWorkspaceAgent;
}

function makeTeam(patch: Partial<Team> = {}): Team {
  return {
    teamId: "team-a",
    name: "Alpha Team",
    description: "team description",
    purpose: "team purpose",
    status: "active",
    teamKind: "custom",
    teamCategory: "自定义团队",
    teamSource: "manual",
    members: [
      {
        memberId: "member-1",
        agentId: "agent-1",
        agentCode: "A1",
        agentName: "Alpha",
        role: "lead",
        purpose: "",
        agentStatus: "active",
        model: { dialogueModelId: "", configured: false },
      },
    ],
    memberCount: 1,
    updatedAt: "2026-10-06T00:00:00Z",
    ...patch,
  } as Team;
}

const baseAgents = [makeAgent("agent-1", "Alpha"), makeAgent("agent-2", "Beta")];
const baseAgentsById = new Map(baseAgents.map((agent) => [agent.agentId, agent]));

function renderDialog(ui: React.ReactElement) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(<MemoryRouter>{ui}</MemoryRouter>);
  });
  return { host, root };
}

function buttonByText(text: string): HTMLButtonElement | null {
  const nodes = Array.from(document.body.querySelectorAll("button"));
  return nodes.find((node) => (node.textContent || "").includes(text)) ?? null;
}

function click(node: HTMLElement) {
  act(() => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

function setInputValue(element: HTMLInputElement | HTMLTextAreaElement, nextValue: string) {
  const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  setter?.call(element, nextValue);
  act(() => {
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function inputByLabel(label: string): HTMLInputElement | HTMLTextAreaElement | null {
  const nodes = Array.from(
    document.body.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input, textarea"),
  );
  return nodes.find((node) => (node.getAttribute("aria-label") || "").includes(label)) ?? null;
}

describe("TeamSettingsDialog", () => {
  let host: HTMLDivElement | null = null;
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
    }
    host?.remove();
    host = null;
    root = null;
    document.body.innerHTML = "";
  });

  it("renders basics, editable member rows, and room section for an editable team", () => {
    const team = makeTeam({
      linkedChatRoom: {
        roomId: "room-1",
        title: "Alpha Team 团队群聊",
        status: "idle",
        mode: "round_robin",
        purpose: "discussion",
        participantCount: 1,
        updatedAt: "2026-10-06T00:00:00Z",
      },
      members: [
        {
          memberId: "member-1",
          agentId: "agent-1",
          agentCode: "A1",
          agentName: "Alpha",
          role: "lead",
          purpose: "协调全队",
          responsibilities: ["收集证据", "汇总结论"],
          agentStatus: "active",
          model: { dialogueModelId: "", configured: false },
        },
      ],
    });
    ({ host, root } = renderDialog(
      <TeamSettingsDialog
        open
        lang="zh"
        team={team}
        agents={baseAgents}
        teams={[team]}
        agentsById={baseAgentsById}
        pending={false}
        createRoomPending={false}
        errorMessage=""
        onSubmit={vi.fn()}
        onCreateRoom={vi.fn()}
        onClose={vi.fn()}
      />,
    ));

    expect(document.body.querySelector("[role='dialog']") || document.body.textContent).toBeTruthy();
    expect(document.body.textContent).toContain("团队设置");
    expect(document.body.textContent).toContain("基本信息");
    expect(document.body.textContent).toContain("成员");
    expect(document.body.textContent).toContain("Alpha Team 团队群聊");
    expect(document.body.textContent).toContain("前往群聊");
    // Existing member fields come in as editable inputs pre-filled from the roster.
    const roleInput = inputByLabel("角色 · Alpha");
    expect(roleInput).toBeTruthy();
    expect((roleInput as HTMLInputElement).value).toBe("lead");
    const purposeInput = inputByLabel("职责目标 · Alpha");
    expect((purposeInput as HTMLTextAreaElement).value).toBe("协调全队");
    const responsibilitiesInput = inputByLabel("职责条目 · Alpha");
    expect((responsibilitiesInput as HTMLTextAreaElement).value).toBe("收集证据\n汇总结论");
    // Model summary chip: member.model says unconfigured.
    expect(document.body.textContent).toContain("未配模型");
    const configLink = buttonByText("配置模型");
    expect(configLink).toBeTruthy();
    // Save starts disabled (clean draft), cancel present.
    const save = buttonByText("保存修改");
    expect(save?.hasAttribute("disabled") || save?.getAttribute("aria-disabled") === "true").toBe(true);
    expect(buttonByText("取消")).toBeTruthy();
  });

  it("submits normalized member field edits through the members payload", () => {
    const onSubmit = vi.fn();
    const team = makeTeam();
    ({ host, root } = renderDialog(
      <TeamSettingsDialog
        open
        lang="zh"
        team={team}
        agents={baseAgents}
        teams={[team]}
        agentsById={baseAgentsById}
        pending={false}
        createRoomPending={false}
        errorMessage=""
        onSubmit={onSubmit}
        onCreateRoom={vi.fn()}
        onClose={vi.fn()}
      />,
    ));

    const roleInput = inputByLabel("角色 · Alpha") as HTMLInputElement;
    expect(roleInput).toBeTruthy();
    setInputValue(roleInput, "主负责");
    const responsibilitiesInput = inputByLabel("职责条目 · Alpha") as HTMLTextAreaElement;
    setInputValue(responsibilitiesInput, "收集证据\n\n  汇总结论 \n第三条");

    const save = buttonByText("保存修改");
    expect(save).toBeTruthy();
    click(save as HTMLElement);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [teamId, payload] = onSubmit.mock.calls[0];
    expect(teamId).toBe("team-a");
    expect(payload.members).toEqual([
      {
        memberId: "member-1",
        agentId: "agent-1",
        role: "主负责",
        purpose: "",
        responsibilities: ["收集证据", "汇总结论", "第三条"],
      },
    ]);
  });

  it("caps member responsibilities at 8 lines before submit", () => {
    const onSubmit = vi.fn();
    const team = makeTeam();
    ({ host, root } = renderDialog(
      <TeamSettingsDialog
        open
        lang="zh"
        team={team}
        agents={baseAgents}
        teams={[team]}
        agentsById={baseAgentsById}
        pending={false}
        createRoomPending={false}
        errorMessage=""
        onSubmit={onSubmit}
        onCreateRoom={vi.fn()}
        onClose={vi.fn()}
      />,
    ));

    const responsibilitiesInput = inputByLabel("职责条目 · Alpha") as HTMLTextAreaElement;
    setInputValue(
      responsibilitiesInput,
      Array.from({ length: 10 }, (_unused, index) => `条目${index + 1}`).join("\n"),
    );

    click(buttonByText("保存修改") as HTMLElement);
    const [, payload] = onSubmit.mock.calls[0];
    expect(payload.members[0].responsibilities).toHaveLength(8);
    expect(payload.members[0].responsibilities[7]).toBe("条目8");
  });

  it("marks a member for unbind and submits the members payload on save", () => {
    const onSubmit = vi.fn();
    const team = makeTeam();
    ({ host, root } = renderDialog(
      <TeamSettingsDialog
        open
        lang="zh"
        team={team}
        agents={baseAgents}
        teams={[team]}
        agentsById={baseAgentsById}
        pending={false}
        createRoomPending={false}
        errorMessage=""
        onSubmit={onSubmit}
        onCreateRoom={vi.fn()}
        onClose={vi.fn()}
      />,
    ));

    const unbind = document.body.querySelector("button[aria-label='解绑成员']");
    expect(unbind).toBeTruthy();
    click(unbind as HTMLElement);

    const save = buttonByText("保存修改");
    expect(save).toBeTruthy();
    click(save as HTMLElement);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [teamId, payload] = onSubmit.mock.calls[0];
    expect(teamId).toBe("team-a");
    expect(payload.members).toEqual([]);
  });

  it("offers the create-room entry when no room is linked", () => {
    const onCreateRoom = vi.fn();
    const team = makeTeam({ linkedChatRoom: null });
    ({ host, root } = renderDialog(
      <TeamSettingsDialog
        open
        lang="zh"
        team={team}
        agents={baseAgents}
        teams={[team]}
        agentsById={baseAgentsById}
        pending={false}
        createRoomPending={false}
        errorMessage=""
        onSubmit={vi.fn()}
        onCreateRoom={onCreateRoom}
        onClose={vi.fn()}
      />,
    ));

    expect(document.body.textContent).toContain("尚未绑定群聊房间");
    const create = buttonByText("创建群聊房间");
    expect(create).toBeTruthy();
    click(create as HTMLElement);
    expect(onCreateRoom).toHaveBeenCalledWith("team-a");
  });

  it("archives through the danger zone confirm when the host wires it", () => {
    const onArchive = vi.fn();
    const team = makeTeam();
    ({ host, root } = renderDialog(
      <TeamSettingsDialog
        open
        lang="zh"
        team={team}
        agents={baseAgents}
        teams={[team]}
        agentsById={baseAgentsById}
        pending={false}
        createRoomPending={false}
        errorMessage=""
        onSubmit={vi.fn()}
        onCreateRoom={vi.fn()}
        archivePending={false}
        onArchive={onArchive}
        onClose={vi.fn()}
      />,
    ));

    expect(document.body.textContent).toContain("危险操作");
    const archive = buttonByText("归档当前团队");
    expect(archive).toBeTruthy();
    click(archive as HTMLElement);

    const confirm = buttonByText("确认归档");
    expect(confirm).toBeTruthy();
    click(confirm as HTMLElement);
    expect(onArchive).toHaveBeenCalledWith("team-a");
  });

  it("locks system teams: read-only notice, disabled inputs, no save, no danger zone", () => {
    const onSubmit = vi.fn();
    const onArchive = vi.fn();
    const team = makeTeam({
      teamId: "research-team",
      teamKind: "research",
      teamSource: "research_organization",
    });
    ({ host, root } = renderDialog(
      <TeamSettingsDialog
        open
        lang="zh"
        team={team}
        agents={baseAgents}
        teams={[team]}
        agentsById={baseAgentsById}
        pending={false}
        createRoomPending={false}
        errorMessage=""
        onSubmit={onSubmit}
        onCreateRoom={vi.fn()}
        archivePending={false}
        onArchive={onArchive}
        onClose={vi.fn()}
      />,
    ));

    expect(document.body.textContent).toContain("只读");
    const nameInput = document.body.querySelector("input");
    expect(nameInput?.disabled).toBe(true);
    expect(buttonByText("保存修改")).toBeNull();
    expect(document.body.querySelector("button[aria-label='解绑成员']")).toBeNull();
    expect(document.body.textContent).not.toContain("添加成员");
    expect(document.body.textContent).not.toContain("危险操作");
    expect(buttonByText("归档当前团队")).toBeNull();
  });

  it("renders nothing when closed or without a team", () => {
    ({ host, root } = renderDialog(
      <TeamSettingsDialog
        open={false}
        lang="zh"
        team={makeTeam()}
        agents={baseAgents}
        teams={[]}
        agentsById={baseAgentsById}
        pending={false}
        createRoomPending={false}
        errorMessage=""
        onSubmit={vi.fn()}
        onCreateRoom={vi.fn()}
        onClose={vi.fn()}
      />,
    ));
    expect(document.body.querySelector("[role='dialog']")).toBeNull();
  });
});

describe("TeamSettingsDialog wiring contract", () => {
  it("uses VUI-only surface and keeps mutations out of the dialog", () => {
    expect(dialogSource).toContain("<VDialog");
    expect(dialogSource).toContain("VButton");
    expect(dialogSource).toContain("VNativeInput");
    expect(dialogSource).toContain("VSelect");
    expect(dialogSource).toContain("VConfirmDialog");
    expect(dialogSource).toContain('from "../../components/vui"');
    expect(dialogSource).not.toMatch(/<button[\s>]/);
    expect(dialogSource).not.toContain("renderers/shadcn");
    expect(dialogSource).not.toContain("@heroui/react");
    expect(dialogSource).not.toContain("useMutation");
    expect(dialogSource).not.toMatch(/['"`]\/api\//);
  });

  it("toolbar mounts the settings dialog through the actions hook", () => {
    expect(toolbarSource).toContain("TeamSettingsDialog");
    expect(toolbarSource).toContain("useTeamSettingsActions");
    expect(toolbarSource).toContain("archivePending={settings.archivePending}");
    expect(toolbarSource).toContain("onArchive={(teamId) => settings.archive(teamId)}");
    expect(actionsSource).toContain("updateTeam(");
    expect(actionsSource).toContain("syncTeamChatRoom(");
    expect(actionsSource).toContain("archiveTeam(");
    expect(actionsSource).toContain("startUserAction(\"team_settings_update\"");
    expect(actionsSource).toContain("startUserAction(\"team_settings_archive\"");
    expect(actionsSource).toContain("afterTeamChanged");
    expect(actionsSource).toContain("afterTeamArchived");
  });

  it("keeps updateTeam( exclusive to the team settings actions hook", () => {
    // vitest may run from the repo root or from web/; locate web/src either way.
    const candidates = [join(process.cwd(), "web", "src"), join(process.cwd(), "src")];
    const srcRoot = candidates.find((candidate) => existsSync(join(candidate, "api", "teams.ts")));
    expect(srcRoot, "web/src directory").toBeTruthy();
    const allowed = new Set(["api/teams.ts", "routes/teams/useTeamSettingsActions.ts"]);
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir)) {
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) {
          walk(full);
          continue;
        }
        if (!/\.(ts|tsx)$/.test(entry) || entry.endsWith(".test.ts") || entry.endsWith(".test.tsx")) {
          continue;
        }
        const relative = full.slice(srcRoot!.length + 1).replace(/\\/g, "/");
        if (allowed.has(relative)) {
          continue;
        }
        const source = readFileSync(full, "utf-8");
        if (/(^|[^.\w])updateTeam\(/.test(source)) {
          offenders.push(relative);
        }
      }
    };
    walk(srcRoot!);
    expect(offenders).toEqual([]);
  });

  it("shell frame forwards the settings action into the shared toolbar (board + canvas)", () => {
    expect(frameSource).toContain("settingsAction");
  });

  it("treats workflow-managed system teams and archived teams as read-only", () => {
    expect(isReadOnlyTeam(makeTeam({ teamId: "research-team", teamKind: "research" }))).toBe(true);
    expect(isReadOnlyTeam(makeTeam({ teamId: "self-evolution-team" }))).toBe(true);
    expect(isReadOnlyTeam(makeTeam({ teamKind: "ai_search" }))).toBe(true);
    expect(isReadOnlyTeam(makeTeam({ status: "archived" }))).toBe(true);
    expect(isReadOnlyTeam(makeTeam({ teamKind: "custom" }))).toBe(false);
    expect(isReadOnlyTeam(makeTeam({ teamKind: "template_demo" }))).toBe(false);
    expect(teamSettingsCopy("zh").lockedNotice).toContain("只读");
    expect(teamSettingsCopy("zh").archiveAction).toContain("归档");
    expect(teamSettingsCopy("en").dangerHeading).toBe("Danger zone");
  });
});
