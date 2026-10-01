import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";

import {
  getLauncherBranchInstances,
  getLauncherState,
  hasLauncherStateBridge,
  onLauncherStateChanged,
} from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import { useShellI18n } from "../i18n/useShellI18n";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "./browserTelemetry";
import { applyWorkbenchDocumentLanguage } from "./documentLanguage";
import { currentInstanceWindowTitle } from "./instanceWindowTitle";
import { LauncherUpdateTopbar } from "./LauncherUpdateTopbar";
import { LauncherNavigation } from "./LauncherNavigation";
import { VSplitWorkspace } from "../components/vui";
import styles from "./LauncherShell.styles";
import { applyWorkbenchDocumentTheme, readStoredWorkbenchTheme } from "./themePreference";
import { applyUiFontBasePx, readStoredUiFontBasePx } from "./uiFontPreference";

export function LauncherShell() {
  const { lang } = useShellI18n({ configEnabled: false });
  const [theme] = useState(() => readStoredWorkbenchTheme());
  const queryClient = useQueryClient();
  const stateBridgeAvailable = hasLauncherStateBridge();
  const branchInstancesQuery = useQuery({
    queryKey: queryKeys.launcherBranchInstances(),
    queryFn: () => getLauncherBranchInstances(),
    staleTime: 15_000,
  });
  const launcherWindowTitle = currentInstanceWindowTitle("launcher", branchInstancesQuery.data);

  useEffect(() => {
    if (!stateBridgeAvailable) {
      return;
    }

    const invalidateBranchInstances = () => {
      void queryClient.invalidateQueries({ queryKey: ["launcher", "branch-instances"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherFreshness() });
    };
    const unsubscribe = onLauncherStateChanged(() => {
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

  return (
    <div
      className={styles.root}
      data-theme={theme}
      data-vui-app="launcher"
      data-shell="launcher"
      data-browser-role="launcher_control_surface"
    >
      <LauncherUpdateTopbar lang={lang} branchName={branchInstancesQuery.data?.currentShortName} />
      <VSplitWorkspace
        className={styles.workspace}
        columnsClassName={styles.columns}
        sidebar={<LauncherNavigation lang={lang} items={branchInstancesQuery.data?.items ?? []} />}
        main={<div className={styles.main}><Outlet /></div>}
      />
    </div>
  );
}
