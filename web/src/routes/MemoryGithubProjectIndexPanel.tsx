import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { cloneGithubProject } from "../api/memory";
import { queryKeys } from "../api/queryKeys";
import type {
  GithubProjectLibraryMutationResponse,
  GithubProjectLibraryPayload,
} from "../api/types";
import {
  VButton,
  VChip,
  VEmptyState,
  VEntityList,
  VNativeInput,
  VPanelHeader,
  VSurface,
} from "../components/vui";
import styles from "./MemoryGithubProjectIndexPanel.styles";

export type MemoryGithubProjectIndexPanelCopy = {
  title: string;
  hint: string;
  empty: string;
  clonePlaceholder: string;
  cloneAction: string;
  confirmAction: string;
  ready: string;
};

type MemoryGithubProjectIndexPanelProps = {
  copy: MemoryGithubProjectIndexPanelCopy;
  library?: GithubProjectLibraryPayload | null;
  loading?: boolean;
};

export function MemoryGithubProjectIndexPanel({
  copy,
  library,
  loading = false,
}: MemoryGithubProjectIndexPanelProps) {
  const queryClient = useQueryClient();
  const [spec, setSpec] = useState("");
  const [pendingConfirm, setPendingConfirm] = useState(false);
  const cloneMutation = useMutation({
    mutationFn: (input: { spec: string; confirm: boolean }) =>
      cloneGithubProject<GithubProjectLibraryMutationResponse>(input),
    onSuccess: async (payload) => {
      setPendingConfirm(payload.status === "confirmation_required");
      await queryClient.invalidateQueries({ queryKey: queryKeys.githubProjectLibrary() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
    },
  });
  const items = (library?.projects ?? []).map((project) => ({
    ...project,
    id: project.projectId || project.fullName,
  }));
  const feedback = cloneMutation.data?.message || (cloneMutation.error instanceof Error ? cloneMutation.error.message : "");

  return (
    <VSurface className={styles.githubProjectsPanel} elevation="panel" tone="rail" padding="compact">
      <VPanelHeader
        eyebrow={copy.ready}
        title={copy.title}
        tooltip={copy.hint}
        tooltipLabel={`${copy.title} details`}
        actions={<VChip tone="neutral">{library?.summary.readyCount ?? 0}</VChip>}
      />
      <div className={styles.cloneRow}>
        <VNativeInput
          value={spec}
          placeholder={copy.clonePlaceholder}
          aria-label={copy.clonePlaceholder}
          onChange={(event) => {
            setSpec(event.target.value);
            setPendingConfirm(false);
          }}
        />
        <VButton
          type="button"
          density="compact"
          isDisabled={!spec.trim() || cloneMutation.isPending || loading}
          onClick={() => cloneMutation.mutate({ spec: spec.trim(), confirm: pendingConfirm })}
        >
          {pendingConfirm ? copy.confirmAction : copy.cloneAction}
        </VButton>
      </div>
      {feedback ? <p className={styles.feedback}>{feedback}</p> : null}
      <VEntityList
        className={styles.list}
        ariaLabel={copy.title}
        items={items}
        empty={<VEmptyState align="start" title={copy.empty} />}
        renderItem={(project) => (
          <div className={styles.row}>
            <div className={styles.meta}>
              <span className={styles.title}>{project.name || project.fullName}</span>
              <VChip tone="neutral">{project.status || copy.ready}</VChip>
              {project.license ? <VChip tone="neutral">{project.license}</VChip> : null}
            </div>
            <p className={styles.description}>{project.description || project.fullName}</p>
          </div>
        )}
      />
    </VSurface>
  );
}
