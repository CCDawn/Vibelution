import { useQuery } from "@tanstack/react-query";

import { fetchFileContent } from "../../api/files";
import { fetchGitFileDiff } from "../../api/git";
import { queryKeys } from "../../api/queryKeys";

/** Diff first. File preview is only fetched when this path has no text diff. */
export function useChatChangePreview(path: string | null) {
  const diffQuery = useQuery({
    queryKey: queryKeys.gitDiff(path ?? ""),
    enabled: Boolean(path),
    queryFn: ({ signal }) => fetchGitFileDiff(path ?? "", { signal }),
  });
  const hasDiff = Boolean(
    diffQuery.data?.available
    && (diffQuery.data.diff.trim() || diffQuery.data.binary),
  );
  const fileQuery = useQuery({
    queryKey: queryKeys.fileContent(path ?? ""),
    enabled: Boolean(path) && diffQuery.isFetched && !hasDiff,
    queryFn: () => fetchFileContent(path ?? ""),
  });
  return {
    diff: diffQuery.data,
    diffLoading: Boolean(path) && diffQuery.isLoading,
    hasDiff,
    file: fileQuery.data,
    fileLoading: fileQuery.isLoading,
    fileError: fileQuery.error,
  };
}
