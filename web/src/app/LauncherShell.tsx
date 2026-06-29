import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";

import { useShellI18n } from "../i18n/useShellI18n";
import { collectBrowserPageSnapshot, postBrowserTelemetry } from "./browserTelemetry";
import { applyWorkbenchDocumentLanguage } from "./documentLanguage";
import { readStoredWorkbenchTheme } from "./themePreference";
import styles from "./LauncherShell.module.css";

export function LauncherShell() {
  const { lang } = useShellI18n();
  const [theme] = useState(() => readStoredWorkbenchTheme());

  useEffect(() => {
    applyWorkbenchDocumentLanguage(document, lang);
    document.title = "Vibelution Launcher";
  }, [lang]);

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
      className={styles.shell}
      data-theme={theme}
      data-vui-app="launcher"
      data-shell="launcher"
      data-browser-role="launcher_control_surface"
    >
      <Outlet />
    </div>
  );
}
