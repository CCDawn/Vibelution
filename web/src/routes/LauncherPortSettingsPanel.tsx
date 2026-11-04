import { LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { LauncherStartupSettings } from "../api/launcher";
import { VButton, VNativeInput, VTooltip } from "../components/vui";
import startupStyles from "./LauncherStartupSettingsPanel.styles";
import styles from "./LauncherPortSettingsPanel.styles";

type LauncherPortSettingsCopy = {
  portSettings: string;
  portSettingsHint: string;
  launcherControlPort: string;
  launcherControlPortHint: string;
  backendPort: string;
  backendPortHint: string;
  frontendPort: string;
  frontendPortHint: string;
  portOverride: string;
  savePortSettings: string;
  invalidPort: string;
};

type LauncherPortSettingsPanelProps = {
  copy: LauncherPortSettingsCopy;
  /** Language for the conflict notice; defaults to Chinese until callers pass the UI language. */
  uiLang?: "zh" | "en";
  setting: LauncherStartupSettings | undefined;
  controlPortOverride: number;
  backendPortOverride: number;
  frontendPortOverride: number;
  pending: boolean;
  onSave: (setting: LauncherStartupSettings) => void;
};

type PortTexts = { control: string; backend: string; frontend: string };

function portTexts(setting: LauncherStartupSettings | undefined): PortTexts {
  return {
    control: String(setting?.launcher.controlPort ?? ""),
    backend: String(setting?.workbench.backendPort ?? ""),
    frontend: String(setting?.workbench.frontendPort ?? ""),
  };
}

function portConflictText(uiLang: "zh" | "en") {
  return uiLang === "zh"
    ? {
        conflict: "端口设置已被其他页面或进程修改。草稿已保留，加载最新设置后可重新编辑。",
        loadLatest: "加载最新设置",
        waitingForLatest: "正在读取最新设置…",
      }
    : {
        conflict: "Port settings changed in another page or process. Your draft is preserved; load the latest settings before editing again.",
        loadLatest: "Load latest settings",
        waitingForLatest: "Waiting for the latest settings…",
      };
}

function parsePortDraft(value: string) {
  if (!/^\d+$/.test(value.trim())) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 && parsed < 65536 ? parsed : null;
}

function differingOverride(configured: number, override: number) {
  return override > 0 && override !== configured ? String(override) : "";
}

export function LauncherPortSettingsPanel({
  copy,
  uiLang = "zh",
  setting,
  controlPortOverride,
  backendPortOverride,
  frontendPortOverride,
  pending,
  onSave,
}: LauncherPortSettingsPanelProps) {
  const signature = setting
    ? [
        setting.configHash,
        setting.launcher.controlPort,
        setting.workbench.backendPort,
        setting.workbench.frontendPort,
      ].join("|")
    : "";
  const [controlPortText, setControlPortText] = useState(() => String(setting?.launcher.controlPort ?? ""));
  const [backendPortText, setBackendPortText] = useState(() => String(setting?.workbench.backendPort ?? ""));
  const [frontendPortText, setFrontendPortText] = useState(() => String(setting?.workbench.frontendPort ?? ""));
  const [validationError, setValidationError] = useState("");
  const [baseline, setBaseline] = useState(() => ({ ...portTexts(setting), configHash: setting?.configHash ?? "" }));
  const [conflictSetting, setConflictSetting] = useState<LauncherStartupSettings>();
  const text = portConflictText(uiLang);
  const dirty = controlPortText !== baseline.control
    || backendPortText !== baseline.backend
    || frontendPortText !== baseline.frontend;
  const previousSignature = useRef(signature);
  const baselineRef = useRef(baseline);
  const dirtyRef = useRef(dirty);
  const pendingRef = useRef(pending);
  baselineRef.current = baseline;
  dirtyRef.current = dirty;
  pendingRef.current = pending;

  useEffect(() => {
    if (signature === previousSignature.current) {
      return;
    }
    previousSignature.current = signature;

    if (!dirtyRef.current && !pendingRef.current) {
      const next = portTexts(setting);
      setControlPortText(next.control);
      setBackendPortText(next.backend);
      setFrontendPortText(next.frontend);
      setBaseline({ ...next, configHash: setting?.configHash ?? "" });
      setValidationError("");
      setConflictSetting(undefined);
      return;
    }

    if (setting?.configHash && setting.configHash !== baselineRef.current.configHash) {
      setConflictSetting(setting);
    }
  }, [setting, signature]);

  const current = setting;
  if (!current) {
    return null;
  }

  const controlsDisabled = pending || !current.configHash || Boolean(conflictSetting);
  const controlOverride = differingOverride(current.launcher.controlPort, controlPortOverride);
  const backendOverride = differingOverride(current.workbench.backendPort, backendPortOverride);
  const frontendOverride = differingOverride(current.workbench.frontendPort, frontendPortOverride);

  function adoptLatestPorts() {
    const latest = conflictSetting;
    if (!latest?.configHash) {
      return;
    }
    const next = portTexts(latest);
    setControlPortText(next.control);
    setBackendPortText(next.backend);
    setFrontendPortText(next.frontend);
    setBaseline({ ...next, configHash: latest.configHash });
    setConflictSetting(undefined);
    setValidationError("");
  }

  function savePorts() {
    const currentSetting = setting;
    if (!currentSetting) {
      return;
    }
    const controlPort = parsePortDraft(controlPortText);
    const backendPort = parsePortDraft(backendPortText);
    const frontendPort = parsePortDraft(frontendPortText);
    if (!controlPort || !backendPort || !frontendPort) {
      setValidationError(copy.invalidPort);
      return;
    }
    const next: PortTexts = {
      control: String(controlPort),
      backend: String(backendPort),
      frontend: String(frontendPort),
    };
    setValidationError("");
    setControlPortText(next.control);
    setBackendPortText(next.backend);
    setFrontendPortText(next.frontend);
    setBaseline({ ...next, configHash: currentSetting.configHash });
    onSave({
      ...currentSetting,
      launcher: { ...currentSetting.launcher, controlPort },
      workbench: { ...currentSetting.workbench, backendPort, frontendPort },
    });
  }

  return (
    <details className={styles.panel}>
      <summary className={styles.summary}>
        <span className={styles.title}>{copy.portSettings}</span>
        <small className={styles.hint}>{copy.portSettingsHint}</small>
      </summary>
      <div className={styles.body}>
        {conflictSetting ? (
          <div className={startupStyles.settingsConflict} role="alert">
            <p>{text.conflict}</p>
            <VButton type="button" variant="secondary" onPress={adoptLatestPorts}>
              {text.loadLatest}
            </VButton>
          </div>
        ) : null}
        <div className={styles.fields}>
          <label className={styles.field}>
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
            {controlOverride ? <small>{copy.portOverride}: {controlOverride}</small> : null}
          </label>
          <label className={styles.field}>
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
            {backendOverride ? <small>{copy.portOverride}: {backendOverride}</small> : null}
          </label>
          <label className={styles.field}>
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
            {frontendOverride ? <small>{copy.portOverride}: {frontendOverride}</small> : null}
          </label>
        </div>
        {validationError ? <small className={styles.error} role="alert">{validationError}</small> : null}
        <div className={styles.actions}>
          <VButton
            type="button"
            variant="secondary"
            className={styles.save}
            isDisabled={controlsDisabled}
            onPress={savePorts}
            icon={pending ? <LoaderCircle size={14} className={styles.spin} /> : <RefreshCw size={14} />}
          >
            {copy.savePortSettings}
          </VButton>
        </div>
      </div>
    </details>
  );
}
