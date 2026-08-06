import { AlertTriangle, Bot } from "lucide-react";
import { type ReactNode } from "react";

import { VButton, VEmptyState, VStateSurface } from "../components/vui";
import {
  AgentDenseList,
  type AgentDenseColumn,
  type AgentDenseListProps,
} from "../components/vui/product/agent-management";
import { ProgressiveRegionSkeleton } from "./shared/ProgressiveRegionSkeleton";

type AgentListStatePanelCopy = {
  loadFailed: string;
  loading: string;
  noAgents: string;
  retry: string;
  refreshing: string;
  staleError: string;
  model: ReactNode;
  prompt: ReactNode;
  runtimeStatus: ReactNode;
  modeMembership: ReactNode;
  statusReminders: ReactNode;
};

type AgentListStatePanelProps = {
  copy: AgentListStatePanelCopy;
  columns: AgentDenseColumn[];
  visibleAgentCount: number;
  isError: boolean;
  error: unknown;
  isPending: boolean;
  isFetching: boolean;
  hasWorkspace: boolean;
  onRetry: () => void;
  onSelectRow: AgentDenseListProps["onSelectRow"];
  onToggleBulk: AgentDenseListProps["onToggleBulk"];
};

export type AgentListPresentation = "initial-loading" | "initial-error" | "refreshing" | "error-with-data" | "ready";

export function resolveAgentListPresentation({
  hasWorkspace,
  isPending,
  isFetching,
  isError,
}: Pick<AgentListStatePanelProps, "hasWorkspace" | "isPending" | "isFetching" | "isError">): AgentListPresentation {
  if (!hasWorkspace && isError) return "initial-error";
  if (!hasWorkspace && isPending) return "initial-loading";
  if (hasWorkspace && isError) return "error-with-data";
  if (hasWorkspace && isFetching) return "refreshing";
  return "ready";
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function AgentListStatePanel({
  copy,
  columns,
  visibleAgentCount,
  isError,
  error,
  isPending,
  isFetching,
  hasWorkspace,
  onRetry,
  onSelectRow,
  onToggleBulk,
}: AgentListStatePanelProps) {
  const presentation = resolveAgentListPresentation({ hasWorkspace, isPending, isFetching, isError });

  if (presentation === "initial-error") {
    return (
      <VEmptyState
        icon={<AlertTriangle size={22} />}
        title={copy.loadFailed}
        actions={<VButton variant="secondary" onPress={onRetry}>{copy.retry}</VButton>}
      >
        {errorText(error)}
      </VEmptyState>
    );
  }

  if (presentation === "initial-loading") {
    return <ProgressiveRegionSkeleton className="p-2.5" label={copy.loading} variant="list" />;
  }

  const backgroundStatus = presentation === "refreshing"
    ? <span className="sr-only" role="status">{copy.refreshing}</span>
    : presentation === "error-with-data"
      ? (
        <VStateSurface
          role="status"
          density="compact"
          tone="error"
          title={copy.staleError}
          actions={<VButton variant="secondary" onPress={onRetry}>{copy.retry}</VButton>}
        />
      )
      : null;

  if (visibleAgentCount === 0) {
    return (
      <>
        {backgroundStatus}
        <VEmptyState icon={<Bot size={22} />} title={copy.noAgents} />
      </>
    );
  }

  return (
    <>
      {backgroundStatus}
      <AgentDenseList
        columns={columns}
        columnLabels={{
          agent: "Agent",
          model: copy.model,
          prompt: copy.prompt,
          runtime: copy.runtimeStatus,
          modes: copy.modeMembership,
          reminders: copy.statusReminders,
        }}
        onSelectRow={onSelectRow}
        onToggleBulk={onToggleBulk}
      />
    </>
  );
}
