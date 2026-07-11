import { AlertTriangle, Bot, RefreshCw } from "lucide-react";
import { type ReactNode } from "react";

import { VButton, VEmptyState } from "../components/vui";
import {
  AgentDenseList,
  type AgentDenseColumn,
  type AgentDenseListProps,
} from "../components/vui/product/agent-management";

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
      <VEmptyState icon={<AlertTriangle size={22} />} title={copy.loadFailed}>
        {errorText(error)}
        <VButton variant="secondary" onPress={onRetry}>{copy.retry}</VButton>
      </VEmptyState>
    );
  }

  if (presentation === "initial-loading") {
    return <VEmptyState aria-busy={isPending && !hasWorkspace || undefined} icon={<RefreshCw size={22} />} title={copy.loading} />;
  }

  const backgroundStatus = presentation === "refreshing"
    ? <p role="status">{copy.refreshing}</p>
    : presentation === "error-with-data"
      ? <div role="status">{copy.staleError} <VButton variant="secondary" onPress={onRetry}>{copy.retry}</VButton></div>
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
