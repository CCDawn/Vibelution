import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

import type { AgentConfigWorkspaceAgent, Team } from "../../api/types";
import { VButton, VStringSelect } from "../../components/vui";
import {
  buildTeamSettingsPayload,
  createTeamSettingsDraft,
  isReadOnlyTeam,
  teamSettingsAgentOptions,
  teamSettingsCopy,
} from "./teamSettingsModel";
import { useTeamSettingsActions } from "./useTeamSettingsActions";
import styles from "./TeamMemberOperations.styles";

export type TeamMemberOperationsProps = {
  lang: "zh" | "en";
  team: Team;
  memberId: string;
  agents: AgentConfigWorkspaceAgent[];
  teams: Team[];
  agentsById: ReadonlyMap<string, AgentConfigWorkspaceAgent>;
  /** A positive revision opens the inline editor, including recovery requests. */
  configureRevision?: number;
  onSyncRoom: () => void;
  onSaved?: (team: Team, memberId: string) => void;
  renderWorkspace?: (operations: ReactNode) => ReactNode;
  syncPending: boolean;
  syncDisabledReason?: string;
  syncError?: string;
};

/** Single-member binding editor. The existing settings hook remains the roster writer. */
export function TeamMemberOperations({
  lang, team, memberId, agents, teams, agentsById, configureRevision = 0,
  onSyncRoom, onSaved, renderWorkspace, syncPending, syncDisabledReason, syncError,
}: TeamMemberOperationsProps) {
  const member = team.members.find((item) => item.memberId === memberId);
  const [open, setOpen] = useState(configureRevision > 0);
  const [agentId, setAgentId] = useState(member?.agentId || "");
  const submittedMember = useRef(memberId);
  const actions = useTeamSettingsActions({ onSaved: (savedTeam) => {
    if (submittedMember.current === memberId) setOpen(false);
    onSaved?.(savedTeam, submittedMember.current);
  } });
  const controlId = useId();
  const zh = lang === "zh";
  const locked = isReadOnlyTeam(team);
  const busy = actions.pending || syncPending;
  const options = useMemo(() => teamSettingsAgentOptions({ agents, teams, team }), [agents, teams, team]);
  const selectedOption = options.find((option) => option.id === agentId);
  const stale = member?.agentStatus === "stale";
  const canApply = Boolean(member && !locked && !busy && selectedOption && !selectedOption.disabled
    && (agentId !== member.agentId || stale));

  useEffect(() => {
    setAgentId(member?.agentId || "");
  }, [memberId, member?.agentId]);
  useEffect(() => { setOpen(configureRevision > 0); }, [memberId]);

  useEffect(() => {
    if (configureRevision > 0) setOpen(true);
  }, [configureRevision]);

  const apply = () => {
    if (!canApply || !member) return;
    // Build from the latest roster, so background updates to siblings survive.
    const draft = createTeamSettingsDraft(team);
    draft.members = draft.members.map((row) => row.memberId === memberId ? { ...row, nextAgentId: agentId } : row);
    submittedMember.current = memberId;
    actions.submit(team.teamId, buildTeamSettingsPayload(draft, team));
  };

  const name = member
    ? agentsById.get(member.agentId)?.displayName || member.agentName || member.agentCode || member.role || member.agentId
    : zh ? "未选择成员" : "No member selected";

  const operations = (
    <section className={styles.panel} aria-labelledby={`${controlId}-heading`} data-team-member-operations={memberId}>
      <h3 id={`${controlId}-heading`} className={styles.heading}>
        {zh ? "人物操作" : "Member actions"}<span className={styles.name}>{name}</span>
      </h3>
      {member ? <>
        {locked ? <p className={styles.hint}>{teamSettingsCopy(lang).lockedNotice}</p> : null}
        <VButton type="button" variant="secondary" className={styles.action} isDisabled={locked || busy}
          aria-expanded={open} aria-controls={`${controlId}-binding`} onClick={() => {
            if (locked || busy) return;
            if (!open) actions.reset();
            setOpen((value) => !value);
          }}>
          {zh ? "配置成员" : "Configure member"}
        </VButton>
        {open ? <div id={`${controlId}-binding`} className={styles.fields}>
          {stale ? <p className={styles.hint}>{zh ? "当前成员配置不可用，请重新绑定可用 Agent。" : "Member configuration is unavailable. Rebind an available Agent."}</p> : null}
          <label className={styles.field} htmlFor={`${controlId}-agent`}>
            {zh ? "绑定 Agent" : "Agent binding"}
            <VStringSelect id={`${controlId}-agent`} ariaLabel={zh ? "选择成员 Agent" : "Select member Agent"}
              className={styles.select} value={agentId} isDisabled={locked || busy}
              placeholder={!selectedOption ? (name || (zh ? "选择 Agent" : "Select Agent"))
                : selectedOption.disabled ? `${selectedOption.label}${zh ? " · 已绑定其他团队" : " · Bound to another team"}` : undefined}
              options={options.map((option) => ({
                value: option.id,
                label: `${option.label}${option.disabled ? (zh ? " · 已绑定其他团队" : " · Bound to another team") : ""}`,
                disabled: option.disabled,
              }))}
              onValueChange={(nextAgentId) => { actions.reset(); setAgentId(nextAgentId); }}
            />
          </label>
          <VButton type="button" className={styles.action} isDisabled={!canApply} isPending={actions.pending} onClick={apply}>
            {zh ? "应用配置" : "Apply configuration"}
          </VButton>
        </div> : null}
        {submittedMember.current === memberId && actions.errorMessage ? <p className={styles.error} role="alert">{actions.errorMessage}</p> : null}
        <VButton type="button" variant="secondary" className={styles.action}
          isPending={syncPending} isDisabled={busy || Boolean(syncDisabledReason)}
          aria-describedby={syncDisabledReason ? `${controlId}-sync-reason` : undefined}
          onClick={() => { if (!busy && !syncDisabledReason) onSyncRoom(); }}>
          {zh ? "同步会话" : "Sync session"}
        </VButton>
        {syncDisabledReason ? <p id={`${controlId}-sync-reason`} className={styles.hint}>{syncDisabledReason}</p> : null}
        {syncError ? <p className={styles.error} role="alert">{syncError}</p> : null}
      </> : null}
    </section>
  );
  return renderWorkspace ? renderWorkspace(operations) : operations;
}
