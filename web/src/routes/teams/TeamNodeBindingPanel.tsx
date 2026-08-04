import { Link2, Save, Trash2, Unlink } from "lucide-react";
import { Link } from "react-router-dom";

import type { AgentConfigWorkspaceAgent, Team, TeamCanvasNode, TeamOrganizationCanvas } from "../../api/types";
import { VNativeButton, VNativeInput, VNativeTextarea, VStringSelect, VTooltip } from "../../components/vui";

export type TeamNodeBindingDraft = {
  label: string;
  role: string;
  purpose: string;
  agentId: string;
};

export type TeamNodeBindingPanelProps = {
  lang: "zh" | "en";
  selectedTeam: Team | null;
  selectedNode: TeamCanvasNode | null;
  nodeDraft: TeamNodeBindingDraft;
  onNodeDraftChange: (patch: Partial<TeamNodeBindingDraft>) => void;
  activeAgents: AgentConfigWorkspaceAgent[];
  agentTeamMembership: Map<string, { teamId: string; teamName: string }>;
  agentDisplayName: (agent: AgentConfigWorkspaceAgent) => string;
  agentSourceRoute: (node: TeamCanvasNode) => string;
  durableCanvas: TeamOrganizationCanvas | null;
  hasWritableCanvas: boolean;
  savePending: boolean;
  detailPending: boolean;
  agentsPending: boolean;
  validationIssues: Array<{ code: string; message: string; nodeId?: string; edgeId?: string }>;
  onSave: () => void;
  onConnectFromLead: () => void;
  onUnbind: () => void;
  onDelete: () => void;
  styles: {
    section: string;
    placeholder: string;
    empty: string;
    sourceAuthority: string;
    actionRow: string;
    dangerButton: string;
    issueList: string;
    issue: string;
  };
};

/**
 * Writable node binding inspector for organization canvas.
 */
export function TeamNodeBindingPanel({
  lang,
  selectedTeam,
  selectedNode,
  nodeDraft,
  onNodeDraftChange,
  activeAgents,
  agentTeamMembership,
  agentDisplayName,
  agentSourceRoute,
  durableCanvas,
  hasWritableCanvas,
  savePending,
  detailPending,
  agentsPending,
  validationIssues,
  onSave,
  onConnectFromLead,
  onUnbind,
  onDelete,
  styles: s,
}: TeamNodeBindingPanelProps) {
  if (!selectedTeam) {
    return (
      <section className={`${s.section} ${s.placeholder}`}>
        <div className={s.empty}>
          {lang === "zh"
            ? "暂无可用团队。请确认 AI 搜索范围团队和 挑战杯ai科研团队 已初始化。"
            : "No available team. Confirm the AI search scope team and Challenge Cup AI research team are initialized."}
        </div>
      </section>
    );
  }

  if (!selectedNode) {
    return (
      <section className={`${s.section} ${s.placeholder}`} aria-busy={detailPending || agentsPending}>
        <div className={s.empty}>
          {detailPending || agentsPending
            ? (lang === "zh" ? "正在读取团队节点..." : "Loading team nodes...")
            : (lang === "zh" ? "创建或选择一个团队节点。" : "Create or select a team node.")}
        </div>
      </section>
    );
  }

  const leadId = durableCanvas?.nodes[0]?.id;

  return (
    <section className={s.section} data-testid="team-node-binding-panel">
      {selectedNode.agentId ? (
        <div className={s.sourceAuthority}>
          <div>
            <strong>{lang === "zh" ? "Agent 身份只读投影" : "Read-only Agent identity"}</strong>
            <span>
              {selectedNode.agentSourceRef?.owner || "AgentDirectory"}
              {" · "}
              {selectedNode.agentCode || selectedNode.agentName || selectedNode.agentId}
            </span>
          </div>
          <VTooltip content={lang === "zh" ? "到 AgentDirectory 源配置修改" : "Edit in the AgentDirectory source"}>
            <Link to={agentSourceRoute(selectedNode)}>
              <Link2 size={14} />
              {lang === "zh" ? "源配置" : "Source"}
            </Link>
          </VTooltip>
        </div>
      ) : null}
      <label>
        <span>{lang === "zh" ? "节点名称" : "Node label"}</span>
        <VNativeInput
          value={nodeDraft.label}
          onChange={(event) => onNodeDraftChange({ label: event.target.value })}
        />
      </label>
      <label>
        <span>{lang === "zh" ? "组织角色" : "Role"}</span>
        <VNativeInput
          value={nodeDraft.role}
          onChange={(event) => onNodeDraftChange({ role: event.target.value })}
        />
      </label>
      <label>
        <span>{lang === "zh" ? "绑定 Agent" : "Bound Agent"}</span>
        <VStringSelect
          ariaLabel={lang === "zh" ? "绑定 Agent" : "Bind agent"}
          value={nodeDraft.agentId}
          onValueChange={(agentId) => onNodeDraftChange({ agentId })}
          options={[
            { value: "", label: lang === "zh" ? "不绑定" : "Unbound" },
            ...activeAgents.map((agent) => {
              const membership = agentTeamMembership.get(agent.agentId);
              const ownedByOtherTeam = Boolean(membership && membership.teamId !== selectedTeam.teamId);
              return {
                value: agent.agentId,
                disabled: ownedByOtherTeam,
                label:
                  `${agentDisplayName(agent)} · ${agent.agentCode}`
                  + (ownedByOtherTeam
                    ? ` · ${lang === "zh" ? "已属于" : "belongs to"} ${membership?.teamName}`
                    : ""),
              };
            }),
          ]}
        />
      </label>
      <label>
        <span>{lang === "zh" ? "目的" : "Purpose"}</span>
        <VNativeTextarea
          value={nodeDraft.purpose}
          onChange={(event) => onNodeDraftChange({ purpose: event.target.value })}
        />
      </label>
      <div className={s.actionRow}>
        <VNativeButton type="button" onClick={onSave} disabled={!hasWritableCanvas || savePending}>
          <Save size={14} />
          {lang === "zh" ? "保存节点" : "Save node"}
        </VNativeButton>
        <VNativeButton
          type="button"
          onClick={onConnectFromLead}
          disabled={!hasWritableCanvas || !selectedNode || leadId === selectedNode.id}
        >
          <Link2 size={14} />
          {lang === "zh" ? "接入主干" : "Connect"}
        </VNativeButton>
        <VNativeButton
          type="button"
          onClick={onUnbind}
          disabled={!hasWritableCanvas || !selectedNode.agentId || savePending}
        >
          <Unlink size={14} />
          {lang === "zh" ? "解绑节点" : "Unbind"}
        </VNativeButton>
        <VNativeButton
          type="button"
          className={s.dangerButton}
          onClick={onDelete}
          disabled={!hasWritableCanvas || !selectedNode || (durableCanvas?.nodes.length ?? 0) <= 1 || savePending}
        >
          <Trash2 size={14} />
          {lang === "zh" ? "删除节点" : "Delete"}
        </VNativeButton>
      </div>
      <div className={s.issueList}>
        {validationIssues.length ? (
          validationIssues.map((issue) => (
            <div key={`${issue.code}-${issue.nodeId}-${issue.edgeId}`} className={s.issue}>
              <strong>{issue.code}</strong>
              <span>{issue.message}</span>
            </div>
          ))
        ) : (
          <span>{lang === "zh" ? "画布校验通过" : "Canvas validation passed"}</span>
        )}
      </div>
    </section>
  );
}
