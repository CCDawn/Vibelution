import { randomUUID } from "node:crypto";
import type { ActiveWorkProbeState } from "../shutdown/shutdownCoordinator.js";

export type MainWorkbenchClosePhase =
  | "confirmation_required"
  | "backend_closing"
  | "window_close_authorized"
  | "succeeded"
  | "failed";

export type MainWorkbenchCloseTransaction = {
  closeId: string;
  phase: MainWorkbenchClosePhase;
  mode: "normal" | "force";
  reason: string;
  activeWorkState: ActiveWorkProbeState;
  requestId?: string;
  failureCode?: string;
  message?: string;
};

export class MainWorkbenchCloseTransactionStore {
  private current: MainWorkbenchCloseTransaction | null = null;

  submit(input: {
    mode: "normal" | "force";
    reason: string;
    activeWorkState: ActiveWorkProbeState;
    requestId?: string;
  }): MainWorkbenchCloseTransaction {
    const active = this.current;
    if (active !== null && active.phase !== "succeeded" && active.phase !== "failed") {
      throw new Error("a workbench close transaction is already in flight");
    }
    const suppliedRequestId = String(input.requestId ?? "").trim();
    if (input.mode === "force" && !suppliedRequestId) {
      throw new Error("force workbench close requires requestId");
    }
    const requiresConfirmation = input.mode === "normal" && input.activeWorkState !== "idle";
    const transaction: MainWorkbenchCloseTransaction = {
      closeId: randomUUID(),
      phase: requiresConfirmation ? "confirmation_required" : "backend_closing",
      mode: input.mode,
      reason: input.reason,
      activeWorkState: input.activeWorkState,
      ...(requiresConfirmation
        ? { requestId: randomUUID() }
        : suppliedRequestId
          ? { requestId: suppliedRequestId }
          : {})
    };
    this.current = transaction;
    return transaction;
  }

  confirm(closeId: string, requestId: string): MainWorkbenchCloseTransaction {
    const transaction = this.requireOpen(closeId);
    if (transaction.phase !== "confirmation_required") {
      throw new Error(`workbench close transaction ${closeId} is not awaiting confirmation`);
    }
    if (!transaction.requestId || transaction.requestId !== requestId.trim()) {
      throw new Error(`workbench close transaction ${closeId} request id does not match`);
    }
    transaction.mode = "force";
    transaction.phase = "backend_closing";
    return transaction;
  }

  backendStopped(closeId: string): MainWorkbenchCloseTransaction {
    const transaction = this.requireOpen(closeId);
    if (transaction.phase !== "backend_closing") {
      throw new Error(`workbench close transaction ${closeId} is not closing the backend`);
    }
    transaction.phase = "window_close_authorized";
    return transaction;
  }

  windowClosed(closeId: string): MainWorkbenchCloseTransaction {
    const transaction = this.requireOpen(closeId);
    if (transaction.phase !== "window_close_authorized") {
      throw new Error(`workbench close transaction ${closeId} is not authorized to close the window`);
    }
    transaction.phase = "succeeded";
    return transaction;
  }

  fail(closeId: string, failureCode: string, message: string): MainWorkbenchCloseTransaction {
    const transaction = this.requireOpen(closeId);
    transaction.phase = "failed";
    transaction.failureCode = failureCode;
    transaction.message = message;
    return transaction;
  }

  get(closeId: string): MainWorkbenchCloseTransaction | null {
    return this.current?.closeId === closeId ? this.current : null;
  }

  currentTransaction(): MainWorkbenchCloseTransaction | null {
    return this.current;
  }

  private requireOpen(closeId: string): MainWorkbenchCloseTransaction {
    const transaction = this.current;
    if (transaction === null || transaction.closeId !== closeId) {
      throw new Error(`unknown workbench close transaction ${closeId}`);
    }
    if (transaction.phase === "succeeded" || transaction.phase === "failed") {
      throw new Error(`workbench close transaction ${closeId} already reached ${transaction.phase}`);
    }
    return transaction;
  }
}
