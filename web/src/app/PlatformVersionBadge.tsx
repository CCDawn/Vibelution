import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../api/client";

type PlatformVersionSnapshot = {
  currentVersion?: string;
};

export function PlatformVersionBadge() {
  const { data } = useQuery({
    queryKey: ["platform-version-badge"],
    queryFn: () => fetchJson<PlatformVersionSnapshot>("/api/platform-version"),
    staleTime: 60_000,
    retry: false,
  });

  const version = data?.currentVersion?.trim();
  if (!version) return null;

  return <span>{`v${version}`}</span>;
}
