import { LoaderCircle, Maximize2, Minimize2, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import type { LauncherStartupSettings } from "../api/launcher";
import type { WorkbenchWindowMode, WorkbenchWindowModeUpdateRequest } from "../api/types";
import { VButton, VNativeInput, VStringSelect, VTabs, VTooltip } from "../components/vui";
import styles from "./LauncherStartupSettingsPanel.styles";

type LauncherStartupSettingsCopy = {
  startupSettings: string;
  expandSettings: string;
  collapseSettings: string;
  runtimeProfile: string;
  windowMode: string;
  windowModeFullscreen: string;
  windowModeWindowed: string;
  windowSize: string;
  windowSizeAuto: string;
  windowSizeEnvOverride: string;
  interfaceLanguage: string;
  languageZh: string;
  languageEn: string;
  preflightDoctor: string;
  requireVenv: string;
  saveStartupSettings: string;
};

type LauncherStartupSettingsPanelProps = {
  copy: LauncherStartupSettingsCopy;
  uiLang: "zh" | "en";
  setting: LauncherStartupSettings | undefined;
  configuredWindowMode: WorkbenchWindowMode;
  effectiveWindowModeLabel: string;
  windowModeDetail: string;
  pending: boolean;
  pendingWindowMode: WorkbenchWindowMode | "";
  onSave: (setting: LauncherStartupSettings) => void;
  onWindowModeChange: (request: WorkbenchWindowModeUpdateRequest) => void;
};

function defaultStartupSettings(windowMode: WorkbenchWindowMode = "fullscreen"): LauncherStartupSettings {
  return {
    launcher: {
      controlPort: 0,
      effectiveControlPort: 0,
      controlPortEnvOverride: 0,
    },
    runtime: {
      profile: "safe_remote",
      preflightDoctor: true,
      requireVenv: true,
      profileOptions: ["safe_local", "safe_remote", "debug", "ci"],
    },
    workbench: {
      backendPort: 8000,
      frontendPort: 5173,
      effectiveBackendPort: 8000,
      effectiveFrontendPort: 5173,
      backendPortEnvOverride: 0,
      frontendPortEnvOverride: 0,
      windowMode,
      effectiveWindowMode: windowMode,
      windowModeEnvOverride: "",
      windowSize: "auto",
      effectiveWindowSize: "auto",
      windowSizeEnvOverride: "",
      windowSizeOptions: [
        {
          size: "auto",
          label: { zh: "自动", en: "Auto" },
        },
      ],
      windowModeOptions: [],
    },
    interface: {
      language: "zh",
      languageOptions: ["zh", "en"],
    },
    configPath: "",
    configHash: "",
    restartRequired: true,
  };
}

function runtimeProfileLabel(profile: string, lang: "zh" | "en") {
  const labels: Record<string, { zh: string; en: string }> = {
    ci: { zh: "CI", en: "CI" },
    debug: { zh: "调试", en: "Debug" },
    safe_local: { zh: "安全本地", en: "Safe local" },
    safe_remote: { zh: "安全远程", en: "Safe remote" },
  };
  return labels[profile]?.[lang] ?? profile;
}

function windowSizeOptions(setting: LauncherStartupSettings, copy: LauncherStartupSettingsCopy) {
  const options = setting.workbench.windowSizeOptions.length
    ? [...setting.workbench.windowSizeOptions]
    : [{ size: "auto", label: { zh: copy.windowSizeAuto, en: copy.windowSizeAuto } }];
  const extras = [setting.workbench.windowSize, setting.workbench.effectiveWindowSize].filter(Boolean);
  extras.forEach((size) => {
    if (!options.some((option) => option.size === size)) {
      options.push({ size, label: { zh: size, en: size } });
    }
  });
  return options;
}

export function LauncherStartupSettingsPanel({
  copy,
  uiLang,
  setting,
  configuredWindowMode,
  effectiveWindowModeLabel,
  windowModeDetail,
  pending,
  pendingWindowMode,
  onSave,
  onWindowModeChange,
}: LauncherStartupSettingsPanelProps) {
  const current = setting ?? defaultStartupSettings(configuredWindowMode);
  const controlsDisabled = pending || Boolean(pendingWindowMode) || !setting?.configHash;
  const currentSignature = setting
    ? [
        setting.configHash,
        setting.runtime.profile,
        setting.runtime.preflightDoctor,
        setting.runtime.requireVenv,
        setting.workbench.windowMode,
        setting.workbench.windowModeEnvOverride,
        setting.workbench.windowSize,
        setting.workbench.windowSizeEnvOverride,
        setting.interface.language,
      ].join("|")
    : `fallback:${configuredWindowMode}`;
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState<LauncherStartupSettings>(() => current);

  useEffect(() => {
    setDraft(current);
  }, [currentSignature]);

  const settingsSummary = [
    runtimeProfileLabel(current.runtime.profile, uiLang),
    effectiveWindowModeLabel,
  ].join(" · ");

  function patchDraft(next: Partial<LauncherStartupSettings>) {
    setDraft((prev) => ({
      ...prev,
      ...next,
      runtime: { ...prev.runtime, ...next.runtime },
      workbench: { ...prev.workbench, ...next.workbench },
      interface: { ...prev.interface, ...next.interface },
    }));
  }

  function saveDraft() {
    onSave(draft);
  }

  function saveWindowMode(next: { windowMode: WorkbenchWindowMode }) {
    const mode = next.windowMode;
    patchDraft({ workbench: { ...draft.workbench, windowMode: mode } });
    if (mode !== current.workbench.windowMode) {
      onWindowModeChange({ mode, baseHash: current.configHash });
    }
  }

  const windowSizeOverride = current.workbench.windowSize !== current.workbench.windowSizeEnvOverride
    ? current.workbench.windowSizeEnvOverride
    : "";

  return (
    <div className={styles.settingsStrip} aria-label={copy.startupSettings}>
      <details
        className={styles.settingsFold}
        onToggle={(event) => setSettingsOpen(event.currentTarget.open)}
      >
        <summary className={styles.settingsSummary}>
          <span className={styles.settingsTitle}>{copy.startupSettings}</span>
          <strong className={styles.settingsSummaryValue}>{settingsSummary}</strong>
          <small className={styles.settingsSummaryHint}>
            {settingsOpen ? copy.collapseSettings : copy.expandSettings}
          </small>
        </summary>
        <div className={styles.settingsBody}>
          <div className={styles.settingsPrimary}>
            <label className={styles.settingField}>
              <span>{copy.runtimeProfile}</span>
              <VStringSelect
                ariaLabel={copy.runtimeProfile}
                value={draft.runtime.profile}
                isDisabled={controlsDisabled}
                onValueChange={(profile) => patchDraft({ runtime: { ...draft.runtime, profile } })}
                options={draft.runtime.profileOptions.map((profile) => ({
                  value: profile,
                  label: runtimeProfileLabel(profile, uiLang),
                }))}
              />
            </label>
          </div>
          <div className={styles.settingsWindow}>
            <div className={styles.settingField}>
              <VTooltip content={`${effectiveWindowModeLabel} · ${windowModeDetail}`} width="wide">
                <span tabIndex={0}>{copy.windowMode}</span>
              </VTooltip>
              <VTabs
                density="compact"
                className={styles.windowModeTabs}
                listClassName={styles.windowModeTabsList}
                triggerClassName={styles.windowModeTabsTrigger}
                aria-label={copy.windowMode}
                value={draft.workbench.windowMode === "windowed" ? "windowed" : "fullscreen"}
                onValueChange={(value) => {
                  if (controlsDisabled) {
                    return;
                  }
                  if (value === "fullscreen" || value === "windowed") {
                    saveWindowMode({ windowMode: value });
                  }
                }}
                items={[
                  {
                    id: "fullscreen",
                    label: (
                      <span className={styles.windowModeTabLabel}>
                        {pendingWindowMode === "fullscreen" ? <LoaderCircle size={14} className={styles.spin} aria-hidden="true" /> : <Maximize2 size={14} aria-hidden="true" />}
                        <span>{copy.windowModeFullscreen}</span>
                      </span>
                    ),
                    title: copy.windowModeFullscreen,
                    disabled: controlsDisabled,
                  },
                  {
                    id: "windowed",
                    label: (
                      <span className={styles.windowModeTabLabel}>
                        {pendingWindowMode === "windowed" ? <LoaderCircle size={14} className={styles.spin} aria-hidden="true" /> : <Minimize2 size={14} aria-hidden="true" />}
                        <span>{copy.windowModeWindowed}</span>
                      </span>
                    ),
                    title: copy.windowModeWindowed,
                    disabled: controlsDisabled,
                  },
                ]}
              />
            </div>
            <label className={styles.settingField}>
              <span>{copy.windowSize}</span>
              <VStringSelect
                ariaLabel={copy.windowSize}
                value={draft.workbench.windowSize}
                isDisabled={controlsDisabled}
                onValueChange={(windowSize) => patchDraft({ workbench: { ...draft.workbench, windowSize } })}
                options={windowSizeOptions(draft, copy).map((option) => ({
                  value: option.size,
                  label: option.label[uiLang] ?? option.size,
                }))}
              />
              {windowSizeOverride ? <small>{copy.windowSizeEnvOverride}: {current.workbench.effectiveWindowSize}</small> : null}
            </label>
            <VButton
              type="button"
              variant="secondary"
              className={styles.settingsSaveButton}
              isDisabled={controlsDisabled}
              onPress={saveDraft}
              icon={pending ? <LoaderCircle size={14} className={styles.spin} /> : <RefreshCw size={14} />}
            >
              <span>{copy.saveStartupSettings}</span>
            </VButton>
          </div>
          <div className={styles.settingsSecondary}>
            <label className={styles.settingField}>
              <span>{copy.interfaceLanguage}</span>
              <VStringSelect
                ariaLabel={copy.interfaceLanguage}
                value={draft.interface.language}
                isDisabled={controlsDisabled}
                onValueChange={(language) => patchDraft({ interface: { ...draft.interface, language } })}
                options={[
                  { value: "zh", label: copy.languageZh },
                  { value: "en", label: copy.languageEn },
                ]}
              />
            </label>
            <label className={styles.settingToggle}>
              <VNativeInput
                type="checkbox"
                checked={draft.runtime.preflightDoctor}
                disabled={controlsDisabled}
                onChange={(event) => patchDraft({ runtime: { ...draft.runtime, preflightDoctor: event.target.checked } })}
              />
              <span>{copy.preflightDoctor}</span>
            </label>
            <label className={styles.settingToggle}>
              <VNativeInput
                type="checkbox"
                checked={draft.runtime.requireVenv}
                disabled={controlsDisabled}
                onChange={(event) => patchDraft({ runtime: { ...draft.runtime, requireVenv: event.target.checked } })}
              />
              <span>{copy.requireVenv}</span>
            </label>
          </div>
        </div>
      </details>
    </div>
  );
}
