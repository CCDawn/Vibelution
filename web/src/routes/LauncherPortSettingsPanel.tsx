import { LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import type { LauncherStartupSettings } from "../api/launcher";
import { VButton, VNativeInput, VTooltip } from "../components/vui";
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
  saveStartupSettings: string;
  invalidPort: string;
};

type LauncherPortSettingsPanelProps = {
  copy: LauncherPortSettingsCopy;
  setting: LauncherStartupSettings | undefined;
  controlPortOverride: number;
  backendPortOverride: number;
  frontendPortOverride: number;
  pending: boolean;
  onSave: (setting: LauncherStartupSettings) => void;
};

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
  const [controlPortText, setControlPortText] = useState("");
  const [backendPortText, setBackendPortText] = useState("");
  const [frontendPortText, setFrontendPortText] = useState("");
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    setControlPortText(String(setting?.launcher.controlPort ?? ""));
    setBackendPortText(String(setting?.workbench.backendPort ?? ""));
    setFrontendPortText(String(setting?.workbench.frontendPort ?? ""));
    setValidationError("");
  }, [signature]);

  const current = setting;
  if (!current) {
    return null;
  }

  const controlsDisabled = pending || !current.configHash;
  const controlOverride = differingOverride(current.launcher.controlPort, controlPortOverride);
  const backendOverride = differingOverride(current.workbench.backendPort, backendPortOverride);
  const frontendOverride = differingOverride(current.workbench.frontendPort, frontendPortOverride);

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
    setValidationError("");
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
            {copy.saveStartupSettings}
          </VButton>
        </div>
      </div>
    </details>
  );
}
