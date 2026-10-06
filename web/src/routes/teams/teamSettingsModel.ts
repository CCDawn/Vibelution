/**
 * Pure model for the unified team settings surface (团队设置).
 * Members are the sole roster authority: edits produce a PATCH
 * `/api/teams/{id}` members payload; the canvas is only a projection.
 */
import type { AgentConfigWorkspaceAgent, AgentLlmBindings, Team, TeamMember } from "../../api/types";
import { researchStageAgentManagementRoute } from "./researchStageAgentPresentation";

export type TeamSettingsMemberDraft = {
  memberId: string;
  agentId: string;
  role: string;
  purpose: string;
  responsibilities: string[];
  /** Rebind target; "" keeps the current agentId. */
  nextAgentId: string;
  /** Marks the row for removal in the next members payload. */
  remove: boolean;
};

export type TeamSettingsDraft = {
  name: string;
  description: string;
  purpose: string;
  members: TeamSettingsMemberDraft[];
  addRole: string;
  addAgentId: string;
};

export type TeamSettingsPayload = {
  name?: string;
  description?: string;
  purpose?: string;
  members?: Array<{
    memberId: string;
    agentId: string;
    role: string;
    purpose: string;
    responsibilities?: string[];
  }>;
};

export type TeamSettingsAgentOption = {
  id: string;
  label: string;
  description?: string;
  /** Bound to another active team: selectable but rejected by the server. */
  disabled: boolean;
};

export type TeamMemberModelStatus = {
  configured: boolean;
  label: string;
  detail: string;
  configRoute: string;
};

const trimmed = (value: string) => String(value || "").trim();

export function createTeamSettingsDraft(team: Team | null | undefined): TeamSettingsDraft {
  return {
    name: team?.name ?? "",
    description: team?.description ?? "",
    purpose: team?.purpose ?? "",
    members: (team?.members ?? []).map((member) => ({
      memberId: member.memberId || "",
      agentId: member.agentId || "",
      role: member.role || "",
      purpose: member.purpose || "",
      responsibilities: [...(member.responsibilities ?? [])],
      nextAgentId: "",
      remove: false,
    })),
    addRole: "",
    addAgentId: "",
  };
}

export function teamSettingsDirty(draft: TeamSettingsDraft, team: Team | null | undefined): boolean {
  if (!team) {
    return false;
  }
  if (trimmed(draft.name) !== trimmed(team.name)) return true;
  if (draft.description.trim() !== (team.description || "")) return true;
  if (draft.purpose.trim() !== (team.purpose || "")) return true;
  if (draft.members.some((member) => member.remove || trimmed(member.nextAgentId))) return true;
  if (trimmed(draft.addAgentId)) return true;
  return false;
}

/**
 * Build the PATCH payload: basic fields only when changed; the members array
 * is a full-roster replacement (kept rows + rebinds, minus removed, plus the
 * pending add row).
 */
export function buildTeamSettingsPayload(
  draft: TeamSettingsDraft,
  team: Team | null | undefined,
): TeamSettingsPayload {
  const payload: TeamSettingsPayload = {};
  if (!team) {
    return payload;
  }
  const name = trimmed(draft.name);
  if (name !== trimmed(team.name) && name) {
    payload.name = name;
  }
  if (draft.description.trim() !== (team.description || "")) {
    payload.description = draft.description.trim();
  }
  if (draft.purpose.trim() !== (team.purpose || "")) {
    payload.purpose = draft.purpose.trim();
  }
  const membersChanged =
    draft.members.some((member) => member.remove || trimmed(member.nextAgentId)) || Boolean(trimmed(draft.addAgentId));
  if (membersChanged) {
    const members: NonNullable<TeamSettingsPayload["members"]> = [];
    for (const member of draft.members) {
      if (member.remove) {
        continue;
      }
      const agentId = trimmed(member.nextAgentId) || member.agentId;
      if (!agentId) {
        continue;
      }
      const row: NonNullable<TeamSettingsPayload["members"]>[number] = {
        memberId: member.memberId,
        agentId,
        role: member.role,
        purpose: member.purpose,
      };
      if (member.responsibilities.length) {
        row.responsibilities = [...member.responsibilities];
      }
      members.push(row);
    }
    const addAgentId = trimmed(draft.addAgentId);
    if (addAgentId) {
      members.push({
        memberId: "",
        agentId: addAgentId,
        role: trimmed(draft.addRole),
        purpose: "",
      });
    }
    payload.members = members;
  }
  return payload;
}

/** Agent options for rebind/add: active directory agents, minus agents bound to other active teams. */
export function teamSettingsAgentOptions({
  agents,
  teams,
  team,
}: {
  agents: AgentConfigWorkspaceAgent[];
  teams: Team[];
  team: Team | null | undefined;
}): TeamSettingsAgentOption[] {
  const teamId = team?.teamId || "";
  const occupiedByOtherTeam = new Set<string>();
  for (const candidate of teams) {
    if (!candidate || candidate.teamId === teamId) {
      continue;
    }
    if (String(candidate.status || "") === "archived") {
      continue;
    }
    for (const member of candidate.members ?? []) {
      if (member?.agentId) {
        occupiedByOtherTeam.add(member.agentId);
      }
    }
  }
  return (agents ?? [])
    .filter((agent) => {
      const agentId = trimmed(agent?.agentId || "");
      return agentId && String(agent?.status || "active") !== "archived";
    })
    .map((agent) => {
      const agentId = trimmed(agent.agentId || "");
      const name = trimmed(agent.displayName || "") || agentId;
      return {
        id: agentId,
        label: name,
        description: trimmed(agent.agentCode || "") || undefined,
        disabled: occupiedByOtherTeam.has(agentId),
      };
    })
    .sort((a, b) => a.label.localeCompare(b.label, "zh-Hans-CN"));
}

