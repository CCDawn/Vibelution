import { AlertTriangle, Bot, RefreshCw } from "lucide-react";
import { type ReactNode } from "react";

import { VEmptyState } from "../components/vui";
import {
  AgentDenseList,
  type AgentDenseColumn,
  type AgentDenseListProps,
} from "../components/vui/product/agent-management";

type AgentListStatePanelCopy = {
  loadFailed: string;
  loading: string;
  noAgents: string;
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
  hasWorkspace: boolean;
  onSelectRow: AgentDenseListProps["onSelectRow"];
  onToggleBulk: AgentDenseListProps["onToggleBulk"];
};

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
  hasWorkspace,
  onSelectRow,
  onToggleBulk,
}: AgentListStatePanelProps) {
  if (isError) {
    return (
      <VEmptyState icon={<AlertTriangle size={22} />} title={copy.loadFailed}>
        {errorText(error)}
      </VEmptyState>
    );
  }

  if (isPending && !hasWorkspace) {
    return <VEmptyState aria-busy={isPending && !hasWorkspace || undefined} icon={<RefreshCw size={22} />} title={copy.loading} />;
  }

  if (visibleAgentCount === 0) {
    return <VEmptyState icon={<Bot size={22} />} title={copy.noAgents} />;
  }

  return (
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
  );
}
