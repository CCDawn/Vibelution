import "../design/route-css/workbench-secondary.tailwind.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useBlocker, useSearchParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";

import {
  getLauncherBranchInstances,
  getLauncherStatus,
  isLauncherControlPlaneNotReady,
  requestBranchInstanceLifecycle,
  updateLauncherStartupSettings,
} from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import type { LauncherOperation } from "../api/types";
import { useWorkbenchLifecycleActions } from "../app/useWorkbenchLifecycleActions";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VButton, VConfirmDialog, VDenseOpsPage, VStateSurface } from "../components/vui";
import { useStableBeforeUnload } from "../app/useStableBeforeUnload";
import { useShellI18n } from "../i18n/useShellI18n";
import { LauncherBranchInstancesPanel } from "./LauncherBranchInstancesPanel";
import {
  acceptLifecycleIntent,
  lifecycleIntentRejectMessage,
  shouldApplyLifecycleMutationFeedback,
  settleLifecycleIntentTable,
  type LifecycleIntentTable,
  type LifecycleRequestOutcome,
} from "./LauncherBranchInstancesPanel.model";
import { LauncherStartupSettingsPanel } from "./LauncherStartupSettingsPanel";
import { launcherRouteStyles as styles } from "./LauncherRoute.styles";

const LAUNCHER_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.launcher;

type BranchLifecycleRequest = {
  instanceId: string;
  operation: Extract<LauncherOperation, "start" | "stop" | "force-stop">;
  requestId: string;
  localRevision: number;
};

