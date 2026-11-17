import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import { platformVersionBadgeStyles as styles } from "./PlatformVersionBadge.styles";

type PlatformVersionSnapshot = {
  currentVersion?: string;
  build?: number;
  progress?: { patchInMinor?: number };
  cadence?: { patchPerMinor?: number };
  unreleasedPending?: boolean;
};

export function PlatformVersionBadge() {
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

  return (
    <span className={styles.wrapper} title={`v${version} · build ${build}`}>
      <span className={styles.version}>v{version}</span>
      <span className={styles.progress}>{patch}/{perMinor}</span>
    </span>
  );
}
