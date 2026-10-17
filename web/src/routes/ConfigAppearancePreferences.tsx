import { useEffect, useState } from "react";
import { applyWorkbenchDocumentTheme, readStoredWorkbenchTheme, subscribeStoredWorkbenchTheme, writeStoredWorkbenchTheme } from "../app/themePreference";
import { VNativeSelect, VSettingsRow } from "../components/vui";
import type { ConfigCopy } from "./config/configCopy";
import { ConfigUiFontSettings } from "./ConfigUiFontSettings";

/** Local appearance preferences use the shell's existing persistence authority. */
export function ConfigAppearancePreferences({ copy }: { copy: ConfigCopy }) {
  const [theme, setTheme] = useState(readStoredWorkbenchTheme);
  useEffect(() => subscribeStoredWorkbenchTheme(setTheme), []);
  return <>
    <VSettingsRow label={copy.themeLabel} description={copy.themeDescription}
      control={<VNativeSelect aria-label={copy.themeLabel} value={theme} onChange={(event) => {
        const next = event.target.value === "dark" ? "dark" : "light";
        setTheme(next);
        writeStoredWorkbenchTheme(next);
        applyWorkbenchDocumentTheme(document, next);
      }}>
        <option value="light">{copy.themeLight}</option><option value="dark">{copy.themeDark}</option>
      </VNativeSelect>} />
    <ConfigUiFontSettings copy={copy} />
  </>;
}
