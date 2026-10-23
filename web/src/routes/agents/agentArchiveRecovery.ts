import {
  archiveAgent, bulkArchiveAgents, fetchAgentArchiveState, isAgentArchiveOutcomeUncertain,
} from "../../api/agents";
import type { AgentConfigWorkspaceAgent } from "../../api/types";
import type { AgentBulkActionItem, AgentBulkActionResponse } from "../agentWorkspaceCache";

export class AgentArchiveInProgressError extends Error {
  constructor() { super("该 Agent 的归档仍在处理中"); }
}

export class AgentArchiveOutcomeUnknownError extends Error {
  constructor(readonly agentId: string) {
    super("归档结果尚未确认；可再次点击归档以先核对状态，不会自动重发请求。");
  }
}

export type AgentArchiveBatchResult = AgentBulkActionResponse & { uncertain: AgentBulkActionItem[] };

function confirmed(agentId: string, value: AgentConfigWorkspaceAgent): boolean {
  return value?.agentId === agentId && value.status === "archived";
}

/** A later authoritative edit must not be replaced by an older archive reply. */
export function archiveSnapshotIsCurrent(current: AgentConfigWorkspaceAgent | undefined, incoming: AgentConfigWorkspaceAgent) {
  if (!current) return true;
  if (Number(current.configRevision) > Number(incoming.configRevision)) return false;
  if (current.runtimeStatus?.reason === "agent_archive_pending") return true;
  const oldTime = Date.parse(current.updatedAt ?? ""), nextTime = Date.parse(incoming.updatedAt ?? "");
  return !(Number.isFinite(oldTime) && Number.isFinite(nextTime) && oldTime > nextTime);
}

/** Operation-scoped recovery, shared by single and bulk writes in one workbench. */
export function createAgentArchiveRecovery(onPendingChange: (ids: ReadonlySet<string>) => void = () => {}) {
  const pending = new Set<string>();
  const uncertain = new Set<string>();
  const unknown = (agentId: string): AgentBulkActionItem => ({ agentId, reason: "archive_outcome_unknown", message: new AgentArchiveOutcomeUnknownError(agentId).message });

  async function readback(agentId: string) {
    const value = await fetchAgentArchiveState(agentId);
    if (value?.agentId !== agentId) throw new AgentArchiveOutcomeUnknownError(agentId);
    if (confirmed(agentId, value)) uncertain.delete(agentId);
    return value;
  }

  return {
    begin(agentIds: readonly string[]) {
      if (agentIds.some(id => pending.has(id))) throw new AgentArchiveInProgressError();
      agentIds.forEach(id => pending.add(id));
      onPendingChange(new Set(pending));
      return () => {
        agentIds.forEach(id => pending.delete(id));
        onPendingChange(new Set(pending));
      };
    },
    isPending: (agentId: string) => pending.has(agentId),
    async single(agentId: string): Promise<AgentConfigWorkspaceAgent> {
      // Only a new explicit action may retry a write, after an authoritative read.
      if (uncertain.has(agentId)) {
        const latest = await readback(agentId).catch(() => { throw new AgentArchiveOutcomeUnknownError(agentId); });
        if (confirmed(agentId, latest)) return latest;
      }
      try {
        const value = await archiveAgent(agentId);
        if (!confirmed(agentId, value)) throw new AgentArchiveOutcomeUnknownError(agentId);
        uncertain.delete(agentId);
        return value;
      } catch (error) {
        if (!isAgentArchiveOutcomeUncertain(error)) throw error;
        uncertain.add(agentId);
        const latest = await readback(agentId).catch(() => undefined);
        if (latest && confirmed(agentId, latest)) return latest;
        throw new AgentArchiveOutcomeUnknownError(agentId);
      }
    },
    async bulk(agentIds: string[]): Promise<AgentArchiveBatchResult> {
      const success: AgentBulkActionItem[] = [], skipped: AgentBulkActionItem[] = [], failed: AgentBulkActionItem[] = [], unresolved: AgentBulkActionItem[] = [];
      const eligible: string[] = [];
      await Promise.all(agentIds.map(async agentId => {
        if (!uncertain.has(agentId)) { eligible.push(agentId); return; }
        try {
          const latest = await readback(agentId);
          if (confirmed(agentId, latest)) success.push(latest);
          else eligible.push(agentId);
        } catch { unresolved.push(unknown(agentId)); }
      }));
      if (eligible.length) {
        try {
          const result = await bulkArchiveAgents<AgentBulkActionResponse>(eligible);
          skipped.push(...result.skipped);
          failed.push(...result.failed);
          await Promise.all(result.success.map(async item => {
            if (!eligible.includes(item.agentId)) return;
            if (confirmed(item.agentId, item as AgentConfigWorkspaceAgent)) {
              uncertain.delete(item.agentId); success.push(item); return;
            }
            uncertain.add(item.agentId);
            const latest = await readback(item.agentId).catch(() => undefined);
            if (latest && confirmed(item.agentId, latest)) success.push(latest);
            else unresolved.push(unknown(item.agentId));
          }));
          const reported = new Set([...result.success, ...result.skipped, ...result.failed].map(item => item.agentId));
          eligible.filter(id => !reported.has(id)).forEach(id => { uncertain.add(id); unresolved.push(unknown(id)); });
        } catch (error) {
          if (!isAgentArchiveOutcomeUncertain(error)) {
            failed.push(...eligible.map(agentId => ({ agentId, message: error instanceof Error ? error.message : String(error) })));
          } else {
            await Promise.all(eligible.map(async agentId => {
              uncertain.add(agentId);
              const latest = await readback(agentId).catch(() => undefined);
              if (latest && confirmed(agentId, latest)) success.push(latest);
              else unresolved.push(unknown(agentId));
            }));
          }
        }
      }
      return {
        status: unresolved.length ? "uncertain" : "completed", requestedAgentIds: agentIds,
        success, skipped, failed, uncertain: unresolved,
        summary: { requestedCount: agentIds.length, successCount: success.length, skippedCount: skipped.length, failedCount: failed.length },
      };
    },
  };
}
