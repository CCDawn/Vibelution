import {
  CLIENT_OPERATION_ID_HEADER,
  currentClientOperationId,
} from "../app/clientOperationContext";

const CONTROL_TOKEN_ENDPOINT = "/api/control-token";
const CONTROL_TOKEN_HEADER_FALLBACK = "X-Vibelution-Control-Token";
const INVALID_CONTROL_TOKEN_DETAIL = "Missing or invalid web control token";

const controlTokenPromises = new Map<string, Promise<{ header: string; token: string }>>();
let fetchJsonFailureReporter: ((report: FetchJsonFailureReport) => void) | null = null;

export type FetchJsonFailureReport = {
  endpoint: string;
  method: string;
  status: number | null;
  message: string;
  failureKind: "http" | "network";
};

export type FetchJsonHttpErrorOptions = {
  status: number;
  code?: string | null;
  details?: unknown;
};

/**
 * Structured failure for a JSON HTTP response.
 *
 * Callers may use the status and server problem code to distinguish an
 * unavailable route from a domain failure. The message remains the same
 * human-readable text used by the legacy transport callers.
 */
export class FetchJsonHttpError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly details: unknown;

  constructor(message: string, options: FetchJsonHttpErrorOptions) {
    super(message);
    this.name = "FetchJsonHttpError";
    this.status = options.status;
    this.code = options.code ?? null;
    this.details = options.details;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export function isFetchJsonHttpError(error: unknown): error is FetchJsonHttpError {
  return error instanceof FetchJsonHttpError
    || (
      error instanceof Error
      && typeof (error as Error & { status?: unknown }).status === "number"
      && (error as Error & { code?: unknown }).code !== undefined
    );
}

export function resetControlTokenForTests() {
  controlTokenPromises.clear();
}

/** Pre-seed the control token so tests make no bootstrap fetch. */
export function seedControlTokenForTests(token = "test-control-token") {
  controlTokenPromises.set(
    controlTokenCacheKey(""),
    Promise.resolve({ header: CONTROL_TOKEN_HEADER_FALLBACK, token }),
  );
}

export function clearControlToken(origin?: string) {
  if (origin === undefined) {
    controlTokenPromises.clear();
    return;
  }
  controlTokenPromises.delete(controlTokenCacheKey(normalizeControlOrigin(origin)));
}

export function setFetchJsonFailureReporter(reporter: ((report: FetchJsonFailureReport) => void) | null) {
  fetchJsonFailureReporter = reporter;
}

export function isFetchAbortError(error: unknown): boolean {
  return (
    error instanceof Error
    && (error.name === "AbortError" || /abort|aborted/i.test(error.message))
  );
}

export async function getControlToken(origin = ""): Promise<{ header: string; token: string }> {
  const controlOrigin = normalizeControlOrigin(origin);
  const cacheKey = controlTokenCacheKey(controlOrigin);
  if (!controlTokenPromises.has(cacheKey)) {
    const endpoint = controlOrigin ? `${controlOrigin}${CONTROL_TOKEN_ENDPOINT}` : CONTROL_TOKEN_ENDPOINT;
    const tokenPromise = fetch(endpoint, {
      headers: { Accept: "application/json" },
      credentials: controlOrigin ? "include" : "same-origin",
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Control token request failed: ${response.status}`);
        }
        const payload = (await response.json()) as { header?: string; controlToken?: string };
        const token = String(payload.controlToken ?? "").trim();
        if (!token) {
          throw new Error("Control token response was empty");
        }
        return {
          header: String(payload.header ?? CONTROL_TOKEN_HEADER_FALLBACK).trim() || CONTROL_TOKEN_HEADER_FALLBACK,
          token,
        };
      })
      .catch((error) => {
        controlTokenPromises.delete(cacheKey);
        throw error;
      });
    controlTokenPromises.set(cacheKey, tokenPromise);
  }
  return controlTokenPromises.get(cacheKey)!;
}

function normalizeControlOrigin(origin: string): string {
  const raw = String(origin || "").trim();
  if (!raw) {
    return "";
  }
  try {
    return new URL(raw).origin;
  } catch {
    return "";
  }
}

function controlTokenCacheKey(origin: string): string {
  return origin || "same-origin";
}

function localApiOriginForControl(input: string): string {
  if (typeof window === "undefined") {
    return "";
  }
  try {
    const url = new URL(input, window.location.origin);
    if (!url.pathname.startsWith("/api/") || url.origin === window.location.origin) {
      return "";
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return "";
    }
    if (!isLoopbackHost(url.hostname)) {
      return "";
    }
    return url.origin;
  } catch {
    return "";
  }
}

function isLoopbackHost(hostname: string): boolean {
  const host = String(hostname || "").trim().toLowerCase();
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

function controlOriginForRequest(input: string): string | null {
  // The backend now requires the control token on every guarded /api
  // request, GET included, so attach it regardless of method.
  if (input.startsWith("/api/")) {
    return "";
  }
  const controlOrigin = localApiOriginForControl(input);
  return controlOrigin ? controlOrigin : null;
}

function apiEndpointForTelemetry(input: string): string {
  if (input.startsWith("/api/")) {
    return input;
  }
  if (typeof window === "undefined") {
    return "";
  }
  try {
    const url = new URL(input, window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/")) {
      return "";
    }
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "";
  }
}

function reportFetchJsonFailure(input: string, report: Omit<FetchJsonFailureReport, "endpoint">) {
  const endpoint = apiEndpointForTelemetry(input);
  if (!endpoint || !fetchJsonFailureReporter) {
    return;
  }
  try {
    fetchJsonFailureReporter({
      endpoint,
      ...report,
    });
  } catch {
    // Telemetry must not affect the request path.
  }
}

export async function fetchWithControl(input: string, init?: RequestInit): Promise<Response> {
  const method = String(init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers ?? {});
  headers.set("Accept", headers.get("Accept") ?? "application/json");
  const controlOrigin = controlOriginForRequest(input);
  let controlHeaderName: string | null = null;
  if (controlOrigin !== null) {
    const control = await getControlToken(controlOrigin);
    controlHeaderName = control.header;
    headers.set(control.header, control.token);
  }
  const clientOperationId = currentClientOperationId();
  if (clientOperationId) {
    headers.set(CLIENT_OPERATION_ID_HEADER, clientOperationId);
  }

  const performFetch = async (): Promise<Response> => {
    try {
      return await fetch(input, {
        ...init,
        headers,
        credentials: init?.credentials ?? (controlOrigin ? "include" : "same-origin"),
      });
    } catch (error) {
      if (!isFetchAbortError(error)) {
        const message = error instanceof Error ? error.message : String(error);
        reportFetchJsonFailure(input, {
          method,
          status: null,
          message: message || "Network request failed",
          failureKind: "network",
        });
      }
      throw error;
    }
  };

  let response = await performFetch();
  let parsedFailureDetails: FailureDetails | null = null;

  if (!response.ok && response.status === 403 && controlOrigin !== null) {
    parsedFailureDetails = await readFailureDetails(response);
    if (parsedFailureDetails.message === INVALID_CONTROL_TOKEN_DETAIL) {
      clearControlToken(controlOrigin);
      const refreshedControl = await getControlToken(controlOrigin);
      if (controlHeaderName) {
        headers.delete(controlHeaderName);
      }
      controlHeaderName = refreshedControl.header;
      headers.set(refreshedControl.header, refreshedControl.token);
      response = await performFetch();
      parsedFailureDetails = null;
    }
  }

  if (!response.ok) {
    const details = parsedFailureDetails ?? await readFailureDetails(response);
    const message = details.message;
    if (
      response.status === 403
      && controlOrigin !== null
      && message === INVALID_CONTROL_TOKEN_DETAIL
    ) {
      // The bounded retry has already been used. Leave the next user action
      // able to bootstrap again without turning this request into a loop.
      clearControlToken(controlOrigin);
    }
    reportFetchJsonFailure(input, {
      method,
      status: response.status,
      message: message || `Request failed: ${response.status}`,
      failureKind: "http",
    });
    throw new FetchJsonHttpError(
      message || `Request failed: ${response.status}`,
      {
        status: response.status,
        code: details.code,
        details: details.payload,
      },
    );
  }

  return response;
}

export async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithControl(input, init);
  return (await response.json()) as T;
}

type FailureDetails = {
  message: string;
  code: string | null;
  payload: unknown;
};

async function readFailureDetails(response: Response): Promise<FailureDetails> {
  const contentType = response.headers.get("content-type") ?? "";
  let message = "";
  let code: string | null = null;
  let payload: unknown;
  let attemptedJsonRead = false;
  if (contentType.includes("application/json")) {
    attemptedJsonRead = true;
    try {
      payload = await response.json();
      const body = payload as { detail?: unknown; message?: unknown; code?: unknown };
      if (typeof body.detail === "string") {
        message = body.detail;
        code = typeof body.code === "string" ? body.code : null;
      } else if (body.detail && typeof body.detail === "object") {
        const detail = body.detail as { code?: unknown };
        code = typeof detail.code === "string" ? detail.code : null;
        message = JSON.stringify({ detail: body.detail });
      } else if (typeof body.message === "string") {
        message = body.message;
        code = typeof body.code === "string" ? body.code : null;
      }
    } catch {
      message = "";
      payload = undefined;
    }
  }
  if (!message && !attemptedJsonRead) {
    message = await response.text();
  }
  return { message, code, payload };
}
