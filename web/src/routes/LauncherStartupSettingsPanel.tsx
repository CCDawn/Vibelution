import { useEffect, useRef, useState } from "react";

import type {
  LauncherStartupSettings,
  LauncherStartupSettingsUpdateResponse,
} from "../api/launcher";
import type { WorkbenchWindowMode, WorkbenchWindowModeUpdateRequest } from "../api/types";
import {
  VButton,
  VCheckbox,
  VSettingsFormPage,
  VSettingsGroupCard,
  VSettingsRow,
  VStringSelect,
} from "../components/vui";
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
  /** Kept for existing callers; window mode now saves with the complete settings draft. */
  pendingWindowMode?: WorkbenchWindowMode | "";
  onSave: (setting: LauncherStartupSettings) => Promise<LauncherStartupSettingsUpdateResponse["setting"]>;
  /** Kept for compatibility with older callers; never called by this panel. */
  onWindowModeChange?: (request: WorkbenchWindowModeUpdateRequest) => void;
  /** Show the editor as a page instead of the legacy collapsed summary strip. */
  standalone?: boolean;
  /** Lets a parent guard navigation while this panel has an unsaved draft. */
  onDirtyChange?: (dirty: boolean) => void;
};

type StartupSettingsEditableValues = Pick<
  LauncherStartupSettings["runtime"],
  "profile" | "preflightDoctor" | "requireVenv"
