const CONTROL_TOKEN_ENDPOINT = "/api/control-token";
const CONTROL_TOKEN_HEADER_FALLBACK = "X-Vibelution-Control-Token";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const controlTokenPromises = new Map<string, Promise<{ header: string; token: string }>>();
let fetchJsonFailureReporter: ((report: FetchJsonFailureReport) => void) | null = null;

export type FetchJsonFailureReport = {
  endpoint: string;
  method: string;
  status: number | null;
  message: string;
  failureKind: "http" | "network";
};

export function resetControlTokenForTests() {
  controlTokenPromises.clear();
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

function controlOriginForRequest(input: string, method: string): string | null {
  if (!MUTATING_METHODS.has(method)) {
    return null;
  }
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

export async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
  const method = String(init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers ?? {});
  headers.set("Accept", headers.get("Accept") ?? "application/json");
  const controlOrigin = controlOriginForRequest(input, method);
  if (controlOrigin !== null) {
    const control = await getControlToken(controlOrigin);
    headers.set(control.header, control.token);
  }

  let response: Response;
  try {
    response = await fetch(input, {
      ...init,
      headers,
      credentials: init?.credentials ?? (controlOrigin ? "include" : "same-origin"),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    reportFetchJsonFailure(input, {
      method,
      status: null,
      message: message || "Network request failed",
      failureKind: "network",
    });
    throw error;
  }

  if (!response.ok) {
    if (response.status === 403 && controlOrigin !== null) {
      clearControlToken(controlOrigin);
    }
    const contentType = response.headers.get("content-type") ?? "";
    let message = "";
    if (contentType.includes("application/json")) {
      try {
        const payload = (await response.json()) as { detail?: unknown; message?: unknown };
        if (typeof payload.detail === "string") {
          message = payload.detail;
        } else if (payload.detail && typeof payload.detail === "object") {
          message = JSON.stringify({ detail: payload.detail });
        } else if (typeof payload.message === "string") {
          message = payload.message;
        }
      } catch {
        message = "";
      }
    }
    if (!message) {
      message = await response.text();
    }
    reportFetchJsonFailure(input, {
      method,
      status: response.status,
      message: message || `Request failed: ${response.status}`,
      failureKind: "http",
    });
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}
