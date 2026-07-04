import { LoaderCircle, Maximize2, Minimize2, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import type { LauncherStartupSettings } from "../api/launcher";
import type { WorkbenchWindowMode, WorkbenchWindowModeUpdateRequest } from "../api/types";
import { VButton, VNativeInput, VNativeSelect } from "../components/vui";
import styles from "./LauncherStartupSettingsPanel.styles";

type LauncherStartupSettingsCopy = {
  invalidPort: string;
  startupSettings: string;
  runtimeProfile: string;
  launcherControlPort: string;
  backendPort: string;
  frontendPort: string;
  portOverride: string;
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
      controlPort: 8765,
      effectiveControlPort: 8765,
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

  return (
    <div className={styles.settingsStrip} aria-label={copy.startupSettings}>
      <div className={styles.settingsHeader} title={windowModeDetail}>
        <span>{copy.startupSettings}</span>
        <strong>{effectiveWindowModeLabel}</strong>
      </div>
      <label className={styles.settingField}>
        <span>{copy.runtimeProfile}</span>
        <VNativeSelect
          value={draft.runtime.profile}
          disabled={controlsDisabled}
          onChange={(event) => patchDraft({ runtime: { ...draft.runtime, profile: event.target.value } })}
        >
          {draft.runtime.profileOptions.map((profile) => (
            <option key={profile} value={profile}>
              {runtimeProfileLabel(profile, uiLang)}
            </option>
          ))}
        </VNativeSelect>
      </label>
      <label className={styles.settingField}>
        <span>{copy.launcherControlPort}</span>
        <VNativeInput
          type="number"
          min={1}
          max={65535}
          value={controlPortText}
          disabled={controlsDisabled}
          onChange={(event) => setControlPortText(event.target.value)}
        />
        {controlPortOverride ? <small>{copy.portOverride}: {controlPortOverride}</small> : null}
      </label>
      <label className={styles.settingField}>
        <span>{copy.backendPort}</span>
        <VNativeInput
          type="number"
          min={1}
          max={65535}
          value={backendPortText}
          disabled={controlsDisabled}
          onChange={(event) => setBackendPortText(event.target.value)}
        />
        {backendPortOverride ? <small>{copy.portOverride}: {backendPortOverride}</small> : null}
      </label>
      <label className={styles.settingField}>
        <span>{copy.frontendPort}</span>
        <VNativeInput
          type="number"
          min={1}
          max={65535}
          value={frontendPortText}
          disabled={controlsDisabled}
          onChange={(event) => setFrontendPortText(event.target.value)}
        />
        {frontendPortOverride ? <small>{copy.portOverride}: {frontendPortOverride}</small> : null}
      </label>
      <div className={styles.segmentedControl} role="group" aria-label={copy.windowMode}>
        <VButton
          type="button"
          variant="secondary"
          data-active={draft.workbench.windowMode === "fullscreen"}
          isDisabled={controlsDisabled}
          onPress={() => saveWindowMode({ windowMode: "fullscreen" })}
          title={copy.windowModeFullscreen}
          icon={pendingWindowMode === "fullscreen" ? <LoaderCircle size={14} className={styles.spin} /> : <Maximize2 size={14} />}
        >
          <span>{copy.windowModeFullscreen}</span>
        </VButton>
        <VButton
          type="button"
          variant="secondary"
          data-active={draft.workbench.windowMode === "windowed"}
          isDisabled={controlsDisabled}
          onPress={() => saveWindowMode({ windowMode: "windowed" })}
          title={copy.windowModeWindowed}
          icon={pendingWindowMode === "windowed" ? <LoaderCircle size={14} className={styles.spin} /> : <Minimize2 size={14} />}
        >
          <span>{copy.windowModeWindowed}</span>
        </VButton>
      </div>
      <label className={styles.settingField}>
        <span>{copy.windowSize}</span>
        <VNativeSelect
          value={draft.workbench.windowSize}
          disabled={controlsDisabled}
          onChange={(event) => patchDraft({ workbench: { ...draft.workbench, windowSize: event.target.value } })}
        >
          {(draft.workbench.windowSizeOptions.length
            ? draft.workbench.windowSizeOptions
            : [{ size: "auto", label: { zh: copy.windowSizeAuto, en: copy.windowSizeAuto } }]
          ).map((option) => (
            <option key={option.size} value={option.size}>
              {option.label[uiLang] ?? option.size}
            </option>
          ))}
        </VNativeSelect>
        {draft.workbench.windowSizeEnvOverride ? <small>{copy.windowSizeEnvOverride}: {draft.workbench.effectiveWindowSize}</small> : null}
      </label>
      <label className={styles.settingField}>
        <span>{copy.interfaceLanguage}</span>
        <VNativeSelect
          value={draft.interface.language}
          disabled={controlsDisabled}
          onChange={(event) => patchDraft({ interface: { ...draft.interface, language: event.target.value } })}
        >
          <option value="zh">{copy.languageZh}</option>
          <option value="en">{copy.languageEn}</option>
        </VNativeSelect>
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
      {validationError ? <small className={styles.settingError} role="alert">{validationError}</small> : null}
    </div>
  );
}
