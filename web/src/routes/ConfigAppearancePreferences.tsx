import { useEffect, useRef, useState } from "react";
import { applyWorkbenchDocumentTheme, readStoredWorkbenchTheme, requestWorkbenchTheme, subscribeStoredWorkbenchTheme, subscribeWorkbenchThemeSync, useAuthorityTheme } from "../app/themePreference";
import { VButton, VSettingsRow, VStringSelect } from "../components/vui";
import type { ConfigCopy } from "./config/configCopy";
import { ConfigUiFontSettings } from "./ConfigUiFontSettings";

/** Local appearance preferences use the shell's existing persistence authority. */
export function ConfigAppearancePreferences({ copy }: { copy: ConfigCopy }) {
  const [theme, setTheme] = useState(readStoredWorkbenchTheme);
  const [syncState, setSyncState] = useState<"applied" | "local" | "conflict" | "unknown" | "unavailable">("applied");
  const [themePending, setThemePending] = useState(false);
  const themeGate = useRef(false);
  useEffect(() => subscribeStoredWorkbenchTheme(setTheme), []);
  useEffect(() => subscribeWorkbenchThemeSync(setSyncState), []);
  const choose = (next: "dark" | "light") => {
    if (themeGate.current) return;
    themeGate.current = true;
    setThemePending(true);
    void requestWorkbenchTheme(next).then(result => {
      if (result === "superseded") return;
      setSyncState(result);
      if (result !== "unavailable") { const current = readStoredWorkbenchTheme(); setTheme(current); applyWorkbenchDocumentTheme(document, current); }
    }).finally(() => { themeGate.current = false; setThemePending(false); });
  };
  return <>
    <VSettingsRow label={copy.themeLabel} description={syncState === "applied" ? copy.themeDescription : syncState === "local" ? copy.themeUnconfirmed : syncState === "conflict" ? copy.themeConflict : syncState === "unknown" ? copy.themeUnknown : copy.themeUnavailable}
      control={<><VStringSelect ariaLabel={copy.themeLabel} value={theme} isDisabled={themePending}
        options={[{ value: "light", label: copy.themeLight }, { value: "dark", label: copy.themeDark }]}
        onValueChange={(value) => choose(value === "dark" ? "dark" : "light")} />
        {syncState !== "applied" ? <><VButton isDisabled={themePending} onPress={() => choose(theme)}>{copy.themeUseCurrent}</VButton>
          <VButton isDisabled={themePending} onPress={() => { if (themeGate.current) return; themeGate.current = true; setThemePending(true); void useAuthorityTheme().then(result => { if (result !== "superseded") { setSyncState(result); if (result !== "unavailable") applyWorkbenchDocumentTheme(document, readStoredWorkbenchTheme()); } }).finally(() => { themeGate.current = false; setThemePending(false); }); }}>{copy.themeUseGlobal}</VButton></> : null}</>} />
    <ConfigUiFontSettings copy={copy} />
  </>;
}
