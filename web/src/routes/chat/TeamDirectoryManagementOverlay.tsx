import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { fetchAgentConfigWorkspace } from "../../api/agents";
import { queryKeys } from "../../api/queryKeys";
import { fetchTeam } from "../../api/teams";
import type { Team, TeamListPayload } from "../../api/types";
import { VButton, VConfirmDialog, VDialog, VNativeInput } from "../../components/vui";
import { isReadOnlyTeam, TeamSettingsDialog } from "../teams/TeamSettingsDialog";
import { useTeamSettingsActions } from "../teams/useTeamSettingsActions";
import type { TeamDirectoryAction } from "./useTeamDirectoryManagement";
import styles from "./TeamDirectoryManagementOverlay.styles";

type Props = { action: TeamDirectoryAction; team: Team | null; teams: Team[]; lang: "zh" | "en"; onClose: () => void };

/** Lazy dialog host. Only opening management loads full roster/config data. */
export function TeamDirectoryManagementOverlay({ action, team, teams, lang, onClose }: Props) {
  const zh = lang === "zh";
  const [name, setName] = useState(team?.name || "");
  const nameId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const submitted = useRef(false);
  const queryClient = useQueryClient();
  const updateRail = (updated: Team) => queryClient.setQueryData<TeamListPayload>(queryKeys.teams(), (current) =>
    current ? { ...current, teams: current.teams.map((item) => item.teamId === updated.teamId ? updated : item) } : current);
  const settings = useTeamSettingsActions({
    onSaved: (updated) => { updateRail(updated); if (action.mode === "rename") onClose(); },
    onArchived: (updated) => { updateRail(updated); onClose(); },
  });
  const pending = settings.pending || settings.archivePending || settings.createRoomPending;
  useEffect(() => { if (!pending) submitted.current = false; }, [pending]);
  useEffect(() => {
    if (action.mode !== "rename") return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [action.mode, action.teamId]);

  const detail = useQuery({
    queryKey: queryKeys.team(action.teamId, "full"),
    queryFn: ({ signal }) => fetchTeam(action.teamId, { signal, detail: "full" }),
    enabled: action.mode === "settings",
  });
  const workspace = useQuery({
    queryKey: queryKeys.agentConfigWorkspace(),
    queryFn: ({ signal }) => fetchAgentConfigWorkspace({ signal, includeRuntime: false }),
    enabled: action.mode === "settings",
  });
  const agents = workspace.data?.agents ?? [];
  const agentsById = useMemo(() => new Map(agents.map((agent) => [agent.agentId, agent])), [agents]);
  const locked = !team || isReadOnlyTeam(team);
  const close = () => { if (!pending && !submitted.current) onClose(); };
  const submitOnce = (submit: () => void) => {
    if (pending || submitted.current) return;
    submitted.current = true;
    submit();
  };
  const error = settings.errorMessage ? <p role="alert" className={styles.error}>{settings.errorMessage}</p> : null;

  if (action.mode === "settings") {
    if (!detail.data || !workspace.data) {
      const loadError = detail.error || workspace.error;
      return <VDialog open title={zh ? "管理团队" : "Manage team"} size="sm" onOpenChange={(open) => { if (!open) close(); }}>
        {loadError ? <>
          <p role="alert">{loadError instanceof Error ? loadError.message : String(loadError)}</p>
          <VButton variant="secondary" onPress={() => { void detail.refetch(); void workspace.refetch(); }}>{zh ? "重试" : "Retry"}</VButton>
        </> : <p role="status">{zh ? "正在载入团队设置…" : "Loading team settings…"}</p>}
      </VDialog>;
    }
    return <TeamSettingsDialog open team={detail.data} teams={teams} agents={agents} agentsById={agentsById} lang={lang}
      pending={settings.pending} createRoomPending={settings.createRoomPending} errorMessage={settings.errorMessage}
      onSubmit={(teamId, payload) => submitOnce(() => settings.submit(teamId, payload))}
      onCreateRoom={(teamId) => submitOnce(() => settings.createRoom(teamId))}
      archivePending={settings.archivePending} onArchive={(teamId) => submitOnce(() => settings.archive(teamId))}
      onClose={close} />;
  }
  if (action.mode === "archive") {
    return <VConfirmDialog open title={zh ? "归档团队" : "Archive team"} tone="danger"
      description={zh ? `确定归档“${team?.name || action.teamId}”？团队将变为只读，关联群聊房间会被删除。若只想收起左栏，请取消并选择“隐藏团队”。`
        : `Archive “${team?.name || action.teamId}”? The team becomes read-only and linked chat rooms are deleted. To keep records, cancel and choose Hide team.`}
      confirmLabel={zh ? "确认归档" : "Confirm archive"} cancelLabel={zh ? "保留团队" : "Keep team"}
      confirmPending={pending} confirmDisabled={locked} onConfirm={() => { if (!locked) submitOnce(() => settings.archive(action.teamId)); }}
      onOpenChange={(open) => { if (!open) close(); }}>{error}</VConfirmDialog>;
  }
  const canSave = !locked && Boolean(name.trim()) && name.trim() !== team?.name && !pending;
  const rename = () => { if (canSave) submitOnce(() => settings.submit(action.teamId, { name: name.trim() })); };
  return <VDialog open title={zh ? "重命名团队" : "Rename team"} size="sm"
    description={zh ? "修改团队显示名称，成员和历史记录保持不变。" : "Change the team display name; keep members and history."}
    onOpenChange={(open) => { if (!open) close(); }} hideClose={pending}
    footer={<>
      <VButton variant="secondary" isDisabled={pending} onPress={close}>{zh ? "取消" : "Cancel"}</VButton>
      <VButton variant="primary" isDisabled={!canSave} isPending={pending} onPress={rename}>{zh ? "保存" : "Save"}</VButton>
    </>}>
    <label htmlFor={nameId} className={styles.accessibleLabel}>{zh ? "团队名称" : "Team name"}</label>
    <VNativeInput ref={inputRef} id={nameId} value={name} maxLength={160} disabled={locked || pending}
      autoComplete="off" onChange={(event) => setName(event.target.value)}
      onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); rename(); } }} />
    {error}
  </VDialog>;
}
