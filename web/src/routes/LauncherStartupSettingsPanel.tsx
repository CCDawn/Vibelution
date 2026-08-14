import { LoaderCircle, Maximize2, Minimize2, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import type { LauncherStartupSettings } from "../api/launcher";
import type { WorkbenchWindowMode, WorkbenchWindowModeUpdateRequest } from "../api/types";
import { VButton, VNativeInput, VStringSelect, VTabs, VTooltip } from "../components/vui";
import styles from "./LauncherStartupSettingsPanel.styles";

type LauncherStartupSettingsCopy = {
  invalidPort: string;
  startupSettings: string;
  runtimeProfile: string;
  launcherControlPort: string;
  launcherControlPortHint: string;
  backendPort: string;
  backendPortHint: string;
  frontendPort: string;
  frontendPortHint: string;
  portOverride: string;
  effectiveValue: string;
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
  controlPortOverride: number;
  backendPortOverride: number;
  frontendPortOverride: number;
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

function parsePortDraft(value: string) {
  if (!/^\d+$/.test(value.trim())) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 && parsed < 65536 ? parsed : null;
}

function differingOverride(configured: number | string, override: number | string) {
  const left = String(configured || "").trim();
  const right = String(override || "").trim();
  if (!right || right === "0") {
    return "";
  }
  return left === right ? "" : right;
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
  controlPortOverride,
  backendPortOverride,
  frontendPortOverride,
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
        setting.launcher.controlPort,
        setting.launcher.controlPortEnvOverride,
        setting.runtime.profile,
        setting.runtime.preflightDoctor,
        setting.runtime.requireVenv,
        setting.workbench.backendPort,
        setting.workbench.frontendPort,
        setting.workbench.backendPortEnvOverride,
        setting.workbench.frontendPortEnvOverride,
        setting.workbench.windowMode,
        setting.workbench.windowModeEnvOverride,
        setting.workbench.windowSize,
        setting.workbench.windowSizeEnvOverride,
        setting.interface.language,
      ].join("|")
    : `fallback:${configuredWindowMode}`;
  const [draft, setDraft] = useState<LauncherStartupSettings>(() => current);
  const [controlPortText, setControlPortText] = useState(() => String(current.launcher.controlPort));
  const [backendPortText, setBackendPortText] = useState(() => String(current.workbench.backendPort));
  const [frontendPortText, setFrontendPortText] = useState(() => String(current.workbench.frontendPort));
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    setDraft(current);
    setControlPortText(String(current.launcher.controlPort));
    setBackendPortText(String(current.workbench.backendPort));
    setFrontendPortText(String(current.workbench.frontendPort));
    setValidationError("");
  }, [currentSignature]);

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
    const controlPort = parsePortDraft(controlPortText);
    const backendPort = parsePortDraft(backendPortText);
    const frontendPort = parsePortDraft(frontendPortText);
    if (!controlPort || !backendPort || !frontendPort) {
      setValidationError(copy.invalidPort);
      return;
    }
    setValidationError("");
    onSave({
      ...draft,
      launcher: {
        ...draft.launcher,
        controlPort,
      },
      workbench: {
        ...draft.workbench,
        backendPort,
        frontendPort,
      },
    });
  }

  function saveWindowMode(next: { windowMode: WorkbenchWindowMode }) {
    const mode = next.windowMode;
    patchDraft({ workbench: { ...draft.workbench, windowMode: mode } });
    setValidationError("");
    if (mode !== current.workbench.windowMode) {
      onWindowModeChange({ mode, baseHash: current.configHash });
    }
  }

  const controlOverride = differingOverride(current.launcher.controlPort, controlPortOverride);
  const backendOverride = differingOverride(current.workbench.backendPort, backendPortOverride);
  const frontendOverride = differingOverride(current.workbench.frontendPort, frontendPortOverride);
  const windowSizeOverride = differingOverride(current.workbench.windowSize, current.workbench.windowSizeEnvOverride);

  return (
    <div className={styles.settingsStrip} aria-label={copy.startupSettings}>
      <p className={styles.settingsTitle}>{copy.startupSettings}</p>
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
        <label className={styles.settingField}>
          <VTooltip content={copy.launcherControlPortHint} width="wide">
            <span tabIndex={0}>{copy.launcherControlPort}</span>
          </VTooltip>
          <VNativeInput
            type="number"
            min={1}
            max={65535}
            value={controlPortText}
            disabled={controlsDisabled}
            onChange={(event) => setControlPortText(event.target.value)}
          />
          {controlOverride ? <small>{copy.effectiveValue}: {controlOverride}</small> : null}
        </label>
        <label className={styles.settingField}>
          <VTooltip content={copy.backendPortHint} width="wide">
            <span tabIndex={0}>{copy.backendPort}</span>
          </VTooltip>
          <VNativeInput
            type="number"
            min={1}
            max={65535}
            value={backendPortText}
            disabled={controlsDisabled}
            onChange={(event) => setBackendPortText(event.target.value)}
          />
          {backendOverride ? <small>{copy.effectiveValue}: {backendOverride}</small> : null}
        </label>
        <label className={styles.settingField}>
          <VTooltip content={copy.frontendPortHint} width="wide">
            <span tabIndex={0}>{copy.frontendPort}</span>
          </VTooltip>
          <VNativeInput
            type="number"
            min={1}
            max={65535}
            value={frontendPortText}
            disabled={controlsDisabled}
            onChange={(event) => setFrontendPortText(event.target.value)}
          />
          {frontendOverride ? <small>{copy.effectiveValue}: {frontendOverride}</small> : null}
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
          {windowSizeOverride ? <small>{copy.effectiveValue}: {current.workbench.effectiveWindowSize}</small> : null}
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
      {validationError ? <small className={styles.settingError} role="alert">{validationError}</small> : null}
    </div>
  );
}
