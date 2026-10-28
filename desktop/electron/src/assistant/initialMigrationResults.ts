import { AssistantProjectLifecycleRequestStore } from "./projectLifecycleRequestStore.js";

/** A result is recorded only after the owned migration Job and output drain exit. */
export class InitialMigrationResults {
  private readonly store: AssistantProjectLifecycleRequestStore;
  constructor(directory: string) { this.store = new AssistantProjectLifecycleRequestStore({ directory }); }

  async record(operationId: string, state: "completed" | "partial"): Promise<void> {
    if (!/^initial-[a-f0-9]{40}$/.test(operationId) || !["completed", "partial"].includes(state))
      throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
    await this.store.reserve({ requestId: operationId, projectId: state, operation: "start" });
  }

  async get(operationId: string): Promise<"completed" | "partial" | null> {
    if (!/^initial-[a-f0-9]{40}$/.test(operationId)) throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
    const row = await this.store.get(operationId);
    if (!row) return null;
    if (row.request.requestId !== operationId || row.request.operation !== "start" || row.binding !== null || row.command !== null
      || (row.request.projectId !== "completed" && row.request.projectId !== "partial"))
      throw new Error("INITIAL_MIGRATION_RESULT_INVALID");
    return row.request.projectId;
  }
}
