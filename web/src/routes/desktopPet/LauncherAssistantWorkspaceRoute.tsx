import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { getLauncherBranchInstances, isLauncherProjectNotSelected, selectLauncherProject } from "../../api/launcher";
import { getLauncherAssistantDetail, getLauncherAssistantDispatches, getLauncherAssistantStatus } from "../../api/launcherAssistant";
import { launcherAssistantComputer } from "../../api/launcherAssistantComputer";
import { createLauncherAssistantPanelTransport } from "../../api/launcherAssistantPanels";
import { queryKeys } from "../../api/queryKeys";
import { launcherAssistantPanelLabel, resolveLauncherAssistantPanel, type LauncherAssistantPanel } from "../../app/launcherNavigationModel";
import { VButton, VDenseOpsPage, VStateSurface, VSurface } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import { PersonalAssistantAffairs } from "../personalAssistant/PersonalAssistantAffairs";
import { PersonalAssistantComputerPanel } from "../personalAssistant/PersonalAssistantComputerPanel";
import { PersonalAssistantDialoguePreferences } from "../personalAssistant/PersonalAssistantDialoguePreferences";
import { PersonalAssistantSettings } from "../personalAssistant/PersonalAssistantSettings";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";
import { launcherDispatchLabel, launcherDispatchReceiptLabel } from "./launcherAssistantModel";
import styles from "./LauncherAssistantWorkspaceRoute.styles";

const copy = {
  zh: { loading: "正在读取个人助理…", failed: "个人助理暂不可用", retry: "重试", boundary: "当前助理与已连接项目",
    boundaryHint: "这里显示当前助理的原生会话、派遣回执，以及已连接项目的分支与实例。",
    assistant: "当前助理", messages: "会话消息", dispatches: "派遣回执", branches: "项目分支与实例条目",
    noProject: "尚未选择项目", noProjectHint: "选择项目后可以查看其分支和实例。", selectProject: "选择项目",
    projectFailed: "项目状态暂不可用", selectFailed: "无法连接项目，请重试。", detailFailed: "会话暂不可用",
    dispatchFailed: "派遣回执暂不可用", emptyDispatch: "暂无派遣回执", approval: "回到对话处理授权", unnamed: "未指定项目" },
  en: { loading: "Loading the assistant…", failed: "Assistant unavailable", retry: "Retry", boundary: "Current assistant and connected project",
    boundaryHint: "Shows the assistant's native session and dispatch receipts, plus branches and instances of the connected project.",
    assistant: "Current assistant", messages: "Session messages", dispatches: "Dispatch receipts", branches: "Project branch and instance entries",
    noProject: "No project selected", noProjectHint: "Select a project to see its branches and instances.", selectProject: "Select project",
    projectFailed: "Project status unavailable", selectFailed: "Could not connect the project. Try again.", detailFailed: "Session unavailable",
    dispatchFailed: "Dispatch receipts unavailable", emptyDispatch: "No dispatch receipts yet", approval: "Return to conversation for approval", unnamed: "Project not specified" },
} as const;

