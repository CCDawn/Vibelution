import { randomUUID } from "node:crypto";

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
  failureCode?: string;
  message?: string;
};

export class MainWorkbenchCloseTransactionStore {
  private current: MainWorkbenchCloseTransaction | null = null;

  submit(input: {
    mode: "normal" | "force";
    reason: string;
    activeWork: boolean;
  }): MainWorkbenchCloseTransaction {
    const active = this.current;
    if (active !== null && active.phase !== "succeeded" && active.phase !== "failed") {
      throw new Error("a workbench close transaction is already in flight");
    }
    const transaction: MainWorkbenchCloseTransaction = {
      closeId: randomUUID(),
      phase: input.activeWork && input.mode === "normal" ? "confirmation_required" : "backend_closing",
      mode: input.mode,
      reason: input.reason
    };
    this.current = transaction;
    return transaction;
  }

  confirm(closeId: string): MainWorkbenchCloseTransaction {
    const transaction = this.requireOpen(closeId);
    if (transaction.phase !== "confirmation_required") {
      throw new Error(`workbench close transaction ${closeId} is not awaiting confirmation`);
    }
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
