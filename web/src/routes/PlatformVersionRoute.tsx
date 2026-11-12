import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { detectUiLanguage } from "../api/client";
import {
  fetchPlatformVersionSnapshot,
  subscribePlatformVersionEvents,
  type PlatformVersionSnapshot,
} from "../api/platformVersion";
import { VButton, VDenseRow, VDenseToolbar, VMetricChip, VPanel } from "../components/vui";

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
  const lang = detectUiLanguage();
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
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-4 text-vui-fg">
      <header className="flex min-w-0 flex-wrap items-end justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h1 className="text-[length:var(--vui-font-xl)] font-semibold leading-tight">{copy.title}</h1>
          <p className="text-[length:var(--vui-font-sm)] text-vui-fg-secondary">{copy.subtitle}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--vui-font-xs)] text-vui-fg-secondary">
            {connected ? copy.live : copy.loading}
          </span>
          <VButton type="button" onClick={() => void query.refetch()}>
            {copy.refresh}
          </VButton>
        </div>
      </header>

      <VPanel ariaLabel={copy.current} className="flex flex-col gap-2 p-3">
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
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <span className="min-w-0">
              {copy.anchor}: <strong className="font-medium">{data?.fileVersion || "—"}</strong>
              <span className="ml-2">
                {data?.fileBehind ? copy.anchorLag : copy.anchorAligned}
              </span>
            </span>
            <span className="min-w-0 truncate text-[length:var(--vui-font-xs)] text-vui-fg-secondary">
              {data?.unreleasedPending ? `${copy.pending}: ${data.unreleasedSummary}` : copy.idle}
            </span>
          </div>
        </VDenseRow>
        {data && cadence ? (
          <p className="text-[length:var(--vui-font-xs)] text-vui-fg-secondary">
            {copy.cadence}: {cadence.patchPerMinor} × PATCH → MINOR · {cadence.minorPerMajor} × MINOR → MAJOR
          </p>
        ) : null}
        {data?.lastError ? (
          <p className="text-[length:var(--vui-font-xs)] text-[var(--state-error)]">
            {copy.error}: {data.lastError}
          </p>
        ) : null}
      </VPanel>

      <VPanel ariaLabel={copy.history} className="flex min-h-0 flex-1 flex-col gap-2 p-3">
        <h2 className="text-[length:var(--vui-font-md)] font-medium">{copy.history}</h2>
        {data && data.entries.length > 0 ? (
          <div className="min-h-0 overflow-auto">
            <table className="w-full table-fixed border-collapse text-left text-[length:var(--vui-font-sm)]">
              <thead className="text-vui-fg-secondary">
                <tr>
                  <th className="w-14 px-2 py-1 font-medium">{copy.seq}</th>
                  <th className="w-24 px-2 py-1 font-medium">{copy.version}</th>
                  <th className="w-24 px-2 py-1 font-medium">{copy.kind}</th>
                  <th className="px-2 py-1 font-medium">{copy.summary}</th>
                  <th className="w-40 px-2 py-1 font-medium">{copy.time}</th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry) => (
                  <tr key={`${entry.seq}-${entry.version}`} className="border-t border-vui-border-subtle">
                    <td className="px-2 py-1 text-vui-fg-secondary">{entry.seq}</td>
                    <td className="px-2 py-1 font-medium">
                      {entry.version}
                      <span className="ml-1 text-[length:var(--vui-font-xs)] text-vui-fg-secondary">
                        #{entry.build}
                      </span>
                    </td>
                    <td className="px-2 py-1 text-vui-fg-secondary">{kindLabel(entry.kind, lang)}</td>
                    <td className="px-2 py-1">
                      <span className="line-clamp-2">{entry.summary || entry.head_subject}</span>
                    </td>
                    <td className="px-2 py-1 text-vui-fg-secondary">{entry.recorded_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[length:var(--vui-font-sm)] text-vui-fg-secondary">
            {query.isLoading ? copy.loading : copy.empty}
          </p>
        )}
      </VPanel>
    </div>
  );
}
