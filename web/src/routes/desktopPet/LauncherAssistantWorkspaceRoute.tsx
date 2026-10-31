import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { getLauncherAssistantStatus } from "../../api/launcherAssistant";
import { launcherAssistantComputer } from "../../api/launcherAssistantComputer";
import { createLauncherAssistantPanelTransport } from "../../api/launcherAssistantPanels";
import { launcherAssistantPanelLabel, resolveLauncherAssistantPanel, type LauncherAssistantPanel } from "../../app/launcherNavigationModel";
import { VButton, VDenseOpsPage, VStateSurface } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import { PersonalAssistantAffairs } from "../personalAssistant/PersonalAssistantAffairs";
import { PersonalAssistantComputerPanel } from "../personalAssistant/PersonalAssistantComputerPanel";
import { PersonalAssistantDialoguePreferences } from "../personalAssistant/PersonalAssistantDialoguePreferences";
import { PersonalAssistantSettings } from "../personalAssistant/PersonalAssistantSettings";
import { LauncherAssistantBrowserWorkspace } from "./LauncherAssistantBrowserWorkspace";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";
import styles from "./LauncherAssistantWorkspaceRoute.styles";

const copy = {
  zh: { loading: "正在读取个人助理…", failed: "个人助理暂不可用", retry: "重试" },
  en: { loading: "Loading the assistant…", failed: "Assistant unavailable", retry: "Retry" },
} as const;

export function LauncherAssistantWorkspaceRoute() {
  const [params, setParams] = useSearchParams();
  const panel = resolveLauncherAssistantPanel(params.toString());
  const { lang } = useShellI18n();
  const text = copy[lang];
  const status = useQuery({ queryKey: ["launcher-assistant", "status"], queryFn: getLauncherAssistantStatus,
    enabled: panel !== "dialogue" && panel !== "browser", retry: false });
  const agentId = status.data?.assistant.agentId ?? "";
  const transport = useMemo(() => agentId ? createLauncherAssistantPanelTransport(agentId) : null, [agentId]);

  function go(next: LauncherAssistantPanel) {
    setParams(previous => { const updated = new URLSearchParams(previous); updated.set("panel", next); return updated; });
  }
  if (panel === "dialogue") return <LauncherAssistantRoute embedded navigationOwned />;
  if (panel === "browser") return <LauncherAssistantBrowserWorkspace />;
  return <VDenseOpsPage className={styles.page} bodyClassName={styles.body} title={launcherAssistantPanelLabel(panel, lang)}>
    <div className={styles.content}>
      {status.isPending ? <VStateSurface tone="loading" title={text.loading} /> : status.isError
        ? <VStateSurface tone="error" title={text.failed} actions={<VButton onClick={() => void status.refetch()}>{text.retry}</VButton>}>
          {status.error instanceof Error ? status.error.message : ""}
        </VStateSurface> : null}
      {status.data && transport && panel === "affairs" ? <PersonalAssistantAffairs agentId={agentId} showHeading={false} transport={{ cacheKey: transport.cacheKey, ...transport.affairs }} /> : null}
      {status.data && transport && panel === "preferences" ? <PersonalAssistantDialoguePreferences agentId={agentId} transport={{ cacheKey: transport.cacheKey, ...transport.preferences }} /> : null}
      {status.data && transport && panel === "assistant-settings" ? <PersonalAssistantSettings open onOpenChange={() => {}} presentation="page"
        transport={{ cacheKey: transport.cacheKey, invalidationKey: ["launcher-assistant"], ...transport.settings }} /> : null}
      {status.data && panel === "computer" ? <PersonalAssistantComputerPanel active transport={launcherAssistantComputer} onCollapse={() => go("dialogue")} /> : null}
    </div>
  </VDenseOpsPage>;
}

export default LauncherAssistantWorkspaceRoute;
