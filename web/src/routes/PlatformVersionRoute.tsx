import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  fetchPlatformVersionSnapshot,
  resolvePlatformVersionLanguage,
  subscribePlatformVersionEvents,
  type PlatformVersionSnapshot,
} from "../api/platformVersion";
import { VButton, VDenseRow, VDenseToolbar, VMetricChip, VPanel } from "../components/vui";
import { platformVersionStyles as styles } from "./PlatformVersionRoute.styles";

const COPY = {
  zh: {
    title: "平台演进版本",
    subtitle: "本地演进节奏，不参与打包或发布。",
    live: "实时",
    refresh: "刷新",
    current: "当前版本",
    build: "Build",
    patchProgress: "小版本进度",
    minorProgress: "中版本进度",
    anchor: "文件锚点",
    anchorLag: "投影落后于账本",
    anchorAligned: "投影与账本一致",
    pending: "Unreleased 待结算",
    pendingHint: "合入 main 后自动升号",
    idle: "暂无待结算变更",
    history: "结算记录",
    empty: "账本尚未初始化。",
    seq: "序号",
    version: "版本",
    kind: "类型",
    summary: "变更",
    time: "时间",
    error: "观察器异常",
    loading: "读取中",
    cadence: "进位规则",
  },
  en: {
    title: "Platform evolution version",
    subtitle: "A local cadence. It never participates in packaging or release.",
    live: "Live",
    refresh: "Refresh",
    current: "Current version",
    build: "Build",
    patchProgress: "Small-version progress",
    minorProgress: "Middle-version progress",
    anchor: "File anchor",
    anchorLag: "Projection lags the ledger",
    anchorAligned: "Projection matches the ledger",
    pending: "Unreleased pending",
    pendingHint: "Settles automatically after main advances",
    idle: "Nothing pending",
    history: "Settled records",
    empty: "The ledger is not initialised yet.",
    seq: "Seq",
    version: "Version",
    kind: "Kind",
    summary: "Change",
    time: "Time",
    error: "Watcher error",
    loading: "Loading",
    cadence: "Carry rule",
  },
} as const;

function kindLabel(kind: string, lang: "zh" | "en"): string {
  const labels: Record<string, { zh: string; en: string }> = {
    baseline: { zh: "基线", en: "baseline" },
    feature: { zh: "新增", en: "feature" },
    fix: { zh: "修复", en: "fix" },
    breaking: { zh: "破坏性", en: "breaking" },
  };
  return labels[kind]?.[lang] ?? kind;
}

export function PlatformVersionRoute() {
  const lang = resolvePlatformVersionLanguage();
  const copy = COPY[lang];
  const query = useQuery({
    queryKey: ["platform-version"],
    queryFn: fetchPlatformVersionSnapshot,
    staleTime: 0,
  });
  const [live, setLive] = useState<PlatformVersionSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const refetchRef = useRef(query.refetch);
  refetchRef.current = query.refetch;

  useEffect(() => {
    const unsubscribe = subscribePlatformVersionEvents((frame) => {
      if (frame.type === "version.snapshot" && frame.snapshot) {
        setLive(frame.snapshot);
        setConnected(true);
        return;
      }
      if (frame.type === "version.settled") {
        void refetchRef.current();
        return;
      }
      if (frame.type === "version.ping") {
        setConnected(true);
      }
    });
    return () => {
      unsubscribe();
      setConnected(false);
    };
  }, []);

  const data = live ?? query.data;
  const cadence = data?.cadence;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerText}>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>
        <div className={styles.headerActions}>
          <span className={styles.liveLabel}>{connected ? copy.live : copy.loading}</span>
          <VButton type="button" onClick={() => void query.refetch()}>
            {copy.refresh}
          </VButton>
        </div>
      </header>

      <VPanel ariaLabel={copy.current} className={styles.panel}>
        <VDenseToolbar ariaLabel={copy.current}>
          <VMetricChip label={copy.current} value={data?.currentVersion ?? "—"} />
          <VMetricChip label={copy.build} value={data ? `#${data.build}` : "—"} />
          <VMetricChip
            label={copy.patchProgress}
            value={data && cadence ? `${data.progress.patchInMinor}/${cadence.patchPerMinor}` : "—"}
          />
          <VMetricChip
            label={copy.minorProgress}
            value={data && cadence ? `${data.progress.minorInMajor}/${cadence.minorPerMajor}` : "—"}
          />
        </VDenseToolbar>
        <VDenseRow>
          <div className={styles.rowBetween}>
            <span className={styles.rowMuted}>
              {copy.anchor}: {data?.fileVersion || "—"}
              {" · "}
              {data?.fileBehind ? copy.anchorLag : copy.anchorAligned}
            </span>
            <span className={styles.rowMuted}>
              {data?.unreleasedPending ? `${copy.pending}: ${data.unreleasedSummary}` : copy.idle}
            </span>
          </div>
        </VDenseRow>
        {data && cadence ? (
          <p className={styles.cadenceNote}>
            {copy.cadence}: {cadence.patchPerMinor} × PATCH → MINOR · {cadence.minorPerMajor} × MINOR → MAJOR
          </p>
        ) : null}
        {data?.lastError ? (
          <p className={styles.errorNote}>
            {copy.error}: {data.lastError}
          </p>
        ) : null}
      </VPanel>

      <VPanel ariaLabel={copy.history} className={styles.historyPanel}>
        <h2 className={styles.sectionTitle}>{copy.history}</h2>
        {data && data.entries.length > 0 ? (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead className={styles.thead}>
                <tr>
                  <th className={styles.thSeq}>{copy.seq}</th>
                  <th className={styles.thVersion}>{copy.version}</th>
                  <th className={styles.thKind}>{copy.kind}</th>
                  <th className={styles.thSummary}>{copy.summary}</th>
                  <th className={styles.thTime}>{copy.time}</th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry) => (
                  <tr key={`${entry.seq}-${entry.version}`} className={styles.tr}>
                    <td className={styles.tdMuted}>{entry.seq}</td>
                    <td className={styles.tdVersion}>
                      {entry.version}
                      <span className={styles.buildBadge}>#{entry.build}</span>
                    </td>
                    <td className={styles.tdMuted}>{kindLabel(entry.kind, lang)}</td>
                    <td className={styles.tdMuted}>
                      <span className={styles.summaryCell}>{entry.summary || entry.head_subject}</span>
                    </td>
                    <td className={styles.tdMuted}>{entry.recorded_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className={styles.empty}>{query.isLoading ? copy.loading : copy.empty}</p>
        )}
      </VPanel>
    </div>
  );
}
