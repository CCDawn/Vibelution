import { useState } from "react";
import { Users } from "lucide-react";

import {
  TeamCandidateCard,
  TeamStageCard,
  TeamStageCommandBar,
  TeamStagePipeline,
} from "../../../components/vui/product/team-management";
import { VButton } from "../../../components/vui";
import type { AgentConfigWorkspaceAgent, Team } from "../../../api/types";
import teamsRouteStyles from "../../../routes/TeamsRoute.styles";
import { TeamSettingsDialog } from "../../../routes/teams/TeamSettingsDialog";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";

// Preview-only demonstrator for the documented TeamCanvasNodeCard pattern.
// The product pattern is rendered inline by TeamOrganizationCanvasSurface and
// intentionally not exported; styles stay centralized in TeamsRoute.styles.
function TeamCanvasNodeCard({
  label,
  functionLabel,
  agentLine,
  purpose,
}: {
  label: string;
  functionLabel: string;
  agentLine: string;
  purpose?: string;
}) {
  return (
    <div className={teamsRouteStyles.node}>
      <span className={teamsRouteStyles.nodeIcon}>
        <Users size={15} />
      </span>
      <strong>{label}</strong>
      <span className={`${teamsRouteStyles.nodeRoleBadge} ${teamsRouteStyles.nodeRoleBadgeResearch}`}>{functionLabel}</span>
      <small>{agentLine}</small>
      {purpose ? <small className={teamsRouteStyles.nodePurpose}>{purpose}</small> : null}
    </div>
  );
}

export function TeamCatalog() {
  return (
    <VuiPreviewSection title="Team">
      <VuiPreviewCard name="TeamStageCommandBar" className="col-span-full min-h-0">
        <div className="w-full">
          <TeamStageCommandBar
            title="知识采集"
            subtitle="资料确认后进入实验设计"
            tone="active"
            stats={[{ key: "evidence", label: "已核验", value: "42", emphasis: "accent" }]}
            steps={[
              { id: "collect", indexLabel: "01", title: "知识采集", tone: "active", selected: true, status: "当前" },
              { id: "design", indexLabel: "02", title: "实验设计", tone: "idle", status: "待开始" },
              { id: "iterate", indexLabel: "03", title: "执行迭代", tone: "idle", status: "待开始" },
            ]}
          />
        </div>
      </VuiPreviewCard>
      <VuiPreviewCard name="TeamStagePipeline" className="col-span-full min-h-0">
        <div className="w-full">
          <TeamStagePipeline>
            <TeamStageCard index={0} label="知识采集" status="当前" metric="42 / 48" nextLabel="完成交接" tone="active" onActivate={() => undefined} />
            <TeamStageCard index={1} label="实验设计" status="待开始" metric="—" nextLabel="等待前序阶段" tone="idle" onActivate={() => undefined} />
            <TeamStageCard index={2} label="执行迭代" status="待开始" metric="—" nextLabel="等待前序阶段" tone="idle" onActivate={() => undefined} />
          </TeamStagePipeline>
        </div>
      </VuiPreviewCard>
      <VuiPreviewCard name="TeamCandidateCard" className="col-span-2 min-h-0">
        <div className="w-full max-w-md">
          <TeamCandidateCard
            title="Isolation Forest 基线"
            statusLabel="候选"
            tone="ready"
            summary="实验记录 · 质量 0.81"
            meta={[{ key: "agent", label: "实验 Agent" }]}
            source={{ label: "来源", value: "RUN-002", title: "运行 RUN-002", href: "https://example.test/runs/2" }}
            actions={<VButton variant="primary">采纳</VButton>}
          />
        </div>
      </VuiPreviewCard>
      <VuiPreviewCard name="TeamCanvasNodeCard" className="col-span-2 min-h-0">
        <div className="w-full" style={{ position: "relative", minHeight: 120 }}>
          <TeamCanvasNodeCard
            label="科研负责人"
            functionLabel="研究"
            agentLine="科研 Agent · 林"
            purpose="假设治理与评审收口"
          />
        </div>
      </VuiPreviewCard>
      <VuiPreviewCard name="TeamSettingsDialog" className="col-span-2 min-h-0">
        <TeamSettingsDialogPreview />
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}

const previewSettingsTeam = {
  teamId: "preview-team",
  name: "示例团队",
  description: "统一团队配置面预览数据",
  purpose: "一处配齐基本信息、成员、群聊与模型状态",
  status: "active",
  teamKind: "custom",
  teamCategory: "自定义团队",
  teamSource: "manual",
  members: [
    {
      memberId: "member-1",
      agentId: "preview-agent-1",
      agentCode: "PA1",
      agentName: "示例 Agent 甲",
      role: "lead",
      purpose: "",
      agentStatus: "active",
      model: { dialogueModelId: "preview-provider/model-a", configured: true },
    },
    {
      memberId: "member-2",
      agentId: "preview-agent-2",
      agentCode: "PA2",
      agentName: "示例 Agent 乙",
      role: "reviewer",
      purpose: "",
      agentStatus: "active",
      model: { dialogueModelId: "", configured: false },
    },
  ],
  memberCount: 2,
  updatedAt: "2026-10-06T00:00:00Z",
  linkedChatRoom: {
    roomId: "preview-room",
    title: "示例团队群聊",
    status: "idle",
    mode: "round_robin",
    purpose: "discussion",
    participantCount: 2,
    updatedAt: "2026-10-06T00:00:00Z",
  },
} as unknown as Team;

const previewSettingsAgents = [
  { agentId: "preview-agent-1", agentCode: "PA1", displayName: "示例 Agent 甲", status: "active", llmBindings: {} },
  { agentId: "preview-agent-2", agentCode: "PA2", displayName: "示例 Agent 乙", status: "active", llmBindings: {} },
  { agentId: "preview-agent-3", agentCode: "PA3", displayName: "示例 Agent 丙", status: "active", llmBindings: {} },
] as unknown as AgentConfigWorkspaceAgent[];

function TeamSettingsDialogPreview() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <VButton variant="secondary" onPress={() => setOpen(true)}>打开团队设置</VButton>
      <TeamSettingsDialog
        open={open}
        lang="zh"
        team={previewSettingsTeam}
        agents={previewSettingsAgents}
        teams={[previewSettingsTeam]}
        agentsById={new Map(previewSettingsAgents.map((agent) => [agent.agentId, agent]))}
        pending={false}
        createRoomPending={false}
        errorMessage=""
        onSubmit={() => undefined}
        onCreateRoom={() => undefined}
        onClose={() => setOpen(false)}
      />
    </>
  );
}
