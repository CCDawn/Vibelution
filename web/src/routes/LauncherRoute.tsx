import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, LoaderCircle, Play, RefreshCw, Square } from "lucide-react";
import { useMemo, useState } from "react";

import {
  getLauncherStatus,
  reattachLauncherSupervisor,
  restartLauncherBundle,
  startLauncherBundle,
  stopLauncherBundle,
} from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import type { LauncherComponentState, LauncherOperation } from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./LauncherRoute.module.css";

type LauncherNotice = {
  tone: "neutral" | "success" | "warning" | "error";
  text: string;
};

type LauncherGuardianResponsibility = {
  id: string;
  owner: string;
  adapter: string;
  status: string;
  detail: string;
};

type LauncherControlPlaneCommand = {
  commandId: string;
  type: string;
  requestedBy: string;
  requestedAt: string;
  reason: string;
  source: string;
  noBrowser: boolean;
  stopManager: boolean;
};

type LauncherControlPlaneResult = {
  commandId: string;
  ok: boolean;
  completed: boolean;
  message: string;
  errorType: string;
  stateVersion: number;
};

type LauncherControlPlaneEvent = {
  type: string;
  at: string;
  commandId: string;
  ok: boolean | null;
  message: string;
};

type LauncherStatusWithGuardian = Awaited<ReturnType<typeof getLauncherStatus>> & {
  controlPlaneEvidence?: {
    schemaVersion: number;
    state: {
      stateVersion: number;
      runtimeState: string;
      managerPid: number;
      updatedAt: string;
      activeCommand: LauncherControlPlaneCommand;
    };
    queue: {
      pendingCount: number;
      processingCount: number;
      pending: LauncherControlPlaneCommand[];
      processing: LauncherControlPlaneCommand[];
    };
    results: {
      recent: LauncherControlPlaneResult[];
    };
    events: {
      recent: LauncherControlPlaneEvent[];
    };
  };
  guardianAdapter?: {
    schemaVersion: number;
    mode: string;
    targetMode: string;
    statusLine: string;
    ownedCount: number;
    adapterCount: number;
    supervisor?: {
      pid: number;
      alive: boolean;
      status: string;
      stdoutPath: string;
      stderrPath: string;
      runtimeSceneId: string;
      runtimeSceneDir: string;
      detail: string;
    };
    responsibilities: LauncherGuardianResponsibility[];
  };
};

const COMPONENT_ORDER = new Map([
  ["backend", 0],
  ["frontend", 1],
  ["browser", 2],
]);

function sortComponents(components: LauncherComponentState[]) {
  return [...components].sort((left, right) => {
    const leftOrder = COMPONENT_ORDER.get(left.id) ?? 99;
    const rightOrder = COMPONENT_ORDER.get(right.id) ?? 99;
    if (leftOrder !== rightOrder) {
      return leftOrder - rightOrder;
    }
    return left.id.localeCompare(right.id);
  });
}

function compactDate(value: string, locale: string) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function stateTone(state: string, ok = true) {
  const normalized = state.trim().toLowerCase();
  if (!ok || normalized.includes("fail") || normalized.includes("error") || normalized.includes("conflict")) {
    return "error";
  }
  if (normalized.includes("run") || normalized.includes("ready") || normalized.includes("ok") || normalized.includes("healthy")) {
    return "success";
  }
  if (normalized.includes("start") || normalized.includes("stop") || normalized.includes("queue") || normalized.includes("restart")) {
    return "warning";
  }
  return "neutral";
}

