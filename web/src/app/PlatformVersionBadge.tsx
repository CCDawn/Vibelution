import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import type { BackendHealth } from "../api/types";
import { describeServingBuild } from "./servingBuildLabel";
import { platformVersionBadgeStyles as styles } from "./PlatformVersionBadge.styles";

type PlatformVersionSnapshot = {
  currentVersion?: string;
  build?: number;
  progress?: { patchInMinor?: number };
  cadence?: { patchPerMinor?: number };
  unreleasedPending?: boolean;
};

type PlatformVersionBadgeProps = {
  /** Shell health poll; the badge never fetches health on its own. */
  health?: BackendHealth;
  lang?: string;
};

/**
 * The top bar states what this page is running, not only which version exists.
 *
 * "I restarted and nothing changed" and "the fix was never in this build" look
 * identical when the only visible signal is a version number, so the pinned
 * release, the backend start clock, and a restart/fallback marker are shown
 * next to it.
 */
export function PlatformVersionBadge({ health, lang = "zh" }: PlatformVersionBadgeProps = {}) {
  const { data } = useQuery({
    queryKey: ["platform-version-badge"],
    queryFn: () => fetchJson<PlatformVersionSnapshot>("/api/platform-version"),
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: false,
  });

  const version = data?.currentVersion?.trim();
  if (!version) return null;

  const build = data?.build ?? 0;
  const patch = data?.progress?.patchInMinor ?? 0;
  const perMinor = data?.cadence?.patchPerMinor ?? 5;
  const serving = describeServingBuild(health, lang);
  const en = lang === "en";

  return (
    <span
      className={styles.wrapper}
      title={[`v${version} · build ${build}`, serving.title].filter(Boolean).join(" · ")}
      data-serving-source={serving.source || "unknown"}
      data-serving-stale={serving.warning === "restart" ? "1" : "0"}
    >
      <span className={styles.version}>v{version}</span>
      <span className={styles.progress}>{patch}/{perMinor}</span>
      {serving.release ? (
        <span className={styles.serving} data-serving-release={serving.release}>
          {serving.release}
        </span>
      ) : null}
      {serving.startedAt ? <span className={styles.clock}>{serving.startedAt}</span> : null}
      {serving.warning ? (
        <span className={styles.warning} role="status">
          {serving.warning === "restart" ? (en ? "restart" : "待重启") : (en ? "legacy" : "旧产物")}
        </span>
      ) : null}
    </span>
  );
}