/**
 * Dialogue-model status for one member row. Prefers the backend team-detail
 * projection (`member.model`); falls back to the loaded agent directory.
 */
export function teamMemberModelStatus(
  member: TeamMember,
  agentsById: Map<string, AgentConfigWorkspaceAgent>,
  lang: "zh" | "en",
): TeamMemberModelStatus {
  const agentId = trimmed(member?.agentId || "");
  const agent = agentsById.get(agentId) ?? null;
  const fromDetail = member?.model;
  const bindings: AgentLlmBindings | undefined = agent?.llmBindings;
  const modelId = trimmed(fromDetail?.dialogueModelId || "")
    || trimmed(bindings?.dialogue?.modelId || "");
  const configured = fromDetail ? Boolean(fromDetail.configured) : Boolean(modelId);
  const configRoute = researchStageAgentManagementRoute(agentId);
  if (!agent && !fromDetail) {
    return {
      configured: false,
      label: lang === "zh" ? "未在目录中" : "Missing agent",
      detail: lang === "zh" ? "该成员的 Agent 不在当前目录中。" : "This member's Agent is not in the directory.",
      configRoute,
    };
  }
  return {
    configured,
    label: configured
      ? lang === "zh"
        ? "已配模型"
        : "Model ready"
      : lang === "zh"
        ? "未配模型"
        : "No model",
    detail: configured
      ? modelId || (lang === "zh" ? "已配置对话模型。" : "Dialogue model configured.")
      : lang === "zh"
        ? "尚未为该成员的 Agent 配置对话模型。"
        : "This member's Agent has no dialogue model configured.",
    configRoute,
  };
}

export type TeamSettingsCopy = {
  title: string;
  description: string;
  basicsHeading: string;
  nameLabel: string;
  descriptionLabel: string;
  purposeLabel: string;
  membersHeading: string;
  membersHint: string;
  memberRoleFallback: string;
  rebindLabel: string;
  unbindLabel: string;
  addHeading: string;
  addRolePlaceholder: string;
  addAgentPlaceholder: string;
  addAction: string;
  roomHeading: string;
  roomNone: string;
  roomCreate: string;
  roomCreating: string;
  roomOpen: string;
  roomParticipants: (count: number) => string;
  modelConfigHint: string;
  lockedNotice: string;
  save: string;
  saving: string;
  cancel: string;
  emptyMembers: string;
};

export function teamSettingsCopy(lang: "zh" | "en"): TeamSettingsCopy {
  if (lang === "en") {
    return {
      title: "Team settings",
      description: "Basics, members, chat room, and model status in one place.",
      basicsHeading: "Basics",
      nameLabel: "Name",
      descriptionLabel: "Description",
      purposeLabel: "Purpose",
      membersHeading: "Members",
      membersHint: "Members are the roster authority; the canvas follows automatically.",
      memberRoleFallback: "Unnamed role",
      rebindLabel: "Change agent",
      unbindLabel: "Unbind member",
      addHeading: "Add member",
      addRolePlaceholder: "Role (optional)",
      addAgentPlaceholder: "Select agent",
      addAction: "Add",
      roomHeading: "Team chat room",
      roomNone: "No chat room linked yet.",
      roomCreate: "Create chat room",
      roomCreating: "Creating…",
      roomOpen: "Open in Chat",
      roomParticipants: (count) => `${count} participant${count === 1 ? "" : "s"}`,
      modelConfigHint: "Configure model",
      lockedNotice: "System and archived teams are read-only here; workflows maintain them.",
      save: "Save changes",
      saving: "Saving…",
      cancel: "Cancel",
      emptyMembers: "No members yet — add the first member below.",
    };
  }
  return {
    title: "团队设置",
    description: "基本信息、成员、群聊与模型状态，一处配齐。",
    basicsHeading: "基本信息",
    nameLabel: "名称",
    descriptionLabel: "描述",
    purposeLabel: "用途",
    membersHeading: "成员",
    membersHint: "成员名单是权威数据，画布会自动跟随投影。",
    memberRoleFallback: "未命名角色",
    rebindLabel: "换绑 Agent",
    unbindLabel: "解绑成员",
    addHeading: "添加成员",
    addRolePlaceholder: "角色（可选）",
    addAgentPlaceholder: "选择 Agent",
    addAction: "添加",
    roomHeading: "团队群聊",
    roomNone: "尚未绑定群聊房间。",
    roomCreate: "创建群聊房间",
    roomCreating: "正在创建…",
    roomOpen: "前往群聊",
    roomParticipants: (count) => `${count} 名参与者`,
    modelConfigHint: "配置模型",
    lockedNotice: "系统团队与归档团队在这里只读，由工作流自动维护。",
    save: "保存修改",
    saving: "保存中…",
    cancel: "取消",
    emptyMembers: "还没有成员，在下方添加第一位成员。",
  };
}
