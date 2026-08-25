import "../design/route-css/workbench-secondary.tailwind.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import {
  getLauncherBranchInstances,
  getLauncherStatus,
  isLauncherControlPlaneNotReady,
  requestBranchInstanceLifecycle,
  saveLauncherWorkbenchWindowMode,
  updateLauncherStartupSettings,
} from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import type { LauncherOperation } from "../api/types";
import { useWorkbenchLifecycleActions } from "../app/useWorkbenchLifecycleActions";
import { VDenseOpsPage, VRouteLinkButton, VStateSurface } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import { LauncherBranchInstancesPanel } from "./LauncherBranchInstancesPanel";
import {
  acceptLifecycleIntent,
  lifecycleIntentRejectMessage,
  settleLifecycleIntentTable,
  type LifecycleIntentTable,
  type LifecycleRequestOutcome,
} from "./LauncherBranchInstancesPanel.model";
import { LauncherStartupSettingsPanel } from "./LauncherStartupSettingsPanel";
import { launcherRouteStyles as styles } from "./LauncherRoute.styles";

type BranchLifecycleRequest = {
  instanceId: string;
  operation: Extract<LauncherOperation, "start" | "stop" | "force-stop">;
  requestId: string;
  localRevision: number;
};

function startupCopy(lang: "zh" | "en") {
  return lang === "zh"
    ? {
        invalidPort: "端口必须是 1-65535 的整数",
        startupSettings: "启动设置",
        expandSettings: "展开编辑",
        collapseSettings: "收起设置",
        runtimeProfile: "运行档位",
        launcherControlPort: "Launcher 端口",
        launcherControlPortHint: "本页控制面端口，不是某个分支实例的端口。",
        backendPort: "默认后端",
        backendPortHint: "启动主项目时的工作台后端默认值。",
        frontendPort: "开发前端",
        frontendPortHint: "Vite 开发热更新端口。",
        portOverride: "端口被环境变量覆盖",
        effectiveValue: "生效",
        windowMode: "启动窗口",
        windowModeFullscreen: "全屏",
        windowModeWindowed: "窗口化",
        windowSize: "窗口尺寸",
        windowSizeAuto: "自动",
        windowSizeEnvOverride: "窗口尺寸被环境变量覆盖",
        interfaceLanguage: "界面语言",
        languageZh: "中文",
        languageEn: "英文",
        preflightDoctor: "启动前自检",
        requireVenv: "要求 .venv",
        saveStartupSettings: "保存启动设置",
        branchInstances: "分支实例管理与清理",
        branchInstancesHint: "在同一个面板中启动、关闭、强制停止或清理分支实例。",
        branchColumn: "分支",
        instanceState: "状态",
        instanceKind: "类型",
        instancePath: "路径",
        currentInstance: "当前 main",
        legacyCheckout: "旧目录",
        retiredCheckout: "退役",
        notCheckedOut: "未打开",
      }
    : {
        invalidPort: "Port must be an integer from 1 to 65535",
        startupSettings: "Startup settings",
        expandSettings: "Expand settings",
        collapseSettings: "Collapse settings",
        runtimeProfile: "Runtime profile",
        launcherControlPort: "Launcher port",
        launcherControlPortHint: "This is the Launcher control-plane port, not an instance port.",
        backendPort: "Default backend",
        backendPortHint: "Default workbench backend when starting the main project.",
        frontendPort: "Development frontend",
        frontendPortHint: "Vite development hot-reload port.",
        portOverride: "Port is overridden by an environment variable",
        effectiveValue: "Effective",
        windowMode: "Startup window",
        windowModeFullscreen: "Fullscreen",
        windowModeWindowed: "Windowed",
        windowSize: "Window size",
        windowSizeAuto: "Auto",
        windowSizeEnvOverride: "Window size is overridden by an environment variable",
        interfaceLanguage: "Interface language",
        languageZh: "Chinese",
        languageEn: "English",
        preflightDoctor: "Startup doctor",
        requireVenv: "Require .venv",
        saveStartupSettings: "Save startup settings",
        branchInstances: "Branch instances and cleanup",
        branchInstancesHint: "Start, stop, force-stop, or clean up branch instances in one panel.",
        branchColumn: "Branch",
        instanceState: "State",
        instanceKind: "Kind",
        instancePath: "Path",
        currentInstance: "Current main",
        legacyCheckout: "Legacy checkout",
        retiredCheckout: "Retired",
        notCheckedOut: "Not checked out",
      };
}

