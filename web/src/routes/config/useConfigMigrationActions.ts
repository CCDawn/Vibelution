/**
 * Config LLM v2 migration preview/apply actions.
 * Formal operator-config apply remains on ConfigRoute.
 * Wave 4: the destructive apply confirm is a VConfirmDialog request state
 * (two-phase) instead of a blocking window.confirm.
 */
import { useCallback, useState } from "react";
import type { QueryClient, UseQueryResult } from "@tanstack/react-query";

import { applyLlmV2Migration, previewLlmV2Migration } from "../../api/config";
import { queryKeys } from "../../api/queryKeys";
import type {
  ConfigMigrationArtifactResolution,
  ConfigMigrationPreview,
  ConfigMigrationPreviewRequest,
  ConfigWorkspace,
} from "../../api/types";
import { shouldResetMigrationPreview } from "../configRouteLogic";
import { type ConfigCopy, formatConfigCopy } from "./configCopy";

type NoticeTone = "neutral" | "success" | "error";

/** Pending "apply previewed migration" confirmation (rendered by the route as VConfirmDialog). */
export type MigrationApplyConfirmRequest = {
  previewId: string;
  previewBaseHash: string;
  message: string;
};

export type UseConfigMigrationActionsOptions = {
  migrationPreview: ConfigMigrationPreview | null;
  migrationPreviewExpiredMessage: string;
  /** Bilingual copy table (wave 4): busy labels + apply confirmation copy. */
  copy: ConfigCopy;
  workspaceQuery: UseQueryResult<ConfigWorkspace, Error>;
  queryClient: QueryClient;
  setBusyAction: (value: string) => void;
  setMigrationPreview: (value: ConfigMigrationPreview | null) => void;
  setProviderActionError: (value: string) => void;
  syncWorkspace: (workspace: ConfigWorkspace, tone?: NoticeTone, options?: { resetBase?: boolean }) => void;
  markError: (error: unknown) => string;
  readableErrorMessage: (error: unknown) => string;
};

export function useConfigMigrationActions(options: UseConfigMigrationActionsOptions) {
  const {
    migrationPreview,
    migrationPreviewExpiredMessage,
    copy,
    workspaceQuery,
    queryClient,
    setBusyAction,
    setMigrationPreview,
    setProviderActionError,
    syncWorkspace,
    markError,
    readableErrorMessage,
  } = options;

  // Wave 4: destructive apply confirms via a route-rendered VConfirmDialog
  // request state instead of a blocking window.confirm.
  const [migrationApplyRequest, setMigrationApplyRequest] = useState<MigrationApplyConfirmRequest | null>(null);

  const handlePreviewMigration = useCallback(async (
    artifactResolutions: ConfigMigrationArtifactResolution[] = [],
  ) => {
    setBusyAction(copy.migrationPreviewPending);
    try {
      const payload: ConfigMigrationPreviewRequest = { artifactResolutions };
      const response = await previewLlmV2Migration(payload);
      setMigrationPreview(response);
    } catch (error) {
      setProviderActionError(readableErrorMessage(error).slice(0, 480));
      markError(error);
    } finally {
      setBusyAction("");
    }
  }, [copy, markError, readableErrorMessage, setBusyAction, setMigrationPreview, setProviderActionError]);

  /** Opens the apply confirmation dialog (no destructive work happens here). */
  const handleApplyMigration = useCallback((previewId: string, previewBaseHash: string) => {
    if (!migrationPreview || migrationPreview.previewId !== previewId || migrationPreview.baseHash !== previewBaseHash) {
      return;
    }
    const impactedRefs = Object.values(migrationPreview.modelRefMap).slice(0, 8).join("\n");
    setMigrationApplyRequest({
      previewId,
      previewBaseHash,
      message: formatConfigCopy(copy.migrationApplyConfirm, {
        liveCount: migrationPreview.referenceImpact.liveReferenceCount,
        refs: impactedRefs,
      }),
    });
  }, [copy, migrationPreview]);

  const handleCancelApplyMigration = useCallback(() => {
    setMigrationApplyRequest(null);
  }, []);

  const handleConfirmApplyMigration = useCallback(async () => {
    const request = migrationApplyRequest;
    setMigrationApplyRequest(null);
    if (!request) return;
    const { previewId, previewBaseHash } = request;
    setBusyAction(copy.migrationApplyPending);
    try {
      await applyLlmV2Migration({ previewId, baseHash: previewBaseHash });
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
    copy,
    markError,
    migrationApplyRequest,
    migrationPreviewExpiredMessage,
    queryClient,
    readableErrorMessage,
    setBusyAction,
    setMigrationPreview,
    setProviderActionError,
    syncWorkspace,
    workspaceQuery,
  ]);

  return {
    handlePreviewMigration,
    handleApplyMigration,
    migrationApplyRequest,
    handleConfirmApplyMigration,
    handleCancelApplyMigration,
  };
}
