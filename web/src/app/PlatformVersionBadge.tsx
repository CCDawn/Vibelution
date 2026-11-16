import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import { VButton } from "../components/vui/primitives/VButton";
import { VPopover } from "../components/vui/primitives/VPopover";
import { platformVersionBadgeStyles as styles } from "./PlatformVersionBadge.styles";

type PlatformVersionEntry = {
  version: string;
  build: number;
};

type PlatformVersionSnapshot = {
  currentVersion: string;
  build: number;
  cadence: { patchPerMinor: number; minorPerMajor: number };
  progress: { patchInMinor: number; minorInMajor: number };
  fileVersion: string;
  fileBehind: boolean;
  unreleasedPending: boolean;
  unreleasedSummary: string;
  entries: PlatformVersionEntry[];
};

export function PlatformVersionBadge() {
  const { data } = useQuery({
    queryKey: ["platform-version-badge"],
    queryFn: () => fetchJson<PlatformVersionSnapshot>("/api/platform-version"),
    staleTime: 20_000,
    refetchInterval: 30_000,
    retry: false,
  });

  if (!data) return null;

  const patchCap = data.cadence?.patchPerMinor ?? 5;
  const minorCap = data.cadence?.minorPerMajor ?? 10;
  const patchInMinor = data.progress?.patchInMinor ?? 0;
  const minorInMajor = data.progress?.minorInMajor ?? 0;
  const recent = (data.entries ?? []).slice(0, 3);

  return (
    <VPopover
      align="end"
      side="bottom"
      sideOffset={8}
      aria-label="平台版本"
      contentClassName={styles.panel}
      trigger={
        <VButton
          variant="ghost"
          contentLayout="plain"
          className={styles.trigger}
          aria-label="平台版本"
        >
          {`v${data.currentVersion}`}
        </VButton>
      }
    >
      <div className={styles.head}>
        <span className={styles.version}>{`v${data.currentVersion}`}</span>
        <span className={styles.build}>{`build ${data.build}`}</span>
      </div>
      <div className={styles.progressRow}>
        <span>小版本</span>
        <span>{`${patchInMinor}/${patchCap}`}</span>
      </div>
      <div className={styles.bar}>
        <div
          className={styles.barFill}
          style={{ width: `${Math.min(100, (patchInMinor / patchCap) * 100)}%` }}
        />
      </div>
      <div className={styles.progressRow}>
        <span>中版本</span>
        <span>{`${minorInMajor}/${minorCap}`}</span>
      </div>
      <div className={styles.bar}>
        <div
          className={styles.barFill}
          style={{ width: `${Math.min(100, (minorInMajor / minorCap) * 100)}%` }}
        />
      </div>
      {data.unreleasedPending ? (
        <div className={styles.pending}>
          {`待结算：${data.unreleasedSummary || "有未结算的变更"}`}
        </div>
      ) : null}
      {recent.length ? (
        <div className={styles.list}>
          {recent.map((entry) => (
            <div key={`${entry.version}-${entry.build}`} className={styles.item}>
              <span className={styles.itemVersion}>{`v${entry.version}`}</span>
              <span className={styles.itemMeta}>{`build ${entry.build}`}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className={styles.empty}>暂无结算记录</div>
      )}
    </VPopover>
  );
}
