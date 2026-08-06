import { useCallback, useMemo } from "react";

import type { LauncherControlResponse, LauncherOperation } from "../api/types";
import {
  requestWorkbenchLifecycleOperation,
  type WorkbenchLifecycleSource,
} from "./workbenchLifecycleActions";

export type UseWorkbenchLifecycleActionsResult = {
  source: WorkbenchLifecycleSource;
  /**
   * Shared launcher lifecycle request path.
   * Surfaces own their own UX (overlay vs mutation notice); this only owns the control call.
   */
  request: (
    operation: LauncherOperation,
    options?: { trigger?: string },
  ) => Promise<LauncherControlResponse>;
};

/**
 * Hook facade over `requestWorkbenchLifecycleOperation`.
 * Keeps AppShell and Launcher on one action path with a stable per-surface source identity.
 */
export function useWorkbenchLifecycleActions(
  source: WorkbenchLifecycleSource,
): UseWorkbenchLifecycleActionsResult {
  const request = useCallback(
    (operation: LauncherOperation, options?: { trigger?: string }) =>
      requestWorkbenchLifecycleOperation(operation, {
        source,
        trigger: options?.trigger,
      }),
    [source],
  );

  return useMemo(
    () => ({
      source,
      request,
    }),
    [request, source],
  );
}