export function LauncherRoute() {
  const { lang } = useShellI18n({ configEnabled: false });
  const queryClient = useQueryClient();
  const { request: requestWorkbenchLifecycle } = useWorkbenchLifecycleActions("launcher_route");
  const [selectedInstanceId, setSelectedInstanceId] = useState("");
  const [notice, setNotice] = useState("");
  const [lifecycleIntents, setLifecycleIntents] = useState<LifecycleIntentTable>({});
  const lifecycleIntentsRef = useRef<LifecycleIntentTable>({});
  lifecycleIntentsRef.current = lifecycleIntents;
  const copy = startupCopy(lang);
  const uiLang = lang === "zh" ? "zh" : "en";

  const statusQuery = useQuery({
    queryKey: queryKeys.launcherStatus(),
    queryFn: getLauncherStatus,
  });
  const branchInstancesQuery = useQuery({
    queryKey: queryKeys.launcherBranchInstances(),
    queryFn: () => getLauncherBranchInstances(),
  });
  const refreshLauncherData = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.launcherBranchInstances() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
  };
  const lifecycleMutation = useMutation({
    mutationFn: async ({ instanceId, operation }: BranchLifecycleRequest) => {
      const instance = branchInstancesQuery.data?.items.find((item) => item.id === instanceId);
      return instance?.current
        ? requestWorkbenchLifecycle(operation)
        : requestBranchInstanceLifecycle(instanceId, operation, "launcher_route_panel");
    },
    onSuccess: (response, request) => {
      if (!response.accepted) {
        setLifecycleIntents((current) => {
          const next = { ...current };
          delete next[request.instanceId];
          lifecycleIntentsRef.current = next;
          return next;
        });
      }
      setNotice(response.message || (response.accepted ? (lang === "zh" ? "生命周期操作已提交。" : "Lifecycle operation submitted.") : (lang === "zh" ? "Launcher 拒绝了该操作。" : "Launcher rejected the operation.")));
      refreshLauncherData();
    },
    onError: (error, request) => {
      setLifecycleIntents((current) => {
        const next = { ...current };
        delete next[request.instanceId];
        lifecycleIntentsRef.current = next;
        return next;
      });
      setNotice(error instanceof Error ? error.message : String(error));
      refreshLauncherData();
    },
  });
  const startupSettingsMutation = useMutation({
    mutationFn: updateLauncherStartupSettings,
    onSuccess: (response) => {
      setNotice(response.message || (lang === "zh" ? "启动设置已保存。" : "Startup settings saved."));
      refreshLauncherData();
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : String(error)),
  });
  const windowModeMutation = useMutation({
    mutationFn: saveLauncherWorkbenchWindowMode,
    onSuccess: (response) => {
      setNotice(response.message || (lang === "zh" ? "启动窗口模式已保存。" : "Startup window mode saved."));
      refreshLauncherData();
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : String(error)),
  });

  const status = statusQuery.data;
  const controlPlaneStarting = statusQuery.isError && isLauncherControlPlaneNotReady(statusQuery.error);
  const setting = status?.settings?.startup;
  const configuredWindowMode = setting?.workbench.windowMode ?? status?.settings?.workbenchWindow?.mode ?? "fullscreen";
  const effectiveWindowMode = setting?.workbench.effectiveWindowMode ?? status?.settings?.workbenchWindow?.effectiveMode ?? configuredWindowMode;
  const branchItems = branchInstancesQuery.data?.items ?? [];
  useEffect(() => {
    setLifecycleIntents((current) => {
      const next = settleLifecycleIntentTable(current, branchItems);
      lifecycleIntentsRef.current = next;
      return next;
    });
  }, [branchItems]);
  const selectedId = branchItems.some((item) => item.id === selectedInstanceId)
    ? selectedInstanceId
    : branchInstancesQuery.data?.currentId || "main";
  const requestInstanceLifecycle = (
    instanceId: string,
    operation: Extract<LauncherOperation, "start" | "stop" | "force-stop">,
  ): LifecycleRequestOutcome => {
    const instance = branchItems.find((item) => item.id === instanceId);
    const requestId = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `lifecycle-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const intentOperation = operation === "force-stop" ? "stop" : operation;
    const accepted = acceptLifecycleIntent(lifecycleIntentsRef.current, {
      instanceId,
      operation: intentOperation,
      requestId,
      baselineLifecycleState: instance?.runtime.lifecycleState,
    });
    if (!accepted.accepted || !accepted.intent) {
      setNotice(lifecycleIntentRejectMessage(accepted.reason === "duplicate" ? "duplicate" : "blocked", lang === "zh", intentOperation));
      return { accepted: false, reason: accepted.reason === "duplicate" ? "duplicate" : "blocked" };
    }
    lifecycleIntentsRef.current = accepted.table;
    setLifecycleIntents(accepted.table);
    setSelectedInstanceId(instanceId);
    lifecycleMutation.mutate({
      instanceId,
      operation,
      requestId: accepted.intent.requestId,
      localRevision: accepted.intent.localRevision,
    });
    return { accepted: true };
  };

  return (
    <VDenseOpsPage
      className={styles.route}
      bodyClassName={styles.routeBody}
      fill
      hideHeader
      data-vui-domain-recipe="launcher-workbench"
      ariaLabel={lang === "zh" ? "项目启动器" : "Project launcher"}
    >
      <div className={styles.primaryRail} data-vui-region="launcher-primary-rail">
        <aside className={styles.settingsRail} data-vui-region="launcher-settings-rail" aria-label={copy.startupSettings}>
          <LauncherStartupSettingsPanel
            copy={copy}
            uiLang={uiLang}
            setting={setting}
            configuredWindowMode={configuredWindowMode}
            effectiveWindowModeLabel={effectiveWindowMode === "windowed" ? copy.windowModeWindowed : copy.windowModeFullscreen}
            windowModeDetail={lang === "zh" ? "下次启动或重启工作台生效" : "Takes effect when the workbench next starts or restarts"}
            controlPortOverride={setting?.launcher.controlPortEnvOverride || 0}
            backendPortOverride={setting?.workbench.backendPortEnvOverride || 0}
            frontendPortOverride={setting?.workbench.frontendPortEnvOverride || 0}
            pending={startupSettingsMutation.isPending || windowModeMutation.isPending}
            pendingWindowMode={windowModeMutation.isPending ? effectiveWindowMode : ""}
            onSave={(nextSetting) => startupSettingsMutation.mutate(nextSetting)}
            onWindowModeChange={(request) => windowModeMutation.mutate(request)}
          />
        </aside>
        <div className={styles.primaryColumn} data-vui-region="launcher-primary">
          <div className={styles.toolsLinkRow}>
            <VRouteLinkButton to="/launcher/tools" variant="ghost" density="compact">
              {lang === "zh" ? "工具与诊断" : "Tools and diagnostics"}
            </VRouteLinkButton>
          </div>
          <LauncherBranchInstancesPanel
            copy={copy}
            items={branchItems}
            selectedId={selectedId}
            onSelect={setSelectedInstanceId}
            launcherTitle={branchInstancesQuery.data?.currentLauncherTitle}
            launcherOnline={Boolean(status && !statusQuery.isError && !controlPlaneStarting)}
            launcherReading={statusQuery.isPending || controlPlaneStarting}
            listLoading={branchInstancesQuery.isPending || (branchInstancesQuery.isFetching && !branchInstancesQuery.data)}
            pendingOperation={lifecycleIntents}
            lifecyclePending={lifecycleMutation.isPending || controlPlaneStarting}
            onLifecycle={requestInstanceLifecycle}
            onStopMany={(instanceIds) => instanceIds.forEach((instanceId) => requestInstanceLifecycle(instanceId, "stop"))}
          />
        </div>
      </div>
      {notice ? <VStateSurface className={styles.notice} tone="info" title={notice} /> : null}
      {controlPlaneStarting ? <VStateSurface className={styles.notice} tone="loading" title={lang === "zh" ? "Launcher 正在启动控制面。" : "Launcher control plane is starting."} skeletonLines={2} /> : null}
      {statusQuery.isError && !controlPlaneStarting ? <VStateSurface className={styles.notice} tone="error" title={lang === "zh" ? "Launcher 状态读取失败" : "Launcher status could not be read"} /> : null}
    </VDenseOpsPage>
  );
}
