/**
 * Config LLM v2 migration preview/apply actions.
 * Formal operator-config apply remains on ConfigRoute.
 */
import { useCallback } from "react";
import type { QueryClient, UseQueryResult } from "@tanstack/react-query";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type {
  ConfigMigrationArtifactResolution,
  ConfigMigrationPreview,
  ConfigMigrationPreviewRequest,
  ConfigWorkspace,
} from "../../api/types";
import { shouldResetMigrationPreview } from "../configRouteLogic";

type NoticeTone = "neutral" | "success" | "error";

export type UseConfigMigrationActionsOptions = {
  migrationPreview: ConfigMigrationPreview | null;
  migrationPreviewExpiredMessage: string;
  workspaceQuery: UseQueryResult<ConfigWorkspace, Error>;
  queryClient: QueryClient;
  setBusyAction: (value: string) => void;
  setMigrationPreview: (value: ConfigMigrationPreview | null) => void;
  setProviderActionError: (value: string) => void;
  syncWorkspace: (workspace: ConfigWorkspace, tone?: NoticeTone, options?: { resetBase?: boolean }) => void;
  markError: (error: unknown) => string;
  readableErrorMessage: (error: unknown) => string;
  requestJson?: <T>(url: string, body?: unknown, method?: string) => Promise<T>;
  confirmApplyMigration?: (message: string) => boolean;
};

async function defaultRequestJson<T>(url: string, body?: unknown, method = "POST"): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body == null ? undefined : JSON.stringify(body),
  });
}

export function useConfigMigrationActions(options: UseConfigMigrationActionsOptions) {
  const {
    migrationPreview,
    migrationPreviewExpiredMessage,
    workspaceQuery,
    queryClient,
    setBusyAction,
    setMigrationPreview,
    setProviderActionError,
    syncWorkspace,
    markError,
    readableErrorMessage,
    requestJson = defaultRequestJson,
    confirmApplyMigration = (message: string) => typeof window === "undefined" || window.confirm(message),
  } = options;

  const handlePreviewMigration = useCallback(async (
    artifactResolutions: ConfigMigrationArtifactResolution[] = [],
  ) => {
    setBusyAction("正在生成迁移预览…");
    try {
      const payload: ConfigMigrationPreviewRequest = { artifactResolutions };
      const response = await requestJson<ConfigMigrationPreview>(
        "/api/config/migration/llm-v2/preview",
        payload,
      );
      setMigrationPreview(response);
    } catch (error) {
      setProviderActionError(readableErrorMessage(error).slice(0, 480));
      markError(error);
    } finally {
      setBusyAction("");
    }
  }, [markError, readableErrorMessage, requestJson, setBusyAction, setMigrationPreview, setProviderActionError]);

  const handleApplyMigration = useCallback(async (previewId: string, previewBaseHash: string) => {
    if (!migrationPreview || migrationPreview.previewId !== previewId || migrationPreview.baseHash !== previewBaseHash) {
      return;
    }
    const impactedRefs = Object.values(migrationPreview.modelRefMap).slice(0, 8).join("\n");
    const confirmed = confirmApplyMigration(
      `将修改外部 operator config。\nLive references: ${migrationPreview.referenceImpact.liveReferenceCount}\nCanonical model refs:\n${impactedRefs}\n\n确认应用已预览的迁移？`,
    );
    if (!confirmed) return;
    setBusyAction("正在应用迁移…");
    try {
      await requestJson<{ migrationId: string; updatedReferenceCount?: number }>(
        "/api/config/migration/llm-v2/apply",
        { previewId, baseHash: previewBaseHash },
      );
      const refreshed = await workspaceQuery.refetch();
      if (refreshed.data) {
        syncWorkspace(refreshed.data, "success");
      }
      setMigrationPreview(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() });
    } catch (error) {
      if (shouldResetMigrationPreview(error)) {
        setMigrationPreview(null);
        setProviderActionError(migrationPreviewExpiredMessage);
      } else {
        setProviderActionError(readableErrorMessage(error).slice(0, 480));
      }
      markError(error);
    } finally {
      setBusyAction("");
    }
  }, [
    confirmApplyMigration,
    markError,
    migrationPreview,
    migrationPreviewExpiredMessage,
    queryClient,
    readableErrorMessage,
    requestJson,
    setBusyAction,
    setMigrationPreview,
    setProviderActionError,
    syncWorkspace,
    workspaceQuery,
  ]);

  return {
    handlePreviewMigration,
    handleApplyMigration,
  };
}
