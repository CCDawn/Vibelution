/**
 * R2-b: Teams shell surface flags + copy (gate / loading / unavailable).
 * Pure model — Workbench only wires query state and consumes the bag.
 */
export type TeamsShellSurfaceLang = "zh" | "en";

export type TeamsShellSurfaceModelInput = {
  lang: TeamsShellSurfaceLang;
  hasTeams: boolean;
  teamsPending: boolean;
  teamsError: boolean;
  teamsData: unknown;
  teamsErrorMessage: string;
  effectiveTeamId: string;
  selectedTeamReference: { name: string } | null | undefined;
  selectedTeam: { name?: string } | null | undefined;
  selectedTeamDetailLoading: boolean;
  selectedTeamDetailUnavailableBase: boolean;
  researchWorkflowTeamSelected: boolean;
  researchCanvasVisible: boolean;
  researchCanvasReadOnly: boolean;
  teamDetailErrorMessage: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  styles: Record<string, string>;
};

export function buildTeamsShellSurfaceModel(input: TeamsShellSurfaceModelInput) {
  const {
    lang,
    hasTeams,
    teamsPending,
    teamsError,
    teamsData,
    teamsErrorMessage,
    effectiveTeamId,
    selectedTeamReference,
    selectedTeam,
    selectedTeamDetailLoading,
    selectedTeamDetailUnavailableBase,
    researchWorkflowTeamSelected,
    researchCanvasVisible,
    researchCanvasReadOnly,
    teamDetailErrorMessage,
    styles,
  } = input;

  const teamListInitialLoading = teamsPending && !teamsData;
  const teamListUnavailable = teamsError && !teamsData;
  const showTeamInitialLoadingSurface = teamListInitialLoading;
  const showTeamUnavailableSurface = !teamListInitialLoading && !hasTeams;
  const selectedTeamDetailUnavailable = Boolean(selectedTeamDetailUnavailableBase);
  const researchTeamDetailDegraded = Boolean(
    researchWorkflowTeamSelected && (selectedTeamDetailLoading || selectedTeamDetailUnavailable),
  );
  const showTeamLoadingSurface =
    !showTeamInitialLoadingSurface && !showTeamUnavailableSurface && selectedTeamDetailLoading && !researchWorkflowTeamSelected;
  const showTeamDetailUnavailableSurface =
    !showTeamInitialLoadingSurface && !showTeamUnavailableSurface && selectedTeamDetailUnavailable && !researchWorkflowTeamSelected;

  const teamUnavailableTitle = teamListUnavailable
    ? (lang === "zh" ? "团队数据不可用" : "Team data unavailable")
    : (lang === "zh" ? "团队尚未初始化" : "Teams are not initialized");
  const teamUnavailableMessage = teamListUnavailable
    ? (lang === "zh"
      ? "当前前端没有拿到团队列表。请刷新团队数据，或通过 Launcher 恢复后端 API。"
      : "The frontend cannot read the team list. Refresh teams or restore the backend API from Launcher.")
    : (lang === "zh"
      ? "暂时没有可展示团队。请确认 AI 搜索范围团队、知识库扩充团队和挑战杯ai科研团队已初始化。"
      : "No visible teams are available. Confirm the AI search, knowledge expansion, and research teams are initialized.");
  const teamUnavailableDetail = teamsErrorMessage;
  const teamWorkspaceLoadingTitle = lang === "zh" ? "正在读取团队详情" : "Loading team details";
  const teamWorkspaceLoadingMessage = selectedTeamReference
    ? (lang === "zh"
      ? `正在补齐 ${selectedTeamReference.name} 的完整详情；当前先保留工作台结构和可用画布。`
      : `Completing details for ${selectedTeamReference.name}; the workspace shell and available canvas stay visible.`)
    : (lang === "zh"
      ? "正在补齐团队详情；当前先保留工作台结构和可用画布。"
      : "Completing team details; the workspace shell and available canvas stay visible.");
  const teamWorkspaceUnavailableTitle = lang === "zh" ? "团队详情不可用" : "Team details unavailable";
  const teamWorkspaceUnavailableMessage = selectedTeamReference
    ? (lang === "zh"
      ? `${selectedTeamReference.name} 已出现在团队列表里，但详情接口没有返回完整工作区数据。请刷新团队，或通过 Launcher 恢复后端 API。`
      : `${selectedTeamReference.name} is present in the team list, but the detail API did not return the complete workspace data. Refresh teams or restore the backend API from Launcher.`)
    : (lang === "zh"
      ? "团队详情接口没有返回完整工作区数据。请刷新团队，或通过 Launcher 恢复后端 API。"
      : "The team detail API did not return the complete workspace data. Refresh teams or restore the backend API from Launcher.");
  const teamWorkspaceUnavailableDetail = teamDetailErrorMessage;
  const teamContextMeta = selectedTeam?.name
    ?? (teamListInitialLoading
      ? (lang === "zh" ? "正在读取团队" : "Loading teams")
      : (lang === "zh" ? "暂无团队" : "No team"));
  const teamSummaryUnavailableText = lang === "zh" ? "不可用" : "unavailable";

  // Class tokens retained for layout contract stability (composers own live layout).
  const workspaceClassName = [
    styles.workspace,
    styles.teamShellWorkspace,
    researchCanvasVisible ? styles.teamShellWorkspaceCanvas : styles.teamShellWorkspaceBoard,
  ].filter(Boolean).join(" ");
  const canvasPanelClassName = [
    styles.canvasPanel,
    !researchCanvasVisible ? styles.researchCanvasPanelHidden : "",
    researchCanvasVisible ? "min-h-0 flex-1" : "",
  ].filter(Boolean).join(" ");
  const inspectorClassName = [
    styles.inspector,
    researchWorkflowTeamSelected ? styles.researchInspector : "",
    !researchCanvasVisible
      ? "flex h-full min-h-0 w-full max-w-none flex-1 flex-col overflow-hidden border-0 !bg-transparent"
      : "min-h-0 shrink-0",
  ].filter(Boolean).join(" ");
  const showNodeBindingPanel = researchCanvasVisible && !researchCanvasReadOnly;

  return {
    teamListInitialLoading,
    teamListUnavailable,
    showTeamInitialLoadingSurface,
    showTeamUnavailableSurface,
    selectedTeamDetailUnavailable,
    researchTeamDetailDegraded,
    showTeamLoadingSurface,
    showTeamDetailUnavailableSurface,
    teamUnavailableTitle,
    teamUnavailableMessage,
    teamUnavailableDetail,
    teamWorkspaceLoadingTitle,
    teamWorkspaceLoadingMessage,
    teamWorkspaceUnavailableTitle,
    teamWorkspaceUnavailableMessage,
    teamWorkspaceUnavailableDetail,
    teamContextMeta,
    teamSummaryUnavailableText,
    workspaceClassName,
    canvasPanelClassName,
    inspectorClassName,
    showNodeBindingPanel,
    effectiveTeamId,
  };
}
