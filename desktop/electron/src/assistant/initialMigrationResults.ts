import { AssistantProjectLifecycleRequestStore } from "./projectLifecycleRequestStore.js";

/** A result is recorded only after the owned migration Job and output drain exit. */
export class InitialMigrationResults {
  private readonly store: AssistantProjectLifecycleRequestStore;
  private readonly ownedAttempts = new Set<string>();
  constructor(directory: string) { this.store = new AssistantProjectLifecycleRequestStore({ directory }); }

  /** Fence a sync before launching its Job; a lost response is never replayed. */
  async begin(operationId: string): Promise<boolean> {
    if (!/^(?:ksync|krec)-[a-f0-9]{40}$/.test(operationId)) throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
    const result = await this.store.reserve({ requestId: `${operationId}.attempt`, projectId: "unknown", operation: "start" });
    if (result.created && result.reservationToken) this.ownedAttempts.add(operationId);
    return result.created;
  }

  /** Only the main owner that reserved this attempt can attest no writer could run. */
  async recordNotStarted(operationId: string): Promise<void> {
    if (!this.ownedAttempts.has(operationId)) throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
    const result = await this.store.reserve({ requestId: operationId, projectId: "not_started", operation: "start" });
    if (!result.created) throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
    this.ownedAttempts.delete(operationId);
  }

  async record(operationId: string, state: "completed" | "partial"): Promise<void> {
    if (!/^(?:initial|ksync|krec)-[a-f0-9]{40}$/.test(operationId) || !["completed", "partial"].includes(state))
      throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
    await this.store.reserve({ requestId: operationId, projectId: state, operation: "start" });
    this.ownedAttempts.delete(operationId);
  }

  /** Persist a fail-closed receipt without replacing a prior final result. */
  async recordUnknown(operationId: string): Promise<"completed" | "partial" | "unknown"> {
    const existing = await this.get(operationId);
    if (existing) return existing === "not_started" ? "unknown" : existing;
    await this.store.reserve({ requestId: operationId, projectId: "unknown", operation: "start" });
    const persisted = await this.get(operationId);
    if (persisted !== "unknown") throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
    return persisted;
  }

  async get(operationId: string): Promise<"completed" | "partial" | "unknown" | "not_started" | null> {
    if (!/^(?:initial|ksync|krec)-[a-f0-9]{40}$/.test(operationId)) throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
    const row = await this.store.get(operationId);
    if (!row) {
      if (!operationId.startsWith("ksync-") && !operationId.startsWith("krec-")) return null;
      const attempt = await this.store.get(`${operationId}.attempt`);
      if (!attempt) return null;
      if (attempt.request.requestId !== `${operationId}.attempt` || attempt.request.projectId !== "unknown"
        || attempt.request.operation !== "start" || attempt.binding !== null || attempt.command !== null)
        throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
      return "unknown";
    }
    if (row.request.requestId !== operationId || row.request.operation !== "start" || row.binding !== null || row.command !== null
      || (row.request.projectId !== "completed" && row.request.projectId !== "partial" && row.request.projectId !== "unknown" && row.request.projectId !== "not_started"))
      throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
    if (row.request.projectId === "not_started") {
      if (!operationId.startsWith("ksync-") && !operationId.startsWith("krec-")) throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
      const attempt = await this.store.get(`${operationId}.attempt`);
      if (!attempt || attempt.request.requestId !== `${operationId}.attempt` || attempt.request.projectId !== "unknown"
        || attempt.request.operation !== "start" || attempt.binding !== null || attempt.command !== null)
        throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
    }
    return row.request.projectId;
  }
}
