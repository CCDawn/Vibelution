export type WorkbenchCloseTransactionPhase =
  | "confirmation_required"
  | "backend_closing"
  | "window_close_authorized"
  | "succeeded"
  | "failed";

export type WorkbenchCloseTransaction = {
  closeId: string;
  phase: WorkbenchCloseTransactionPhase | string;
  mode?: "normal" | "force" | string;
  confirmationCloseId?: string;
  nextPollAfterMs?: number;
  deadlineAt?: string;
  retryable?: boolean;
  failureCode?: string;
  message?: string;
};

export type WorkbenchCloseTransactionRequestOperation = "submit" | "fetch" | "window closed acknowledgement";

/**
 * Keeps control-plane rejection details available to the Electron lifecycle
 * owner without parsing a user-facing error message.
 */
export class WorkbenchCloseTransactionRequestError extends Error {
  constructor(
    readonly operation: WorkbenchCloseTransactionRequestOperation,
    readonly status: number
  ) {
    super(`workbench close transaction ${operation} failed: ${status}`);
    this.name = "WorkbenchCloseTransactionRequestError";
  }
}

/**
 * A rejected submit cannot have created a close transaction, so it is safe to
 * refresh the local control context and submit the same idempotent request one
 * more time. Poll and acknowledgement failures deliberately do not use this
 * helper: their transaction may already be in flight or complete.
 */
export async function retryRejectedWorkbenchCloseSubmitOnce<T>(
  submit: () => Promise<T>,
  recoverControlContext: () => Promise<void>
): Promise<T> {
  try {
    return await submit();
  } catch (error: unknown) {
    if (!isRecoverableWorkbenchCloseSubmitRejection(error)) {
      throw error;
    }
    await recoverControlContext();
    return await submit();
  }
}

function isRecoverableWorkbenchCloseSubmitRejection(
  error: unknown
): error is WorkbenchCloseTransactionRequestError {
  return error instanceof WorkbenchCloseTransactionRequestError
    && error.operation === "submit"
    && (error.status === 401 || error.status === 403);
}

type WorkbenchCloseTransactionRequest = {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  fetchImpl?: typeof fetch;
};

export function workbenchCloseTransactionEndpoints(launcherOrigin: string) {
  const origin = new URL(launcherOrigin).origin;
  const transactions = `${origin}/api/launcher/workbench-close-transactions`;
  return {
    submit: transactions,
    transaction: `${transactions}/{closeId}`,
    windowClosed: `${transactions}/{closeId}/window-closed`
  };
}

export async function submitWorkbenchCloseTransaction(
  input: WorkbenchCloseTransactionRequest & {
    idempotencyKey: string;
    mode: "normal" | "force";
    reason: string;
    confirmationCloseId?: string;
  }
): Promise<WorkbenchCloseTransaction> {
  const fetcher = input.fetchImpl ?? fetch;
  const response = await fetcher(workbenchCloseTransactionEndpoints(input.launcherOrigin).submit, {
    method: "POST",
    headers: transactionHeaders(input.controlToken),
    body: JSON.stringify({
      desktopSessionId: input.desktopSessionId,
      idempotencyKey: input.idempotencyKey,
      mode: input.mode,
      reason: input.reason,
      confirmationCloseId: input.confirmationCloseId ?? ""
    })
  });
  return await readTransaction(response, "submit");
}

export async function fetchWorkbenchCloseTransaction(
  input: WorkbenchCloseTransactionRequest & { closeId: string }
): Promise<WorkbenchCloseTransaction> {
  const fetcher = input.fetchImpl ?? fetch;
  const endpoint = workbenchCloseTransactionEndpoints(input.launcherOrigin).transaction.replace(
    "{closeId}",
    encodeURIComponent(input.closeId)
  );
  const response = await fetcher(endpoint, {
    method: "GET",
    headers: { "X-Vibelution-Control-Token": input.controlToken }
  });
  return await readTransaction(response, "fetch");
}

export async function acknowledgeWorkbenchCloseWindowClosed(
  input: WorkbenchCloseTransactionRequest & { closeId: string; desktopSessionRevision: number }
): Promise<WorkbenchCloseTransaction> {
  const fetcher = input.fetchImpl ?? fetch;
  const endpoint = workbenchCloseTransactionEndpoints(input.launcherOrigin).windowClosed.replace(
    "{closeId}",
    encodeURIComponent(input.closeId)
  );
  const response = await fetcher(endpoint, {
    method: "POST",
    headers: transactionHeaders(input.controlToken),
    body: JSON.stringify({
      desktopSessionId: input.desktopSessionId,
      desktopSessionRevision: input.desktopSessionRevision
    })
  });
  return await readTransaction(response, "window closed acknowledgement");
}

function transactionHeaders(controlToken: string): Record<string, string> {
  return {
    "content-type": "application/json",
    "X-Vibelution-Control-Token": controlToken
  };
}

async function readTransaction(
  response: Response,
  operation: WorkbenchCloseTransactionRequestOperation
): Promise<WorkbenchCloseTransaction> {
  if (!response.ok) {
    throw new WorkbenchCloseTransactionRequestError(operation, response.status);
  }
  return (await response.json()) as WorkbenchCloseTransaction;
}
