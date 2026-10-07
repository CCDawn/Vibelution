import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { fetchGitStatus } from "../../api/git";
import { queryKeys } from "../../api/queryKeys";
import type { GitStatusFile } from "../../api/types";

const EMPTY_GIT_FILES: GitStatusFile[] = [];

export function normalizeGitRailPath(path: string) {
  return String(path || "").replace(/\\/g, "/").trim();
}

export function selectGitRailPath(paths: readonly string[], picked: string | null) {
  if (picked && paths.includes(picked)) {
    return picked;
  }
  return paths[0] ?? null;
}

/** Repository file list for the chat right column. Fetches only while that tab is open. */
export function useChatGitRail(enabled: boolean) {
  const query = useQuery({
    queryKey: queryKeys.gitStatus(),
    enabled,
    staleTime: 15_000,
    queryFn: ({ signal }) => fetchGitStatus({ limit: 200, signal }),
  });
  const [picked, setPicked] = useState<string | null>(null);
  const files = query.data?.available ? query.data.files : EMPTY_GIT_FILES;
  const listed = useMemo(() => {
    const paths: string[] = [];
    const detailByPath: Record<string, string> = {};
    const seen = new Set<string>();
    for (const file of files) {
      const path = normalizeGitRailPath(file.path);
      if (!path || seen.has(path)) {
        continue;
      }
      seen.add(path);
      paths.push(path);
      const detail = String(file.statusLabel || file.status || "").trim();
      if (detail) {
        detailByPath[path] = detail;
      }
    }
    return { paths, detailByPath };
  }, [files]);
  return {
    paths: listed.paths,
    selectedPath: selectGitRailPath(listed.paths, picked),
    detailByPath: listed.detailByPath,
    selectPath: setPicked,
    pending: enabled && query.isPending,
    unavailable: enabled && (query.isError || Boolean(query.data && !query.data.available)),
    error: query.error,
    errorText: String(query.data?.error || "").trim(),
    branch: String(query.data?.branch || "").trim(),
  };
}
