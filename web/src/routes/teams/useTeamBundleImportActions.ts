/**
 * Team bundle import orchestration: file parsing + dry-run preview +
 * confirmed execution. State machine lives in teamBundleImportLogic.
 */
import { useCallback, useReducer, useRef } from "react";
import type { Dispatch } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { importTeamBundle } from "../../api/teamBundles";
import { queryKeys } from "../../api/queryKeys";
import type { TeamBundle } from "../../api/types";
import {
  initialTeamBundleImportState,
  reportNeedsSchemaConfirm,
  teamBundleImportReducer,
  type TeamBundleImportAction,
  type TeamBundleImportState,
} from "./teamBundleImportLogic";

export type UseTeamBundleImportActionsOptions = {
  dispatchOverride?: Dispatch<TeamBundleImportAction>;
  invalidateQueries?: (queryClient: QueryClient) => void;
  queryClient: QueryClient;
};

function parseBundleText(text: string): TeamBundle {
  const parsed = JSON.parse(text) as TeamBundle;
  if (!parsed || typeof parsed !== "object" || !parsed.team || !Array.isArray(parsed.agents)) {
    throw new Error("invalid bundle");
  }
  return parsed;
}

export function useTeamBundleImportActions(options: UseTeamBundleImportActionsOptions) {
  const { queryClient } = options;
  const [state, dispatch] = useReducer(teamBundleImportReducer, undefined, initialTeamBundleImportState);
  const stateRef = useRef(state);
  stateRef.current = state;
  const bundleTextRef = useRef("");

  const prepareBundleFile = useCallback(
    async (file: File) => {
      const emit = options.dispatchOverride ?? dispatch;
      emit({ type: "load_started" });
      try {
        const text = await file.text();
        bundleTextRef.current = text;
        const bundle = parseBundleText(text);
        const report = await importTeamBundle(bundle, { dryRun: true });
        emit({ type: "load_succeeded", bundle, report });
      } catch (error) {
        const message = error instanceof Error && error.message === "invalid bundle"
          ? "invalid bundle"
          : error instanceof Error
            ? error.message
            : "load failed";
        emit({ type: "load_failed", message });
      }
    },
    [options.dispatchOverride],
  );

  const confirmImport = useCallback(async () => {
    const emit = options.dispatchOverride ?? dispatch;
    const current = stateRef.current;
    const bundle = current.bundle;
    if (!bundle) {
      return;
    }
    emit({ type: "confirm_started" });
    try {
      const report = await importTeamBundle(bundle, {
        dryRun: false,
        confirm: reportNeedsSchemaConfirm(current.report),
      });
      emit({ type: "confirm_succeeded", report });
      const invalidate = options.invalidateQueries ?? ((client: QueryClient) => {
        void client.invalidateQueries({ queryKey: queryKeys.teams() });
        void client.invalidateQueries({ queryKey: queryKeys.agents() });
      });
      invalidate(queryClient);
    } catch (error) {
      emit({
        type: "confirm_failed",
        message: error instanceof Error ? error.message : "import failed",
      });
    }
  }, [options.dispatchOverride, options.invalidateQueries, queryClient]);

  const reset = useCallback(() => {
    bundleTextRef.current = "";
    (options.dispatchOverride ?? dispatch)({ type: "reset" });
  }, [options.dispatchOverride]);

  return { state, prepareBundleFile, confirmImport, reset };
}
