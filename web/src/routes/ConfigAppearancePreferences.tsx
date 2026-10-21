import { useEffect, useState } from "react";
import { applyWorkbenchDocumentTheme, readStoredWorkbenchTheme, subscribeStoredWorkbenchTheme, writeStoredWorkbenchTheme } from "../app/themePreference";
import { VSettingsRow, VStringSelect } from "../components/vui";
import type { ConfigCopy } from "./config/configCopy";
import { ConfigUiFontSettings } from "./ConfigUiFontSettings";

/** Local appearance preferences use the shell's existing persistence authority. */
export function ConfigAppearancePreferences({ copy }: { copy: ConfigCopy }) {
  const [theme, setTheme] = useState(readStoredWorkbenchTheme);
  useEffect(() => subscribeStoredWorkbenchTheme(setTheme), []);
  return <>
    <VSettingsRow label={copy.themeLabel} description={copy.themeDescription}
      control={<VStringSelect ariaLabel={copy.themeLabel} value={theme}
        options={[{ value: "light", label: copy.themeLight }, { value: "dark", label: copy.themeDark }]}
        onValueChange={(value) => {
          const next = value === "dark" ? "dark" : "light";
          setTheme(next);
          writeStoredWorkbenchTheme(next);
          applyWorkbenchDocumentTheme(document, next);
        }} />} />
    <ConfigUiFontSettings copy={copy} />
  </>;
}