export function LauncherAssistantWorkspaceRoute() {
  const [params, setParams] = useSearchParams();
  const panel = resolveLauncherAssistantPanel(params.toString());
  const { lang } = useShellI18n();
  const text = copy[lang];
  const client = useQueryClient();
  const [selectionError, setSelectionError] = useState("");
  const [selecting, setSelecting] = useState(false);
  const status = useQuery({ queryKey: ["launcher-assistant", "status"], queryFn: getLauncherAssistantStatus,
    enabled: panel !== "dialogue", retry: false });
  const agentId = status.data?.assistant.agentId ?? "";
  const sessionId = status.data?.assistant.directSessionId ?? "";
  const transport = useMemo(() => agentId ? createLauncherAssistantPanelTransport(agentId) : null, [agentId]);
  const detail = useQuery({ queryKey: ["launcher-assistant", "overview-detail", sessionId],
    queryFn: () => getLauncherAssistantDetail(sessionId), enabled: panel === "overview" && Boolean(sessionId), retry: false });
  const dispatches = useQuery({ queryKey: ["launcher-assistant", "workspace-dispatches"], queryFn: getLauncherAssistantDispatches,
    enabled: panel === "overview" || panel === "dispatches", retry: false, refetchInterval: 5000 });
  const projects = useQuery({ queryKey: queryKeys.launcherBranchInstances(), queryFn: () => getLauncherBranchInstances(),
    enabled: panel === "overview", retry: false });

  function go(next: LauncherAssistantPanel) {
    setParams(previous => { const updated = new URLSearchParams(previous); updated.set("panel", next); return updated; });
  }
  async function selectProject() {
    if (selecting) return;
    setSelecting(true); setSelectionError("");
    try {
      const result = await selectLauncherProject();
      if (result.connected) await client.invalidateQueries({ queryKey: ["launcher"] });
    } catch (error) { setSelectionError(error instanceof Error ? error.message : text.selectFailed); }
    finally { setSelecting(false); }
  }
  if (panel === "dialogue") return <LauncherAssistantRoute embedded navigationOwned />;
  const waiting = status.isPending;
  return <VDenseOpsPage className={styles.page} bodyClassName={styles.body} title={launcherAssistantPanelLabel(panel, lang)}>
    <div className={styles.content}>
      {waiting ? <VStateSurface tone="loading" title={text.loading} /> : status.isError
        ? <VStateSurface tone="error" title={text.failed} actions={<VButton onClick={() => void status.refetch()}>{text.retry}</VButton>}>
          {status.error instanceof Error ? status.error.message : ""}
        </VStateSurface> : null}
      {status.data && panel === "overview" ? <>
        <p className={styles.intro}>{text.boundary} · {text.boundaryHint}</p>
        <div className={styles.grid}>
          <VSurface className={styles.card}><h2 className={styles.cardTitle}>{text.assistant}</h2><p className={styles.value}>{status.data.assistant.displayName}</p></VSurface>
          <VSurface className={styles.card}><h2 className={styles.cardTitle}>{text.messages}</h2>
            {detail.isPending ? <p className={styles.muted}>{text.loading}</p> : detail.isError
              ? <VStateSurface tone="error" density="compact" title={text.detailFailed} actions={<VButton onClick={() => void detail.refetch()}>{text.retry}</VButton>} />
              : <p className={styles.value}>{detail.data.messages.length}</p>}</VSurface>
          <VSurface className={styles.card}><h2 className={styles.cardTitle}>{text.dispatches}</h2>
            {dispatches.isPending ? <p className={styles.muted}>{text.loading}</p> : dispatches.isError
              ? <VStateSurface tone="error" density="compact" title={text.dispatchFailed} actions={<VButton onClick={() => void dispatches.refetch()}>{text.retry}</VButton>} />
              : <p className={styles.value}>{dispatches.data.length}</p>}</VSurface>
          <VSurface className={styles.card}><h2 className={styles.cardTitle}>{text.branches}</h2>
            {projects.isPending ? <p className={styles.muted}>{text.loading}</p> : projects.isError
              ? isLauncherProjectNotSelected(projects.error) ? <VStateSurface tone="empty" density="compact" title={text.noProject}
                actions={<VButton isPending={selecting} onClick={() => void selectProject()}>{text.selectProject}</VButton>}>
                {text.noProjectHint}</VStateSurface> : <VStateSurface tone="error" density="compact" title={text.projectFailed}
                actions={<VButton onClick={() => void projects.refetch()}>{text.retry}</VButton>}>{projects.error instanceof Error ? projects.error.message : ""}</VStateSurface>
              : <p className={styles.value}>{projects.data.items.length}</p>}
            {selectionError ? <p role="alert" className={styles.muted}>{selectionError}</p> : null}</VSurface>
        </div>
      </> : null}
      {status.data && panel === "dispatches" ? dispatches.isPending ? <VStateSurface tone="loading" title={text.loading} />
        : dispatches.isError ? <VStateSurface tone="error" title={text.dispatchFailed} actions={<VButton onClick={() => void dispatches.refetch()}>{text.retry}</VButton>}>
          {dispatches.error instanceof Error ? dispatches.error.message : ""}</VStateSurface>
        : !dispatches.data.length ? <VStateSurface tone="empty" title={text.emptyDispatch} />
        : <div className={styles.list}>{dispatches.data.map(row => <VSurface key={row.dispatchId} className={styles.row}>
          <div className={styles.rowHead}><strong>{launcherDispatchReceiptLabel(row, lang)}</strong><span className={styles.muted}>{launcherDispatchLabel(row, lang)}</span></div>
          <span className={styles.identifier}>{row.projectId || text.unnamed} · {row.dispatchId}</span>
          {row.receipt?.resultSummary || row.lastError?.message ? <p className={styles.muted}>{row.receipt?.resultSummary || row.lastError?.message}</p> : null}
          {row.receipt?.pendingApprovals?.length ? <VButton variant="secondary" onClick={() => go("dialogue")}>{text.approval}</VButton> : null}
        </VSurface>)}</div> : null}
      {status.data && transport && panel === "affairs" ? <PersonalAssistantAffairs agentId={agentId} transport={{ cacheKey: transport.cacheKey, ...transport.affairs }} /> : null}
      {status.data && transport && panel === "preferences" ? <PersonalAssistantDialoguePreferences agentId={agentId} transport={{ cacheKey: transport.cacheKey, ...transport.preferences }} /> : null}
      {status.data && transport && panel === "assistant-settings" ? <PersonalAssistantSettings open onOpenChange={() => {}} presentation="page"
        transport={{ cacheKey: transport.cacheKey, invalidationKey: ["launcher-assistant"], ...transport.settings }} /> : null}
      {status.data && panel === "computer" ? <PersonalAssistantComputerPanel active transport={launcherAssistantComputer} onCollapse={() => go("dialogue")} /> : null}
    </div>
  </VDenseOpsPage>;
}

export default LauncherAssistantWorkspaceRoute;