> & {
  windowMode: WorkbenchWindowMode;
  windowSize: string;
  language: string;
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

function editableValues(setting: LauncherStartupSettings): StartupSettingsEditableValues {
  return {
    profile: setting.runtime.profile,
    preflightDoctor: setting.runtime.preflightDoctor,
    requireVenv: setting.runtime.requireVenv,
    windowMode: setting.workbench.windowMode,
    windowSize: setting.workbench.windowSize,
    language: setting.interface.language,
  };
}

function sameEditableValues(left: LauncherStartupSettings, right: LauncherStartupSettings): boolean {
  return JSON.stringify(editableValues(left)) === JSON.stringify(editableValues(right));
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

function isConflictError(error: unknown): boolean {
  if (!error || typeof error !== "object") {
    return false;
  }
  const candidate = error as { status?: unknown; code?: unknown; message?: unknown };
  return candidate.status === 409
    || candidate.code === "launcher_startup_settings_conflict"
    || (typeof candidate.message === "string" && /startup settings conflict|settings? (?:was |were )?changed|配置.{0,12}改动|设置.{0,12}改动/i.test(candidate.message));
}

function errorMessage(error: unknown, lang: "zh" | "en"): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return lang === "zh" ? "保存启动设置失败，请稍后重试。" : "Could not save startup settings. Try again.";
}

function startupSettingsText(lang: "zh" | "en") {
  return lang === "zh"
    ? {
        pageTitle: "启动与窗口",
        runtimeProfileDescription: "选择工作区启动时使用的运行配置。",
        windowModeDescription: "应用于之后打开或重启的工作区。",
        windowModeOverride: "环境变量覆盖了此设置，当前生效：",
        windowSizeDescription: "设置之后打开的工作区窗口初始尺寸。",
        windowSizeOverride: "环境变量覆盖了此设置，当前生效：",
        interfaceLanguageDescription: "控制 Launcher 和工作区界面的显示语言。",
        preflightDescription: "启动前检查运行环境与依赖，提前发现问题。",
        requireVenvDescription: "要求工作区使用项目自己的 .venv 环境。",
        unsaved: "有未保存的更改",
        clean: "没有未保存的更改",
        discard: "撤销更改",
        loadLatest: "加载最新设置",
        waitingForLatest: "正在读取最新设置…",
        conflict: "启动设置已被其他页面或进程修改。草稿已保留，请加载最新设置后重新编辑。",
        saveFailed: "保存启动设置失败，请稍后重试。",
        saving: "正在保存…",
        notLoaded: "正在读取设置；加载完成后即可编辑。",
      }
    : {
        pageTitle: "Startup and window",
        runtimeProfileDescription: "Choose the runtime configuration for workbench launches.",
        windowModeDescription: "Applies to workbenches opened or restarted later.",
        windowModeOverride: "Overridden by an environment variable. Effective value:",
        windowSizeDescription: "Set the initial size for workbench windows opened later.",
        windowSizeOverride: "Overridden by an environment variable. Effective value:",
        interfaceLanguageDescription: "Controls the display language in Launcher and workbenches.",
        preflightDescription: "Check the runtime environment and dependencies before launch.",
        requireVenvDescription: "Require workbenches to use the project's own .venv environment.",
        unsaved: "You have unsaved changes",
        clean: "No unsaved changes",
        discard: "Discard changes",
        loadLatest: "Load latest settings",
        waitingForLatest: "Waiting for the latest settings…",
        conflict: "Startup settings changed in another page or process. Your draft is preserved; load the latest settings before editing again.",
        saveFailed: "Could not save startup settings. Try again later.",
        saving: "Saving…",
        notLoaded: "Loading settings. Editing will be available when they finish loading.",
      };
}

export function LauncherStartupSettingsPanel({
  copy,
  uiLang,
  setting,
  configuredWindowMode,
  effectiveWindowModeLabel,
  windowModeDetail,
  pending,
  onSave,
  standalone = false,
  onDirtyChange,
}: LauncherStartupSettingsPanelProps) {
  const current = setting ?? defaultStartupSettings(configuredWindowMode);
  const [baseSetting, setBaseSetting] = useState<LauncherStartupSettings>(() => current);
  const [draft, setDraft] = useState<LauncherStartupSettings>(() => current);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveConflict, setSaveConflict] = useState(false);
  const [conflictSetting, setConflictSetting] = useState<LauncherStartupSettings>();
  const [saveError, setSaveError] = useState("");
  const signature = JSON.stringify(current);
  const previousSignature = useRef(signature);
  const baseSettingRef = useRef(baseSetting);
  const savingRef = useRef(saving);
  const dirty = !sameEditableValues(draft, baseSetting);
  const dirtyRef = useRef(dirty);
  const onDirtyChangeRef = useRef(onDirtyChange);
  const text = startupSettingsText(uiLang);

  baseSettingRef.current = baseSetting;
  savingRef.current = saving;
  dirtyRef.current = dirty;
  onDirtyChangeRef.current = onDirtyChange;

  useEffect(() => {
    if (signature === previousSignature.current) {
      return;
    }
    previousSignature.current = signature;

    if (!dirtyRef.current && !savingRef.current) {
      setBaseSetting(current);
      setDraft(current);
      setSaveConflict(false);
      setConflictSetting(undefined);
      setSaveError("");
      return;
    }

    if (setting && setting.configHash !== baseSettingRef.current.configHash) {
      setSaveConflict(true);
      setConflictSetting(setting);
    }
  }, [current, setting, signature]);

  useEffect(() => {
    onDirtyChangeRef.current?.(dirty);
  }, [dirty]);

  const currentPropIsNewer = Boolean(
    signature !== previousSignature.current
      && setting?.configHash
      && setting.configHash !== baseSetting.configHash,
  );
  const latestConflictSetting = conflictSetting ?? (currentPropIsNewer ? setting : undefined);
  const hasLatestSettings = Boolean(latestConflictSetting?.configHash);
  const conflicted = saveConflict || Boolean(conflictSetting) || currentPropIsNewer;
  const controlsDisabled = pending || saving || !setting?.configHash || conflicted;
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
    setSaveError("");
  }

  async function saveDraft() {
    if (!dirty || controlsDisabled) {
      return;
    }
    setSaveError("");
    setSaving(true);
    try {
      const saved = await onSave(draft);
      setBaseSetting(saved);
      setDraft(saved);
      setSaveConflict(false);
      setConflictSetting(undefined);
      setSaveError("");
    } catch (error) {
      setSaveError(errorMessage(error, uiLang));
      if (isConflictError(error)) {
        setSaveConflict(true);
        setConflictSetting(undefined);
      }
    } finally {
      setSaving(false);
    }
  }

  function discardDraft() {
    if (hasLatestSettings && latestConflictSetting) {
      setBaseSetting(latestConflictSetting);
      setDraft(latestConflictSetting);
      setSaveConflict(false);
      setConflictSetting(undefined);
    } else {
      setDraft(baseSetting);
      setSaveConflict(false);
    }
    setSaveError("");
  }

  const profileOptions = [...new Set([
    ...current.runtime.profileOptions,
    draft.runtime.profile,
  ])];
  const modeOptions = current.workbench.windowModeOptions.length
    ? current.workbench.windowModeOptions
    : [
        { mode: "fullscreen" as const, label: { zh: copy.windowModeFullscreen, en: copy.windowModeFullscreen }, detail: { zh: "", en: "" } },
        { mode: "windowed" as const, label: { zh: copy.windowModeWindowed, en: copy.windowModeWindowed }, detail: { zh: "", en: "" } },
      ];
  const languageOptions = [...new Set([
    ...current.interface.languageOptions,
    draft.interface.language,
  ])];
  const windowSizeOverride = current.workbench.windowSizeEnvOverride;
  const windowModeOverride = current.workbench.windowModeEnvOverride;

  const settingsRows = (
    <VSettingsGroupCard className={styles.settingsGroup}>
      <VSettingsRow
        label={copy.runtimeProfile}
        description={text.runtimeProfileDescription}
        testId="row-runtime-profile"
        control={(
          <VStringSelect
            ariaLabel={copy.runtimeProfile}
            className={styles.settingsSelect}
            value={draft.runtime.profile}
            isDisabled={controlsDisabled}
            onValueChange={(profile) => patchDraft({ runtime: { ...draft.runtime, profile } })}
            options={profileOptions.map((profile) => ({
              value: profile,
              label: runtimeProfileLabel(profile, uiLang),
            }))}
          />
        )}
      />
      <VSettingsRow
        label={copy.windowMode}
        description={text.windowModeDescription}
        testId="row-window-mode"
        detail={windowModeOverride
          ? `${text.windowModeOverride} ${effectiveWindowModeLabel}`
          : windowModeDetail}
        control={(
          <VStringSelect
            ariaLabel={copy.windowMode}
            className={styles.settingsSelect}
            value={draft.workbench.windowMode}
            isDisabled={controlsDisabled}
            onValueChange={(windowMode) => {
              if (windowMode === "fullscreen" || windowMode === "windowed") {
                patchDraft({ workbench: { ...draft.workbench, windowMode } });
              }
            }}
            options={modeOptions.map((option) => ({
              value: option.mode,
              label: option.label[uiLang] ?? option.mode,
              description: option.detail[uiLang] || undefined,
            }))}
          />
        )}
      />
      <VSettingsRow
        label={copy.windowSize}
        description={text.windowSizeDescription}
        testId="row-window-size"
        detail={windowSizeOverride
          ? `${text.windowSizeOverride} ${current.workbench.effectiveWindowSize}`
          : undefined}
        control={(
          <VStringSelect
            ariaLabel={copy.windowSize}
            className={styles.settingsSelect}
            value={draft.workbench.windowSize}
            isDisabled={controlsDisabled}
            onValueChange={(windowSize) => patchDraft({ workbench: { ...draft.workbench, windowSize } })}
            options={windowSizeOptions(current, copy).map((option) => ({
              value: option.size,
              label: option.label[uiLang] ?? option.size,
            }))}
          />
        )}
      />
      <VSettingsRow
        label={copy.interfaceLanguage}
        description={text.interfaceLanguageDescription}
        testId="row-interface-language"
        control={(
          <VStringSelect
            ariaLabel={copy.interfaceLanguage}
            className={styles.settingsSelect}
            value={draft.interface.language}
            isDisabled={controlsDisabled}
            onValueChange={(language) => patchDraft({ interface: { ...draft.interface, language } })}
            options={languageOptions.map((language) => ({
              value: language,
              label: language === "zh" ? copy.languageZh : language === "en" ? copy.languageEn : language,
            }))}
          />
        )}
      />
      <VSettingsRow
        label={copy.preflightDoctor}
        description={text.preflightDescription}
        testId="row-preflight-doctor"
        control={(
          <VCheckbox
            aria-label={copy.preflightDoctor}
            isSelected={draft.runtime.preflightDoctor}
            isDisabled={controlsDisabled}
            onChange={(preflightDoctor) => patchDraft({ runtime: { ...draft.runtime, preflightDoctor } })}
          />
        )}
      />
      <VSettingsRow
        label={copy.requireVenv}
        description={text.requireVenvDescription}
        testId="row-require-venv"
        control={(
          <VCheckbox
            aria-label={copy.requireVenv}
            isSelected={draft.runtime.requireVenv}
            isDisabled={controlsDisabled}
            onChange={(requireVenv) => patchDraft({ runtime: { ...draft.runtime, requireVenv } })}
          />
        )}
      />
    </VSettingsGroupCard>
  );

  const conflictMessage = (
    <div className={styles.settingsConflict} role="alert">
      <p>{text.conflict}</p>
      <VButton
        type="button"
        variant="secondary"
        isDisabled={!hasLatestSettings}
        onPress={discardDraft}
      >
        {hasLatestSettings ? text.loadLatest : text.waitingForLatest}
      </VButton>
    </div>
  );

  const footer = (
    <>
      <span className={styles.settingsFooterStatus} role="status">
        {!setting
          ? text.notLoaded
          : conflicted
            ? text.conflict
            : dirty
              ? text.unsaved
              : text.clean}
      </span>
      {saveError && !conflicted ? <span className={styles.settingsSaveError} role="alert">{saveError}</span> : null}
      {dirty && !conflicted ? (
        <VButton type="button" variant="secondary" isDisabled={saving || pending} onPress={discardDraft}>
          {text.discard}
        </VButton>
      ) : null}
      <VButton
        type="button"
        variant="primary"
        isDisabled={!dirty || controlsDisabled}
        isPending={saving}
        onPress={() => void saveDraft()}
      >
        {saving ? text.saving : copy.saveStartupSettings}
      </VButton>
    </>
  );

  if (standalone) {
    return (
      <VSettingsFormPage
        title={text.pageTitle}
        ariaLabel={copy.startupSettings}
        className={styles.standalonePage}
        headerClassName={styles.standaloneHeader}
        bodyClassName={styles.settingsPageBody}
        footer={footer}
      >
        <div className={styles.settingsPageContent}>
          {conflicted ? conflictMessage : null}
          {settingsRows}
        </div>
      </VSettingsFormPage>
    );
  }

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
          {conflicted ? conflictMessage : null}
          {settingsRows}
          <div className={styles.settingsCompactFooter}>
            {footer}
          </div>
        </div>
      </details>
    </div>
  );
}
