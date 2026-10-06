/**
 * Unified team settings dialog (团队设置): basics + member management (rebind /
 * add / unbind without touching the canvas) + linked chat room state + per
 * member model status. VUI-only surface; mutations live in
 * useTeamSettingsActions (injected via props) and copy is an inline zh/en
 * table. Members are the roster authority — this surface never writes canvas
 * or Agent config.
 */
import { UserMinus, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { AgentConfigWorkspaceAgent, Team } from "../../api/types";
import { VButton, VDialog, VNativeInput, VSelect, VStatusChip, VTextarea } from "../../components/vui";
import { teamChatRoomRoute } from "./researchStageAgentPresentation";
import {
  buildTeamSettingsPayload,
  createTeamSettingsDraft,
  teamMemberModelStatus,
  teamSettingsAgentOptions,
  teamSettingsCopy,
  teamSettingsDirty,
  type TeamSettingsAgentOption,
  type TeamSettingsPayload,
} from "./teamSettingsModel";
import styles from "./TeamSettingsDialog.styles";

export type TeamSettingsDialogProps = {
  open: boolean;
  lang: "zh" | "en";
  team: Team | null;
  /** Active agent directory (agents.json projection) for rebind/add options. */
  agents: AgentConfigWorkspaceAgent[];
  /** Full visible team list, used to mark agents already bound elsewhere. */
  teams: Team[];
  agentsById: Map<string, AgentConfigWorkspaceAgent>;
  pending: boolean;
  createRoomPending: boolean;
  errorMessage: string;
  onSubmit: (teamId: string, payload: TeamSettingsPayload) => void;
  onCreateRoom: (teamId: string) => void;
  onClose: () => void;
};

export function TeamSettingsDialog({
  open,
  lang,
  team,
  agents,
  teams,
  agentsById,
  pending,
  createRoomPending,
  errorMessage,
  onSubmit,
  onCreateRoom,
  onClose,
}: TeamSettingsDialogProps) {
  const copy = useMemo(() => teamSettingsCopy(lang), [lang]);
  const navigate = useNavigate();
  const [draft, setDraft] = useState(() => createTeamSettingsDraft(team));
  const teamId = team?.teamId || "";
  const teamUpdatedAt = team?.updatedAt || "";

  useEffect(() => {
    if (!open) {
      return;
    }
    setDraft(createTeamSettingsDraft(team));
    // Reset on open / team switch / post-save refresh; background refetches
    // with the same updatedAt must not wipe in-progress edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, teamId, teamUpdatedAt]);

  const locked = !team || isReadOnlyTeam(team);
  const dirty = teamSettingsDirty(draft, team);
  const canSave = Boolean(team) && !locked && dirty && !pending;
  const agentOptions = useMemo(
    () => teamSettingsAgentOptions({ agents, teams, team }),
    [agents, teams, team],
  );

  if (!open || !team) {
    return null;
  }

  const room = team.linkedChatRoom ?? null;
  const roomRoute = room?.roomId ? teamChatRoomRoute(room.roomId, `/teams?teamId=${encodeURIComponent(team.teamId)}`, "teams") : "";

  const patchMember = (memberId: string, patch: Partial<{ nextAgentId: string; remove: boolean }>) => {
    setDraft((current) => ({
      ...current,
      members: current.members.map((member) => (member.memberId === memberId ? { ...member, ...patch } : member)),
    }));
  };

  const addMemberRow = () => {
    if (!draft.addAgentId) {
      return;
    }
    setDraft((current) => ({ ...current, addAgentId: "" }));
  };

  return (
    <VDialog
      open={open}
      onOpenChange={(nextOpen: boolean) => {
        if (!nextOpen && !pending) {
          onClose();
        }
      }}
      title={copy.title}
      description={copy.description}
      size="xl"
      aria-label={copy.title}
      hideClose={pending}
    >
      <div className={styles.content}>
        {locked ? <p className={styles.lockedNotice}>{copy.lockedNotice}</p> : null}

        <section className={styles.section} aria-label={copy.basicsHeading}>
          <h4 className={styles.sectionHeading}>{copy.basicsHeading}</h4>
          <div className={styles.fieldGrid}>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>{copy.nameLabel}</span>
              <VNativeInput
                value={draft.name}
                maxLength={160}
                disabled={locked || pending}
                onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>{copy.descriptionLabel}</span>
              <VTextarea
                value={draft.description}
                rows={2}
                isDisabled={locked || pending}
                onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>{copy.purposeLabel}</span>
              <VTextarea
                value={draft.purpose}
                rows={2}
                isDisabled={locked || pending}
                onChange={(event) => setDraft((current) => ({ ...current, purpose: event.target.value }))}
              />
            </label>
          </div>
        </section>

        <section className={styles.section} aria-label={copy.membersHeading}>
          <h4 className={styles.sectionHeading}>{copy.membersHeading}</h4>
          <p className={styles.sectionHint}>{copy.membersHint}</p>
          <div className={styles.memberList}>
            {draft.members.length === 0 ? <p className={styles.sectionHint}>{copy.emptyMembers}</p> : null}
            {draft.members.map((member) => {
              const memberRef = team.members.find((item) => item.memberId === member.memberId);
              const modelStatus = teamMemberModelStatus(
                memberRef ?? ({ agentId: member.agentId } as Team["members"][number]),
                agentsById,
                lang,
              );
              return (
                <div
                  key={member.memberId || member.agentId}
                  className={[styles.memberRow, member.remove ? styles.memberRowMarkedRemove : ""].filter(Boolean).join(" ")}
                >
                  <div className={styles.memberMeta}>
                    <span className={styles.memberRole}>{member.role || copy.memberRoleFallback}</span>
                    {modelStatus.configured ? (
                      <VStatusChip className={styles.modelChip} tone="success">
                        {modelStatus.label}
                      </VStatusChip>
                    ) : (
                      <VStatusChip className={styles.modelChip} tone="warning">
                        {modelStatus.label}
                      </VStatusChip>
                    )}
                  </div>
                  <div className={styles.memberActions}>
                    <VSelect
                      className={styles.rebindSelect}
                      density="compact"
                      aria-label={`${copy.rebindLabel} · ${member.role || member.agentId}`}
                      placeholder={copy.addAgentPlaceholder}
                      isDisabled={locked || pending}
                      selectedKey={member.nextAgentId || member.agentId || null}
                      options={[
                        ...(member.agentId
                          ? agentOptions.some((option) => option.id === member.agentId)
                            ? []
                            : [{
                                id: member.agentId,
                                label: memberRef?.agentName || member.agentId,
                                disabled: false,
                              }]
                          : []),
                        ...agentOptions,
                      ]}
                      onSelectionChange={(key) => {
                        if (key == null) return;
                        const nextAgentId = String(key);
                        patchMember(member.memberId, { nextAgentId: nextAgentId === member.agentId ? "" : nextAgentId });
                      }}
                    />
                    {!modelStatus.configured ? (
                      <VButton
                        type="button"
                        variant="ghost"
                        density="compact"
                        className={styles.modelLink}
                        isDisabled={pending}
                        onClick={() => navigate(modelStatus.configRoute)}
                      >
                        {copy.modelConfigHint}
                      </VButton>
                    ) : null}
                    {!locked ? (
                      <VButton
                        type="button"
                        variant="ghost"
                        density="compact"
                        isIconOnly
                        className={styles.iconAction}
                        aria-label={copy.unbindLabel}
                        title={copy.unbindLabel}
                        isDisabled={pending}
                        icon={<UserMinus size={14} aria-hidden="true" />}
                        onClick={() => patchMember(member.memberId, { remove: !member.remove, nextAgentId: "" })}
                      />
                    ) : null}
                  </div>
                </div>
              );
            })}
            {!locked ? (
              <div className={styles.addRow}>
                <VNativeInput
                  className={styles.addRoleInput}
                  value={draft.addRole}
                  maxLength={96}
                  disabled={pending}
                  placeholder={copy.addRolePlaceholder}
                  onChange={(event) => setDraft((current) => ({ ...current, addRole: event.target.value }))}
                />
                <VSelect
                  className={styles.addAgentSelect}
                  density="compact"
                  aria-label={copy.addHeading}
                  placeholder={copy.addAgentPlaceholder}
                  isDisabled={pending}
                  selectedKey={draft.addAgentId || null}
                  options={agentOptions.filter((option) => !draft.members.some((member) => !member.remove && (member.nextAgentId || member.agentId) === option.id))}
                  onSelectionChange={(key) => {
                    setDraft((current) => ({ ...current, addAgentId: key == null ? "" : String(key) }));
                  }}
                />
                <VButton
                  type="button"
                  variant="secondary"
                  density="compact"
                  icon={<Users size={14} aria-hidden="true" />}
                  isDisabled={!draft.addAgentId || pending}
                  onClick={addMemberRow}
                >
                  {copy.addAction}
                </VButton>
              </div>
            ) : null}
          </div>
        </section>

        <section className={styles.section} aria-label={copy.roomHeading}>
          <h4 className={styles.sectionHeading}>{copy.roomHeading}</h4>
          {room ? (
            <div className={styles.roomRow}>
              <span className={styles.roomTitle}>{room.title || room.roomId}</span>
              <span className={styles.roomMeta}>
                {[
                  room.mode,
                  copy.roomParticipants(room.participantCount ?? 0),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              {roomRoute ? (
                <VButton
                  type="button"
                  variant="secondary"
                  density="compact"
                  onClick={() => navigate(roomRoute)}
                >
                  {copy.roomOpen}
                </VButton>
              ) : null}
            </div>
          ) : (
            <div className={styles.roomRow}>
              <span className={styles.roomMeta}>{copy.roomNone}</span>
              <VButton
                type="button"
                variant="secondary"
                density="compact"
                isDisabled={locked || createRoomPending}
                isPending={createRoomPending}
                onClick={() => onCreateRoom(team.teamId)}
              >
                {createRoomPending ? copy.roomCreating : copy.roomCreate}
              </VButton>
            </div>
          )}
        </section>

        {errorMessage ? <p className={styles.error}>{errorMessage}</p> : null}

        <div className={styles.actions}>
          <VButton type="button" variant="secondary" isDisabled={pending} onPress={onClose}>
            {copy.cancel}
          </VButton>
          {!locked ? (
            <VButton
              type="button"
              variant="primary"
              isDisabled={!canSave}
              isPending={pending}
              onPress={() => onSubmit(team.teamId, buildTeamSettingsPayload(draft, team))}
            >
              {pending ? copy.saving : copy.save}
            </VButton>
          ) : null}
        </div>
      </div>
    </VDialog>
  );
}

/** Mirrors the backend guard: archived and workflow-managed system teams reject PATCH edits. */
export function isReadOnlyTeam(team: Team): boolean {
  return (
    team.status === "archived"
    || team.teamId === "research-team"
    || team.teamId === "knowledge-expansion-team"
    || team.teamId === "ai-search-team"
    || team.teamId === "self-evolution-team"
    || team.teamId === "supervised-evolution-team"
    || team.teamKind === "research"
    || team.teamKind === "knowledge_expansion"
    || team.teamKind === "ai_search"
    || team.teamKind === "self_evolution"
    || team.teamKind === "supervised_evolution"
    || team.teamSource === "research_organization"
    || team.teamSource === "knowledge_expansion"
    || team.teamSource === "ai_search"
    || team.teamSource === "self_evolution"
    || team.teamSource === "supervised_evolution"
  );
}