function startupCopy(lang: "zh" | "en") {
  return lang === "zh"
    ? {
        startupSettings: "启动设置",
        expandSettings: "展开编辑",
        collapseSettings: "收起设置",
        runtimeProfile: "运行档位",
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
        startupSettings: "Startup settings",
        expandSettings: "Expand settings",
        collapseSettings: "Collapse settings",
        runtimeProfile: "Runtime profile",
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
  const [searchParams] = useSearchParams();
  const settingsVisible = searchParams.get("view") === "settings";
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [settingsResetKey, setSettingsResetKey] = useState(0);
  const leaveBlocker = useBlocker(({ currentLocation, nextLocation }) => settingsDirty &&
    `${currentLocation.pathname}${currentLocation.search}` !== `${nextLocation.pathname}${nextLocation.search}`);
  useStableBeforeUnload((event) => {
    if (settingsDirty) { event.preventDefault(); event.returnValue = ""; }
  });
  const { lang } = useShellI18n({ configEnabled: false });
  const queryClient = useQueryClient();
  const { request: requestWorkbenchLifecycle } = useWorkbenchLifecycleActions("launcher_route");
  const [selectedInstanceId, setSelectedInstanceId] = useState("");
  const [notice, setNotice] = useState("");
  const [noticeTone, setNoticeTone] = useState<"info" | "error">("info");
  const [rowFeedback, setRowFeedback] = useState<{
    instanceId: string;
    tone: "error" | "info";
    message: string;
  } | null>(null);
  const showNotice = (text: string, tone: "info" | "error" = "info") => {
    setNotice(text);
    setNoticeTone(tone);
  };
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
      if (!shouldApplyLifecycleMutationFeedback(lifecycleIntentsRef.current, request)) {
        refreshLauncherData();
        return;
      }
      if (!response.accepted) {
        setLifecycleIntents((current) => {
          const next = { ...current };
          delete next[request.instanceId];
          lifecycleIntentsRef.current = next;
          return next;
        });
      }
      const fallback = response.accepted
        ? (lang === "zh" ? "生命周期操作已提交。" : "Lifecycle operation submitted.")
        : (lang === "zh" ? "Launcher 拒绝了该操作。" : "Launcher rejected the operation.");
      const message = response.message || fallback;
      // A refusal must stay visible on the row it belongs to: name the branch
      // and flag the notice as an error instead of a neutral status line.
      setRowFeedback(
        response.accepted
          ? response.shellStale
            ? {
                instanceId: request.instanceId,
                tone: "info",
                message: lang === "zh"
                  ? "桌面壳仍是旧版本，刷新桌面壳后才会换上桌面代码。"
                  : "The desktop shell is still an older build. Refresh the shell to pick up desktop code.",
              }
            : null
          : {
              instanceId: request.instanceId,
              tone: "error",
              message,
            },
      );
      showNotice(
        response.accepted ? message : withBranchLabel(request.instanceId, message),
        response.accepted ? "info" : "error",
      );
      refreshLauncherData();
    },
    onError: (error, request) => {
      if (!shouldApplyLifecycleMutationFeedback(lifecycleIntentsRef.current, request)) {
        refreshLauncherData();
        return;
      }
      setLifecycleIntents((current) => {
        const next = { ...current };
        delete next[request.instanceId];
        lifecycleIntentsRef.current = next;
        return next;
      });
      const errorMessage = error instanceof Error ? error.message : String(error);
      setRowFeedback({
        instanceId: request.instanceId,
        tone: "error",
        message: errorMessage,
      });
      showNotice(
        withBranchLabel(request.instanceId, errorMessage),
        "error",
      );
      refreshLauncherData();
    },
  });
  const startupSettingsMutation = useMutation({
    mutationFn: async (next: Parameters<typeof updateLauncherStartupSettings>[0]) => {
      const response = await updateLauncherStartupSettings(next);
      if (!response.ok) throw new Error(response.message || "Startup settings were not saved");
      return response;
    },
    onSuccess: (response) => {
      showNotice(response.message || (lang === "zh" ? "启动设置已保存。" : "Startup settings saved."));
      refreshLauncherData();
    },
    onError: (error) => {
      showNotice(error instanceof Error ? error.message : String(error), "error");
      void statusQuery.refetch();
    },
  });

  const status = statusQuery.data;
  const controlPlaneStarting = statusQuery.isError && isLauncherControlPlaneNotReady(statusQuery.error);
  const setting = status?.settings?.startup;
  const configuredWindowMode = setting?.workbench.windowMode ?? status?.settings?.workbenchWindow?.mode ?? "fullscreen";
  const effectiveWindowMode = setting?.workbench.effectiveWindowMode ?? status?.settings?.workbenchWindow?.effectiveMode ?? configuredWindowMode;
  const branchItems = branchInstancesQuery.data?.items ?? [];
  const withBranchLabel = (instanceId: string, message: string) => {
    const instance = branchItems.find((item) => item.id === instanceId);
    const label = instance?.shortName || instance?.branch || instanceId;
    return `${label}${lang === "zh" ? "：" : ": "}${message}`;
  };
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
      showNotice(
        withBranchLabel(instanceId, lifecycleIntentRejectMessage(accepted.reason === "duplicate" ? "duplicate" : "blocked", lang === "zh", intentOperation)),
        "error",
      );
      return { accepted: false, reason: accepted.reason === "duplicate" ? "duplicate" : "blocked" };
    }
    lifecycleIntentsRef.current = accepted.table;
    setLifecycleIntents(accepted.table);
    setSelectedInstanceId(instanceId);
    setRowFeedback((current) => (current?.instanceId === instanceId ? null : current));
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
      data-vui-recipe="launcher-workbench"
      data-vui-layout-id={LAUNCHER_LAYOUT_ID}
      ariaLabel={lang === "zh" ? "项目启动器" : "Project launcher"}
    >
      <div className="flex min-h-0 flex-1 flex-col" data-vui-region="launcher-primary-rail">
        <div hidden={!settingsVisible} className="flex h-full min-h-0 flex-col overflow-hidden px-7 py-4 max-[640px]:px-4" data-vui-region="launcher-settings-rail" aria-label={copy.startupSettings}>
          <h1 className="mb-1 mt-0 shrink-0 text-xl font-semibold">{lang === "zh" ? "设置" : "Settings"}</h1>
          <p className="mb-5 mt-1 shrink-0 text-vui-xs text-vui-fg-secondary">{lang === "zh" ? "管理启动行为和窗口偏好。" : "Manage startup behavior and window preferences."}</p>
          <LauncherStartupSettingsPanel
            key={settingsResetKey}
            standalone
            onDirtyChange={setSettingsDirty}
            copy={copy}
            uiLang={uiLang}
            setting={setting}
            configuredWindowMode={configuredWindowMode}
            effectiveWindowModeLabel={effectiveWindowMode === "windowed" ? copy.windowModeWindowed : copy.windowModeFullscreen}
            windowModeDetail={lang === "zh" ? "下次启动或重启工作台生效" : "Takes effect when the workbench next starts or restarts"}
            pending={startupSettingsMutation.isPending}
            pendingWindowMode=""
            onSave={async (nextSetting) => (await startupSettingsMutation.mutateAsync(nextSetting)).setting}
          />
        </div>
        <div hidden={settingsVisible} className="h-full min-h-0" data-vui-region="launcher-primary">
          <LauncherBranchInstancesPanel
            copy={copy}
            headerAction={(
              <VButton variant="ghost" isIconOnly aria-label={lang === "zh" ? "刷新工作区列表" : "Refresh workspaces"} isPending={branchInstancesQuery.isFetching} onPress={refreshLauncherData} icon={<RefreshCw size={15} />} />
            )}
            items={branchItems}
            selectedId={selectedId}
            onSelect={setSelectedInstanceId}
            launcherTitle={branchInstancesQuery.data?.currentLauncherTitle}
            launcherOnline={Boolean(status && !statusQuery.isError && !controlPlaneStarting)}
            launcherReading={statusQuery.isPending || controlPlaneStarting}
            listLoading={branchInstancesQuery.isPending || (branchInstancesQuery.isFetching && !branchInstancesQuery.data)}
            listError={branchInstancesQuery.isError ? (lang === "zh" ? "工作区读取失败，请刷新重试。" : "Workspaces could not be loaded. Please refresh.") : undefined}
            pendingOperation={lifecycleIntents}
            lifecyclePending={lifecycleMutation.isPending || controlPlaneStarting}
            onLifecycle={requestInstanceLifecycle}
            onStopMany={(instanceIds) => instanceIds.forEach((instanceId) => requestInstanceLifecycle(instanceId, "stop"))}
            rowFeedback={rowFeedback}
          />
        </div>
      </div>
      {notice ? <VStateSurface className={styles.notice} tone={noticeTone} title={notice} /> : null}
      {controlPlaneStarting ? <VStateSurface className={styles.notice} tone="loading" title={lang === "zh" ? "Launcher 正在启动控制面。" : "Launcher control plane is starting."} skeletonLines={2} /> : null}
      {statusQuery.isError && !controlPlaneStarting ? <VStateSurface className={styles.notice} tone="error" title={lang === "zh" ? "Launcher 状态读取失败" : "Launcher status could not be read"} /> : null}
      <VConfirmDialog open={leaveBlocker.state === "blocked"} onOpenChange={(open) => { if (!open && leaveBlocker.state === "blocked") leaveBlocker.reset(); }}
        title={lang === "zh" ? "还有未保存的设置" : "Unsaved settings"}
        description={lang === "zh" ? "离开设置前请先保存。直接离开将放弃本次修改。" : "Save before leaving, or discard these changes."}
        confirmLabel={lang === "zh" ? "放弃并离开" : "Discard and leave"} cancelLabel={lang === "zh" ? "继续编辑" : "Keep editing"}
        onConfirm={() => { if (leaveBlocker.state === "blocked") { setSettingsDirty(false); setSettingsResetKey((value) => value + 1); leaveBlocker.proceed(); } }} />
    </VDenseOpsPage>
  );
}
