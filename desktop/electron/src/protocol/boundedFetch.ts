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
  const forwardAbort = () => controller.abort(existingSignal?.reason);
  if (existingSignal?.aborted) {
    forwardAbort();
  } else {
    existingSignal?.addEventListener("abort", forwardAbort, { once: true });
  }

  let timer: ReturnType<typeof setTimeout> | null = null;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      controller.abort(new Error(`${input.operation} timed out after ${timeoutMs}ms`));
      reject(new Error(`${input.operation} timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });

  try {
    return await Promise.race([
      fetcher(input.resource, { ...input.init, signal: controller.signal }),
      timeout
    ]);
  } finally {
    if (timer !== null) {
      clearTimeout(timer);
    }
    existingSignal?.removeEventListener("abort", forwardAbort);
  }
}
