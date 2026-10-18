import { useQuery } from "@tanstack/react-query";

import { getLauncherStatus } from "../api/launcher";
import { queryKeys } from "../api/queryKeys";
import type { Language } from "./shellDictionary";

/** Launcher settings come from its local control plane, even without a workbench. */
export function useLauncherLanguage(): Language {
  const statusQuery = useQuery({
    queryKey: queryKeys.launcherStatus(),
    queryFn: getLauncherStatus,
  });

  return statusQuery.data?.settings?.startup?.interface.language === "en" ? "en" : "zh";
}
