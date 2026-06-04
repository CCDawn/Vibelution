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

type StatusRow = {
  id: string;
  label: string;
  status: string;
  pid: string;
  mode: string;
  detail: string;
  ok: boolean;
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

function boolText(value: boolean | undefined, yes: string, no: string) {
  return value ? yes : no;
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
        lifecycle: "生命周期",
        matrix: "生命周期矩阵",
        controlPlane: "控制面",
        controlEvidence: "证据",
        guardian: "守护归并",
        diagnostics: "诊断详情",
        activeCommand: "当前命令",
        recentResults: "最近结果",
        recentEvents: "最近事件",
        desired: "期望",
        observed: "观察",
        phase: "阶段",
        overall: "整体",
        adapter: "适配器",
        independent: "独立",
        nextPhase: "下一阶段",
        stable: "稳定控制面",
        pid: "PID",
        state: "状态",
        detail: "细节",
        unit: "单元",
        mode: "模式",
        port: "端口",
        listening: "监听",
        owner: "占用 PID",
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
        queue: "队列",
        reason: "原因",
        source: "来源",
        transition: "转换",
        proof: "证明",
        schema: "schema",
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
        lifecycle: "Lifecycle",
        matrix: "Lifecycle Matrix",
        controlPlane: "Control Plane",
        controlEvidence: "Evidence",
        guardian: "Guardian Merge",
        diagnostics: "Diagnostics",
        activeCommand: "Active Command",
        recentResults: "Recent Results",
        recentEvents: "Recent Events",
        desired: "Desired",
        observed: "Observed",
        phase: "Phase",
        overall: "Overall",
        adapter: "Adapter",
        independent: "Independent",
        nextPhase: "Next Phase",
        stable: "Stable Control Plane",
        pid: "PID",
        state: "State",
        detail: "Detail",
        unit: "Unit",
        mode: "Mode",
        port: "Port",
        listening: "Listening",
        owner: "Owner PID",
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
        queue: "Queue",
        reason: "Reason",
        source: "Source",
        transition: "Transition",
        proof: "Proof",
        schema: "schema",
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
  const statusRows = useMemo<StatusRow[]>(() => {
    const componentById = new Map(componentRows.map((component) => [component.id, component]));
    const backend = componentById.get("backend");
    const frontend = componentById.get("frontend");
    const browser = componentById.get("browser");
    return [
      {
        id: "project",
        label: bundle?.id || "vibelution-project",
        status: `${bundle?.desiredState || "-"} / ${bundle?.observedState || "-"}`,
        pid: "-",
        mode: bundle?.mode || "-",
        detail: bundle?.statusLine || status?.launcher.message || "-",
        ok: Boolean(bundle) && bundle?.overallState !== "failed",
      },
      {
        id: "backend",
        label: "backend",
        status: backend?.state || (bundle?.backend.healthy ? "healthy" : "-"),
        pid: String(bundle?.backend.pid || backend?.pid || "-"),
        mode: `${copy.port} ${bundle?.backend.port || "-"} · ${copy.owner} ${bundle?.backend.portOwnerPid || "-"}`,
        detail: `${copy.listening}: ${boolText(bundle?.backend.portListening, copy.yes, copy.no)} · ${copy.alive}: ${boolText(bundle?.backend.alive, copy.yes, copy.no)}`,
        ok: Boolean(backend?.ok ?? bundle?.backend.healthy),
      },
      {
        id: "frontend",
        label: "frontend",
        status: frontend?.state || (bundle?.frontend.distReady ? "ready" : "-"),
        pid: String(frontend?.pid || "-"),
        mode: bundle?.frontend.mode || "-",
        detail: `dist: ${boolText(bundle?.frontend.distReady, copy.yes, copy.no)} · orphaned: ${boolText(bundle?.frontend.orphaned, copy.yes, copy.no)}`,
        ok: Boolean(frontend?.ok ?? bundle?.frontend.distReady),
      },
      {
        id: "browser",
        label: "browser",
        status: browser?.state || (bundle?.browser.alive ? "alive" : "stopped"),
        pid: String(bundle?.browser.windowPid || browser?.pid || "-"),
        mode: `managed: ${boolText(bundle?.browser.managed, copy.yes, copy.no)}`,
        detail: browser?.detail || `${copy.alive}: ${boolText(bundle?.browser.alive, copy.yes, copy.no)}`,
        ok: Boolean(browser?.ok ?? !bundle?.browser.alive),
      },
      {
        id: "runtime_manager",
        label: "runtime_manager",
        status: status?.runtimeManager.runtimeState || "-",
        pid: String(status?.runtimeManager.managerPid || "-"),
        mode: `state ${status?.runtimeManager.stateVersion ?? "-"}`,
        detail: evidence?.state.updatedAt ? compactDate(evidence.state.updatedAt, locale) : "-",
        ok: Boolean(status?.runtimeManager.running),
      },
      {
        id: "supervisor",
        label: "supervisor",
        status: guardian?.supervisor?.status || "-",
        pid: String(guardian?.supervisor?.pid || "-"),
        mode: guardian?.mode || "-",
        detail: guardian?.supervisor?.detail || guardian?.statusLine || "-",
        ok: Boolean(guardian?.supervisor?.alive),
      },
    ];
  }, [bundle, componentRows, copy, evidence?.state.updatedAt, guardian, locale, status]);

  const activeCommand = evidence?.state.activeCommand;
  const recentResults = (evidence?.results.recent ?? []).slice(0, 3);
  const recentEvents = (evidence?.events.recent ?? []).slice(0, 3);

  return (
    <section className={styles.route} aria-label={copy.title}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.subtitle}>{bundle?.statusLine || status?.launcher.message || copy.subtitle}</p>
        </div>
        <div className={styles.actions}>
          <button type="button" className={styles.iconButton} onClick={() => void statusQuery.refetch()} disabled={statusQuery.isFetching} title={copy.refresh}>
            {statusQuery.isFetching ? <LoaderCircle size={15} className={styles.spin} /> : <RefreshCw size={15} />}
            <span>{copy.refresh}</span>
          </button>
          <button type="button" className={styles.primaryButton} onClick={() => controlMutation.mutate("start")} disabled={busy} title={copy.start}>
            <Play size={15} />
            <span>{copy.start}</span>
          </button>
          <button type="button" className={styles.iconButton} onClick={() => controlMutation.mutate("stop")} disabled={busy} title={copy.stop}>
            <Square size={15} />
            <span>{copy.stop}</span>
          </button>
          <button type="button" className={styles.iconButton} onClick={() => controlMutation.mutate("restart")} disabled={busy} title={copy.restart}>
            <RefreshCw size={15} />
            <span>{copy.restart}</span>
          </button>
          {bundle?.url ? (
            <a className={styles.iconButton} href={bundle.url} target="_blank" rel="noreferrer" title={copy.open}>
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
        <Metric label={copy.queue} value={`${evidence?.queue.pendingCount ?? 0}/${evidence?.queue.processingCount ?? 0}`} />
        <Metric label={copy.guardian} value={`${guardian?.ownedCount ?? 0}/${guardian?.adapterCount ?? 0}`} />
      </div>

      {statusQuery.isError ? <p className={styles.notice} data-tone="error">{copy.loadFailed}</p> : null}
      {notice.text ? <p className={styles.notice} data-tone={notice.tone}>{notice.text}</p> : null}
      {statusQuery.isPending && !status ? <p className={styles.notice} data-tone="neutral">{copy.loading}</p> : null}

      <div className={styles.workspace}>
        <section className={`${styles.panel} ${styles.matrixPanel}`}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.lifecycle}</p>
            <strong>{copy.matrix}</strong>
          </div>
          <div className={styles.statusTable} role="table" aria-label={copy.matrix}>
            <div className={styles.statusHead} role="row">
              <span role="columnheader">{copy.unit}</span>
              <span role="columnheader">{copy.state}</span>
              <span role="columnheader">{copy.pid}</span>
              <span role="columnheader">{copy.mode}</span>
              <span role="columnheader">{copy.detail}</span>
            </div>
            {statusRows.map((row) => (
              <div key={row.id} className={styles.statusRow} role="row" data-tone={stateTone(row.status, row.ok)}>
                <span role="cell"><strong>{row.label}</strong></span>
                <span role="cell">{row.status}</span>
                <span role="cell">{row.pid}</span>
                <span role="cell">{row.mode}</span>
                <span role="cell">{row.detail}</span>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.controlPlane}</p>
            <strong>{status?.launcher.mode || "-"}</strong>
          </div>
          <dl className={styles.specGrid}>
            <Spec label={copy.stable} value={boolText(status?.launcher.stableControlPlane, copy.yes, copy.no)} />
            <Spec label={copy.independent} value={boolText(status?.launcher.controlPlane.independent, copy.yes, copy.no)} />
            <Spec label={copy.adapter} value={status?.launcher.controlPlane.adapter || "-"} />
            <Spec label={copy.nextPhase} value={status?.launcher.controlPlane.nextPhase || "-"} />
            <Spec label={copy.reason} value={bundle?.lastOperation.reason || bundle?.lastReason || "-"} />
            <Spec label={copy.transition} value={transitionAt} />
          </dl>
        </section>

        <section className={styles.panel}>
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
          <div className={styles.commandLine}>
            <span>{copy.activeCommand}</span>
            <strong>{activeCommand?.commandId || "-"}</strong>
            <small>{[activeCommand?.type, activeCommand?.requestedBy, activeCommand?.reason].filter(Boolean).join(" · ") || "-"}</small>
          </div>
        </section>

        <section className={`${styles.panel} ${styles.activityPanel}`}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.recentResults}</p>
            <strong>{recentResults.length}</strong>
          </div>
          <CompactList
            items={recentResults.map((item) => ({
              id: item.commandId,
              primary: item.commandId || "-",
              secondary: `${item.ok ? "ok" : "failed"} · ${item.message || item.errorType || "-"}`,
              tone: item.ok ? "success" : "error",
            }))}
          />
        </section>

        <section className={`${styles.panel} ${styles.activityPanel}`}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.recentEvents}</p>
            <strong>{recentEvents.length}</strong>
          </div>
          <CompactList
            items={recentEvents.map((item) => ({
              id: `${item.at}-${item.type}-${item.commandId}`,
              primary: item.type || "-",
              secondary: [item.commandId, compactDate(item.at, locale)].filter(Boolean).join(" · ") || "-",
              tone: item.ok === false ? "error" : item.ok === true ? "success" : "neutral",
            }))}
          />
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
            <button type="button" className={styles.iconButton} onClick={() => supervisorMutation.mutate()} disabled={busy || !canRequestSupervisorReattach} title={copy.reattachSupervisor}>
              {supervisorMutation.isPending ? <LoaderCircle size={15} className={styles.spin} /> : <RefreshCw size={15} />}
              <span>{copy.reattachSupervisor}</span>
            </button>
          </div>
          <div className={styles.guardianTable} role="table" aria-label={copy.guardian}>
            <div className={styles.guardianHead} role="row">
              <span role="columnheader">{copy.unit}</span>
              <span role="columnheader">owner</span>
              <span role="columnheader">{copy.adapter}</span>
              <span role="columnheader">{copy.state}</span>
              <span role="columnheader">{copy.detail}</span>
            </div>
            {(guardian?.responsibilities ?? []).map((item) => (
              <div key={item.id} className={styles.guardianRow} role="row" data-tone={stateTone(item.status)}>
                <span role="cell"><strong>{item.id}</strong></span>
                <span role="cell">{item.owner}</span>
                <span role="cell">{item.adapter}</span>
                <span role="cell">{item.status}</span>
                <span role="cell">{item.detail}</span>
              </div>
            ))}
          </div>
        </section>

        <details className={`${styles.panel} ${styles.diagnosticsPanel}`}>
          <summary>
            <span>{copy.diagnostics}</span>
            <strong>{status?.lifecycleProof.overallLabel || "-"}</strong>
          </summary>
          <dl className={styles.diagnosticsGrid}>
            <Spec label={copy.schema} value={String(bundle?.schemaVersion ?? "-")} />
            <Spec label="bundle mode" value={bundle?.mode || "-"} />
            <Spec label="url" value={bundle?.url || "-"} />
            <Spec label={copy.source} value={bundle?.lastOperation.source || "-"} />
            <Spec label={copy.proof} value={status?.lifecycleProof.summary || "-"} />
            <Spec label={copy.supervisor} value={guardian?.supervisor?.status || "-"} />
            <Spec label={copy.scene} value={guardian?.supervisor?.runtimeSceneId || "-"} />
            <Spec label={copy.stdout} value={guardian?.supervisor?.stdoutPath || "-"} />
            <Spec label={copy.stderr} value={guardian?.supervisor?.stderrPath || "-"} />
          </dl>
        </details>
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

function CompactList({
  items,
}: {
  items: Array<{ id: string; primary: string; secondary: string; tone: "neutral" | "success" | "error" }>;
}) {
  return (
    <div className={styles.compactList}>
      {items.length ? items.map((item) => (
        <div key={item.id || item.primary} className={styles.compactItem} data-tone={item.tone}>
          <strong>{item.primary}</strong>
          <small>{item.secondary}</small>
        </div>
      )) : <small>-</small>}
    </div>
  );
}
