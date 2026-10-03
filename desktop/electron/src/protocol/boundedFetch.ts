export const DEFAULT_DESKTOP_CONTROL_REQUEST_TIMEOUT_MS = 5_000;

export async function boundedDesktopControlFetch(input: {
  fetchImpl?: typeof fetch;
  resource: string | URL | Request;
  init?: RequestInit;
  operation: string;
  requestTimeoutMs?: number;
}): Promise<Response> {
  const fetcher = input.fetchImpl ?? fetch;
  const timeoutMs = Math.max(
    1,
    Math.round(input.requestTimeoutMs ?? DEFAULT_DESKTOP_CONTROL_REQUEST_TIMEOUT_MS)
  );
  const controller = new AbortController();
  const existingSignal = input.init?.signal;
  // Keep both budgets attached after headers arrive: response.json() may still
  // be reading a body when either the request or caller deadline expires.
  const requestTimeoutSignal = AbortSignal.timeout(timeoutMs);
  const signals = [controller.signal, requestTimeoutSignal];
  if (existingSignal) signals.push(existingSignal);
  const signal = AbortSignal.any(signals);

  let timer: ReturnType<typeof setTimeout> | null = null;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      controller.abort(new Error(`${input.operation} timed out after ${timeoutMs}ms`));
      reject(new Error(`${input.operation} timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });

  try {
    return await Promise.race([
      fetcher(input.resource, { ...input.init, signal }),
      timeout
    ]);
  } catch (error) {
    if (requestTimeoutSignal.aborted && !existingSignal?.aborted) {
      throw new Error(`${input.operation} timed out after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    if (timer !== null) {
      clearTimeout(timer);
    }
  }
}
