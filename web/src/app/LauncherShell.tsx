import { useMutationState, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import {
  getLauncherBranchInstances,
  getLauncherFreshness,
  getLauncherState,
  hasLauncherStateBridge,
  onLauncherStateChanged,
} from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { useLauncherLanguage } from "../i18n/useLauncherLanguage";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "./browserTelemetry";
import { applyWorkbenchDocumentLanguage } from "./documentLanguage";
import { currentInstanceWindowTitle } from "./instanceWindowTitle";
import { LauncherTitlebar } from "./LauncherTitlebar";
import { LauncherNotificationProvider } from "./LauncherNotifications";
import { LauncherNavigation } from "./LauncherNavigation";
import {LauncherAssistantTaskCards} from "../routes/desktopPet/assistantTasks/LauncherAssistantTaskCards";
import {LauncherTaskNavigationSlot} from "../routes/desktopPet/assistantTasks/LauncherTaskNavigationSlot";
import { LauncherApprovalTargetContext, type LauncherApprovalTarget } from "../routes/desktopPet/launcherAssistantApprovalTarget";
import { VDialog, VSplitWorkspace, VWorkbenchFrame } from "../components/vui";
import { isElectronDesktopShell } from "./projectCloseGuard";
import styles from "./LauncherShell.styles";
import { applyWorkbenchDocumentTheme, readStoredWorkbenchTheme, subscribeStoredWorkbenchTheme } from "./themePreference";
import { applyUiFontBasePx, readStoredUiFontBasePx } from "./uiFontPreference";
import { isLauncherUpdateAvailable, LAUNCHER_UPDATE_MUTATION_KEY } from "./updateBanner";
import { UPDATE_FRESHNESS_INTERVAL_MS, UPDATE_FRESHNESS_QUERY_OPTIONS, useUpdateFreshnessFocus } from "./updateFreshness";

export function LauncherShell() {
  const routeContent = useMemo(() => <Outlet />, []);
  const lang = useLauncherLanguage();
  const [theme, setTheme] = useState(() => readStoredWorkbenchTheme());
  const [navigationOpen,setNavigationOpen] = useState(false);
  const [approvalTarget, setApprovalTarget] = useState<LauncherApprovalTarget | null>(null);
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const previousPath = useRef(location.pathname);
  useEffect(() => {
    if (previousPath.current.replace(/\/+$/, "").endsWith("/assistant")
      && !location.pathname.replace(/\/+$/, "").endsWith("/assistant")) setApprovalTarget(null);
    previousPath.current = location.pathname;
  }, [location.pathname]);
  const approvalNavigation = useMemo(() => ({ target: approvalTarget, dismiss: (nonce: string) => {
    setApprovalTarget(current => current?.nonce === nonce ? null : current);
  } }), [approvalTarget]);
  const watchUpdates = !location.pathname.replace(/\/+$/, "").endsWith("/updates");
  useUpdateFreshnessFocus(queryClient, watchUpdates);
  const freshnessQuery = useQuery({ ...UPDATE_FRESHNESS_QUERY_OPTIONS, queryKey:queryKeys.launcherFreshness(), queryFn:getLauncherFreshness,
    enabled:watchUpdates, refetchInterval:watchUpdates ? UPDATE_FRESHNESS_INTERVAL_MS : false, refetchOnWindowFocus:watchUpdates ? "always" : false, retry:false });
  const updateAvailable = isLauncherUpdateAvailable(freshnessQuery.data);
  const updateAttempts = useMutationState({ filters: { mutationKey: LAUNCHER_UPDATE_MUTATION_KEY }, select: (mutation) => mutation.state });
  const updateFailed = Boolean(freshnessQuery.data?.refreshError || updateAttempts.at(-1)?.status === "error");
  const stateBridgeAvailable = hasLauncherStateBridge();
  const desktopShell = isElectronDesktopShell();
  const branchInstancesQuery = useQuery({
    queryKey: queryKeys.launcherBranchInstances(),
    queryFn: () => getLauncherBranchInstances(),
    staleTime: 15_000,
  });
  const launcherWindowTitle = currentInstanceWindowTitle("launcher", branchInstancesQuery.data);

  useEffect(() => {
    const bridge = window.vibelutionLauncherBrowser;
    if (typeof bridge?.onShow !== "function") return;
    return bridge.onShow(() => { setNavigationOpen(false); void navigate("/launcher/assistant?panel=browser"); });
  }, [navigate]);

  useEffect(() => {
    const unsubscribe = subscribeStoredWorkbenchTheme(setTheme);
    setTheme(readStoredWorkbenchTheme());
    return unsubscribe;
  }, []);

  useEffect(() => {
    if (!stateBridgeAvailable) {
      return;
    }

    const invalidateBranchInstances = () => {
      void queryClient.invalidateQueries({ queryKey: ["launcher", "branch-instances"] });
    };
    const unsubscribe = onLauncherStateChanged(() => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      invalidateBranchInstances();
    });

    // Read once after subscribing so a state event emitted during initial mount
    // still causes the shared branch-instance query to refresh.
    void Promise.resolve()
      .then(() => getLauncherState())
      .then(invalidateBranchInstances, () => undefined);

    return unsubscribe;
  }, [queryClient, stateBridgeAvailable]);

  useEffect(() => {
    applyWorkbenchDocumentLanguage(document, lang);
    applyWorkbenchDocumentTheme(document, theme);
    // Same apply point as the theme: the launcher control surface follows the
    // workbench font-base preference too (read-only; no subscription needed).
    applyUiFontBasePx(document, readStoredUiFontBasePx());
    document.title = launcherWindowTitle;
  }, [lang, theme, launcherWindowTitle]);

  useEffect(() => {
    postBrowserTelemetry({
      phase: "page",
      eventCode: "browser.page.snapshot",
      message: "Launcher control surface snapshot.",
      fields: {
        ...collectBrowserPageSnapshot(),
        reason: "launcher_shell_mounted",
      },
    });
  }, []);

  return (<LauncherNotificationProvider><LauncherApprovalTargetContext.Provider value={approvalNavigation}>
   <LauncherAssistantTaskCards lang={lang} routePath={location.pathname} onApproval={(_task, target) => setApprovalTarget(target)} onOpenConversation={()=>{setNavigationOpen(false);void navigate("/launcher/assistant");}}>
    <div
      className={styles.root}
      data-theme={theme}
      data-vui-app="launcher"
      data-shell="launcher"
      data-desktop-shell={desktopShell ? "electron" : "browser"}
      data-browser-role="launcher_control_surface"
    >
      <LauncherTitlebar lang={lang} desktop={desktopShell} onOpenNavigation={() => setNavigationOpen(true)} />
      <VWorkbenchFrame>
        <VSplitWorkspace
          chrome="workbench"
          className={styles.workspace}
          columnsClassName={styles.columns}
          sidebar={<div className={styles.navigation}><LauncherNavigation lang={lang} items={branchInstancesQuery.data?.items ?? []} updateAvailable={updateAvailable} updateFailed={updateFailed} taskContent={<LauncherTaskNavigationSlot lang={lang}/>}/></div>}
          main={routeContent}
        />
      </VWorkbenchFrame>
      <VDialog open={navigationOpen} onOpenChange={setNavigationOpen} title={lang === "zh" ? "功能导航" : "Navigation"} size="sm">
        <div className={styles.mobileNavigation}><LauncherNavigation lang={lang} items={branchInstancesQuery.data?.items ?? []} onNavigate={() => setNavigationOpen(false)} updateAvailable={updateAvailable} updateFailed={updateFailed} taskContent={<LauncherTaskNavigationSlot lang={lang} onNavigate={()=>setNavigationOpen(false)}/>}/></div>
      </VDialog>
    </div>
   </LauncherAssistantTaskCards></LauncherApprovalTargetContext.Provider></LauncherNotificationProvider>
  );
}