export function LauncherRoute() {
  const { lang } = useAppI18n();
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const copy = lang === "zh"
    ? {
        eyebrow: "Launcher",
        title: "项目启动器",
        subtitle: "统一控制前端、后端和浏览器生命周期",
        refresh: "刷新",
        start: "启动",
        stop: "停止",
        restart: "重启",
        open: "打开",
        bundle: "项目整体",
        controlPlane: "控制面",
        controlEvidence: "控制面证据",
        components: "组件",
        guardian: "守护归并",
        lastOperation: "最近动作",
        backend: "后端",
        frontend: "前端",
        browser: "浏览器",
        desired: "期望",
        observed: "观察",
        phase: "阶段",
        overall: "整体",
        adapter: "适配器",
        independent: "独立",
        nextPhase: "下一阶段",
        stable: "稳定控制面",
        pid: "PID",
        required: "必需",
        state: "状态",
        detail: "细节",
        responsibility: "职责",
        port: "端口",
        listening: "监听",
        owner: "占用 PID",
        dist: "dist",
        orphaned: "孤儿进程",
        managed: "受管",
        alive: "存活",
        healthy: "健康",
        yes: "是",
        no: "否",
        unavailable: "不可用",
        loadFailed: "Launcher 状态读取失败",
        loading: "正在读取 Launcher 状态",
        commandDone: "命令已提交",
        reattachSupervisor: "重新接管",
        targetMode: "目标模式",
        owned: "已纳入",
        legacyAdapter: "旧适配",
        supervisor: "Supervisor",
        stdout: "stdout",
        stderr: "stderr",
        scene: "现场",
        pending: "待执行",
        processing: "执行中",
        activeCommand: "当前命令",
        recentResults: "最近结果",
        recentEvents: "最近事件",
      }
    : {
        eyebrow: "Launcher",
        title: "Project Launcher",
        subtitle: "Control frontend, backend, and browser as one lifecycle bundle",
        refresh: "Refresh",
        start: "Start",
        stop: "Stop",
        restart: "Restart",
        open: "Open",
        bundle: "Project Bundle",
        controlPlane: "Control Plane",
        controlEvidence: "Control Evidence",
        components: "Components",
        guardian: "Guardian Merge",
        lastOperation: "Last Operation",
        backend: "Backend",
        frontend: "Frontend",
        browser: "Browser",
        desired: "Desired",
        observed: "Observed",
        phase: "Phase",
        overall: "Overall",
        adapter: "Adapter",
        independent: "Independent",
        nextPhase: "Next Phase",
        stable: "Stable Control Plane",
        pid: "PID",
        required: "Required",
        state: "State",
        detail: "Detail",
        responsibility: "Responsibility",
        port: "Port",
        listening: "Listening",
        owner: "Owner PID",
        dist: "dist",
        orphaned: "Orphaned",
        managed: "Managed",
        alive: "Alive",
        healthy: "Healthy",
        yes: "Yes",
        no: "No",
        unavailable: "Unavailable",
        loadFailed: "Launcher status failed",
        loading: "Loading Launcher status",
        commandDone: "Command submitted",
        reattachSupervisor: "Reattach",
        targetMode: "Target Mode",
        owned: "Owned",
        legacyAdapter: "Legacy Adapter",
        supervisor: "Supervisor",
        stdout: "stdout",
        stderr: "stderr",
        scene: "Scene",
        pending: "Pending",
        processing: "Processing",
        activeCommand: "Active Command",
        recentResults: "Recent Results",
        recentEvents: "Recent Events",
      };

  const [notice, setNotice] = useState<LauncherNotice>({ tone: "neutral", text: "" });
  const statusQuery = useQuery({
    queryKey: queryKeys.launcherStatus(),
    queryFn: getLauncherStatus,
    refetchInterval: resolvePollingInterval(pageVisible, 4_000),
    refetchIntervalInBackground: false,
  });
  const controlMutation = useMutation({
    mutationFn: async (operation: LauncherOperation) => {
      if (operation === "start") {
        return startLauncherBundle();
      }
      if (operation === "stop") {
        return stopLauncherBundle();
      }
      return restartLauncherBundle(false);
    },
    onSuccess: (response) => {
      setNotice({
        tone: response.accepted ? "success" : "warning",
        text: response.message || copy.commandDone,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });
  const supervisorMutation = useMutation({
    mutationFn: reattachLauncherSupervisor,
    onSuccess: (response) => {
      setNotice({
        tone: response.accepted ? "success" : "warning",
        text: response.message || copy.commandDone,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.launcherStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const status = statusQuery.data as LauncherStatusWithGuardian | undefined;
  const bundle = status?.projectBundle;
  const guardian = status?.guardianAdapter;
  const evidence = status?.controlPlaneEvidence;
  const componentRows = useMemo(() => sortComponents(bundle?.components ?? []), [bundle?.components]);
  const busy = controlMutation.isPending || supervisorMutation.isPending;
  const headerTone = stateTone(bundle?.overallState ?? status?.launcher.phase ?? "", Boolean(bundle));
  const transitionAt = compactDate(bundle?.lastOperation.transitionAt ?? "", locale);
  const canRequestSupervisorReattach = Boolean(status && guardian?.supervisor && !guardian.supervisor.alive);

  return (
    <section className={styles.route} aria-label={copy.title}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.subtitle}>{bundle?.statusLine || status?.launcher.message || copy.subtitle}</p>
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => void statusQuery.refetch()}
            disabled={statusQuery.isFetching}
            title={copy.refresh}
          >
            {statusQuery.isFetching ? <LoaderCircle size={15} className={styles.spin} /> : <RefreshCw size={15} />}
            <span>{copy.refresh}</span>
          </button>
          <button
            type="button"
            className={styles.primaryButton}
            onClick={() => controlMutation.mutate("start")}
            disabled={busy}
            title={copy.start}
          >
            <Play size={15} />
            <span>{copy.start}</span>
          </button>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => controlMutation.mutate("stop")}
            disabled={busy}
            title={copy.stop}
          >
            <Square size={15} />
            <span>{copy.stop}</span>
          </button>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => controlMutation.mutate("restart")}
            disabled={busy}
            title={copy.restart}
          >
            <RefreshCw size={15} />
            <span>{copy.restart}</span>
          </button>
          {bundle?.url ? (
            <a className={styles.secondaryButton} href={bundle.url} target="_blank" rel="noreferrer" title={copy.open}>
              <ExternalLink size={15} />
              <span>{copy.open}</span>
            </a>
          ) : null}
        </div>
      </header>

      <div className={styles.summaryStrip} data-tone={headerTone}>
        <Metric label={copy.desired} value={bundle?.desiredState || copy.unavailable} />
        <Metric label={copy.observed} value={bundle?.observedState || copy.unavailable} />
        <Metric label={copy.phase} value={bundle?.phase || status?.launcher.phase || copy.unavailable} />
        <Metric label={copy.overall} value={bundle?.overallState || copy.unavailable} />
      </div>

      {statusQuery.isError ? <p className={styles.notice} data-tone="error">{copy.loadFailed}</p> : null}
      {notice.text ? <p className={styles.notice} data-tone={notice.tone}>{notice.text}</p> : null}
      {statusQuery.isPending && !status ? <p className={styles.notice} data-tone="neutral">{copy.loading}</p> : null}

      <div className={styles.workspace}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.bundle}</p>
            <strong>{bundle?.id || "vibelution"}</strong>
          </div>
          <dl className={styles.specGrid}>
            <Spec label="schema" value={String(bundle?.schemaVersion ?? "-")} />
            <Spec label="mode" value={bundle?.mode || "-"} />
            <Spec label="url" value={bundle?.url || "-"} />
            <Spec label="reason" value={bundle?.lastReason || "-"} />
            <Spec label="failure" value={bundle?.failureMessage || "-"} />
          </dl>
        </section>

        <section className={`${styles.panel} ${styles.evidencePanel}`}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.controlEvidence}</p>
            <strong>{evidence?.state.runtimeState || "-"}</strong>
          </div>
          <dl className={styles.specGrid}>
            <Spec label="state" value={String(evidence?.state.stateVersion ?? "-")} />
            <Spec label="manager" value={String(evidence?.state.managerPid || "-")} />
            <Spec label={copy.pending} value={String(evidence?.queue.pendingCount ?? 0)} />
            <Spec label={copy.processing} value={String(evidence?.queue.processingCount ?? 0)} />
          </dl>
          <div className={styles.evidenceStack}>
            <EvidenceLine
              label={copy.activeCommand}
              primary={evidence?.state.activeCommand?.commandId || "-"}
              secondary={[evidence?.state.activeCommand?.type, evidence?.state.activeCommand?.requestedBy].filter(Boolean).join(" / ") || "-"}
            />
            <EvidenceList
              label={copy.recentResults}
              items={(evidence?.results.recent ?? []).slice(0, 3).map((item) => ({
                id: item.commandId,
                primary: item.commandId || "-",
                secondary: `${item.ok ? "ok" : "failed"} · ${item.message || item.errorType || "-"}`,
                tone: item.ok ? "success" : "error",
              }))}
            />
            <EvidenceList
              label={copy.recentEvents}
              items={(evidence?.events.recent ?? []).slice(0, 3).map((item) => ({
                id: `${item.at}-${item.type}-${item.commandId}`,
                primary: item.type || "-",
                secondary: [item.commandId, compactDate(item.at, locale)].filter(Boolean).join(" · ") || "-",
                tone: item.ok === false ? "error" : item.ok === true ? "success" : "neutral",
              }))}
            />
          </div>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.controlPlane}</p>
            <strong>{status?.launcher.mode || "-"}</strong>
          </div>
          <dl className={styles.specGrid}>
            <Spec label={copy.stable} value={status?.launcher.stableControlPlane ? copy.yes : copy.no} />
            <Spec label={copy.independent} value={status?.launcher.controlPlane.independent ? copy.yes : copy.no} />
            <Spec label={copy.adapter} value={status?.launcher.controlPlane.adapter || "-"} />
            <Spec label={copy.nextPhase} value={status?.launcher.controlPlane.nextPhase || "-"} />
          </dl>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.lastOperation}</p>
            <strong>{bundle?.lastOperation.reason || "-"}</strong>
          </div>
          <dl className={styles.specGrid}>
            <Spec label="source" value={bundle?.lastOperation.source || "-"} />
            <Spec label="transition" value={transitionAt} />
            <Spec label="manager" value={status?.runtimeManager.runtimeState || "-"} />
            <Spec label="proof" value={status?.lifecycleProof.overallLabel || "-"} />
          </dl>
        </section>

        <section className={`${styles.panel} ${styles.guardianPanel}`}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.guardian}</p>
            <strong>{guardian?.mode || "-"}</strong>
          </div>
          <div className={styles.guardianSummary}>
            <span>{guardian?.statusLine || "-"}</span>
            <strong>{copy.owned}: {guardian?.ownedCount ?? 0}</strong>
            <strong>{copy.legacyAdapter}: {guardian?.adapterCount ?? 0}</strong>
            <strong>{copy.targetMode}: {guardian?.targetMode || "-"}</strong>
          </div>
          <div className={styles.supervisorToolbar}>
            <span>{guardian?.supervisor?.detail || "-"}</span>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={() => supervisorMutation.mutate()}
              disabled={busy || !canRequestSupervisorReattach}
              title={copy.reattachSupervisor}
            >
              {supervisorMutation.isPending ? <LoaderCircle size={15} className={styles.spin} /> : <RefreshCw size={15} />}
              <span>{copy.reattachSupervisor}</span>
            </button>
          </div>
          <dl className={styles.supervisorGrid}>
            <Spec label={copy.supervisor} value={guardian?.supervisor?.status || "-"} />
            <Spec label={copy.pid} value={String(guardian?.supervisor?.pid || "-")} />
            <Spec label={copy.alive} value={guardian?.supervisor?.alive ? copy.yes : copy.no} />
            <Spec label={copy.scene} value={guardian?.supervisor?.runtimeSceneId || "-"} />
            <Spec label={copy.stdout} value={guardian?.supervisor?.stdoutPath || "-"} />
            <Spec label={copy.stderr} value={guardian?.supervisor?.stderrPath || "-"} />
          </dl>
          <div className={styles.guardianTable} role="table" aria-label={copy.guardian}>
            <div className={styles.guardianHead} role="row">
              <span role="columnheader">{copy.responsibility}</span>
              <span role="columnheader">owner</span>
              <span role="columnheader">{copy.adapter}</span>
              <span role="columnheader">{copy.state}</span>
              <span role="columnheader">{copy.detail}</span>
            </div>
            {(guardian?.responsibilities ?? []).map((item) => (
              <div key={item.id} className={styles.guardianRow} role="row" data-tone={stateTone(item.status)}>
                <span role="cell">
                  <strong>{item.id}</strong>
                </span>
                <span role="cell">{item.owner}</span>
                <span role="cell">{item.adapter}</span>
                <span role="cell">{item.status}</span>
                <span role="cell">{item.detail}</span>
              </div>
            ))}
          </div>
        </section>

        <section className={`${styles.panel} ${styles.componentPanel}`}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.components}</p>
            <strong>{componentRows.length}</strong>
          </div>
          <div className={styles.componentTable} role="table" aria-label={copy.components}>
            <div className={styles.componentHead} role="row">
              <span role="columnheader">{copy.state}</span>
              <span role="columnheader">{copy.pid}</span>
              <span role="columnheader">{copy.required}</span>
              <span role="columnheader">{copy.detail}</span>
            </div>
            {componentRows.map((component) => (
              <div key={component.id} className={styles.componentRow} role="row" data-tone={stateTone(component.state, component.ok)}>
                <span role="cell">
                  <strong>{component.id}</strong>
                  <small>{component.state}</small>
                </span>
                <span role="cell">{component.pid || "-"}</span>
                <span role="cell">{component.requiredForRunning ? copy.yes : copy.no}</span>
                <span role="cell">{component.detail || "-"}</span>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.backend}</p>
            <strong>{bundle?.backend.healthy ? copy.healthy : copy.unavailable}</strong>
          </div>
          <dl className={styles.specGrid}>
            <Spec label={copy.pid} value={String(bundle?.backend.pid || "-")} />
            <Spec label={copy.port} value={String(bundle?.backend.port || "-")} />
            <Spec label={copy.listening} value={bundle?.backend.portListening ? copy.yes : copy.no} />
            <Spec label={copy.owner} value={String(bundle?.backend.portOwnerPid || "-")} />
          </dl>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.frontend}</p>
            <strong>{bundle?.frontend.distReady ? "ready" : copy.unavailable}</strong>
          </div>
          <dl className={styles.specGrid}>
            <Spec label="mode" value={bundle?.frontend.mode || "-"} />
            <Spec label={copy.dist} value={bundle?.frontend.distReady ? copy.yes : copy.no} />
            <Spec label={copy.orphaned} value={bundle?.frontend.orphaned ? copy.yes : copy.no} />
          </dl>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.browser}</p>
            <strong>{bundle?.browser.alive ? copy.alive : copy.unavailable}</strong>
          </div>
          <dl className={styles.specGrid}>
            <Spec label={copy.managed} value={bundle?.browser.managed ? copy.yes : copy.no} />
            <Spec label={copy.pid} value={String(bundle?.browser.windowPid || "-")} />
            <Spec label={copy.alive} value={bundle?.browser.alive ? copy.yes : copy.no} />
          </dl>
        </section>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.metric}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function EvidenceLine({ label, primary, secondary }: { label: string; primary: string; secondary: string }) {
  return (
    <div className={styles.evidenceLine}>
      <span>{label}</span>
      <strong>{primary}</strong>
      <small>{secondary}</small>
    </div>
  );
}

function EvidenceList({
  label,
  items,
}: {
  label: string;
  items: Array<{ id: string; primary: string; secondary: string; tone: "neutral" | "success" | "error" }>;
}) {
  return (
    <div className={styles.evidenceList}>
      <span>{label}</span>
      {items.length ? items.map((item) => (
        <div key={item.id || item.primary} className={styles.evidenceItem} data-tone={item.tone}>
          <strong>{item.primary}</strong>
          <small>{item.secondary}</small>
        </div>
      )) : <small>-</small>}
    </div>
  );
}
