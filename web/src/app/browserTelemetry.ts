import { clearControlToken, getControlToken } from "../api/client";
import { getPageInstanceId } from "./pageInstance";

export type BrowserTelemetryEventInput = {
  phase: string;
  eventCode: string;
  message: string;
  level?: "info" | "warning" | "error";
  fields?: Record<string, unknown>;
};

const TELEMETRY_ENDPOINT = "/api/runtime/browser-telemetry";
const BYTES_PER_MEBIBYTE = 1024 * 1024;
const MAX_FAILED_TELEMETRY_BODIES = 20;

type ControlToken = { header: string; token: string };

const failedTelemetryBodies: string[] = [];
let flushingFailedTelemetry = false;

type BrowserPerformanceWithMemory = Performance & {
  memory?: {
    usedJSHeapSize?: number;
    totalJSHeapSize?: number;
    jsHeapSizeLimit?: number;
  };
};

function truncateText(value: string, limit: number): string {
  const text = String(value ?? "");
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, Math.max(0, limit - 3))}...`;
}

function compactText(value: string, limit: number): string {
  return truncateText(String(value ?? "").replace(/\s+/g, " ").trim(), limit);
}

function compactLength(value: string): number {
  return String(value ?? "").replace(/\s+/g, " ").trim().length;
}

function summarizeUnknown(value: unknown, limit = 240): string {
  if (value instanceof Error) {
    return truncateText(value.stack || value.message || value.name, limit);
  }
  if (typeof value === "string") {
    return truncateText(value, limit);
  }
  try {
    return truncateText(JSON.stringify(value), limit);
  } catch {
    return truncateText(String(value), limit);
  }
}

export function summarizeConsoleArgs(args: unknown[], limit = 240): string {
  return truncateText(args.map((item) => summarizeUnknown(item, Math.max(limit, 120))).join(" | "), limit);
}

export function collectBrowserPageSnapshot(): Record<string, unknown> {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return {};
  }

  const port = window.location.port || "";
  const activeNav = document.querySelector<HTMLAnchorElement>("header nav a[aria-current='page']");
  const heading = document.querySelector("h1");
  const main = document.querySelector("main");
  const shell = document.querySelector<HTMLElement>("[data-browser-role], [data-shell]");
  const browserRole = shell?.dataset.browserRole || (shell?.dataset.shell === "launcher" ? "launcher_control_surface" : "workbench");
  const telemetrySurface = port === "5173" || port === "5174"
    ? "vite_dev"
    : browserRole === "launcher_control_surface"
      ? "managed_launcher"
      : "managed_workbench";

  return {
    pageInstanceId: getPageInstanceId(),
    href: window.location.href,
    origin: window.location.origin,
    hostname: window.location.hostname,
    port,
    telemetrySurface,
    browserRole,
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
    title: document.title,
    readyState: document.readyState,
    visibilityState: document.visibilityState,
    online: typeof navigator === "undefined" ? true : navigator.onLine,
    activeNavHref: activeNav?.getAttribute("href") ?? "",
    activeNavText: compactText(activeNav?.textContent ?? "", 80),
    heading: compactText(heading?.textContent ?? "", 120),
    mainTextLength: compactLength(main?.textContent ?? ""),
  };
}

export function collectBrowserMemorySnapshot(): Record<string, unknown> {
  if (typeof performance === "undefined") {
    return {
      available: false,
    };
  }

  const memory = (performance as BrowserPerformanceWithMemory).memory;
  if (!memory) {
    return {
      available: false,
    };
  }

  const usedJSHeapSize = finiteNumber(memory.usedJSHeapSize);
  const totalJSHeapSize = finiteNumber(memory.totalJSHeapSize);
  const jsHeapSizeLimit = finiteNumber(memory.jsHeapSizeLimit);
  return {
    available: true,
    usedJSHeapMB: toMegabytes(usedJSHeapSize),
    totalJSHeapMB: toMegabytes(totalJSHeapSize),
    jsHeapLimitMB: toMegabytes(jsHeapSizeLimit),
    usedJSHeapBytes: usedJSHeapSize,
    totalJSHeapBytes: totalJSHeapSize,
    jsHeapLimitBytes: jsHeapSizeLimit,
  };
}

function warnTelemetryDeliveryFailure(error: unknown): void {
  // Never post another telemetry event here: delivery failure must not recurse.
  if (typeof console !== "undefined" && typeof console.warn === "function") {
    console.warn("browser telemetry delivery failed", compactText(summarizeUnknown(error, 180), 200));
  }
}

function rememberFailedTelemetryBody(body: string, error: unknown): void {
  warnTelemetryDeliveryFailure(error);
  failedTelemetryBodies.push(body);
  while (failedTelemetryBodies.length > MAX_FAILED_TELEMETRY_BODIES) {
    failedTelemetryBodies.shift();
  }
}

function postTelemetryBody(control: ControlToken, body: string): Promise<Response> {
  return fetch(TELEMETRY_ENDPOINT, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      [control.header]: control.token,
    },
    body,
    credentials: "same-origin",
    keepalive: true,
  });
}

async function flushFailedTelemetryBodies(control: ControlToken): Promise<void> {
  if (flushingFailedTelemetry || failedTelemetryBodies.length === 0) {
    return;
  }
  flushingFailedTelemetry = true;
  try {
    while (failedTelemetryBodies.length > 0) {
      const pending = failedTelemetryBodies[0];
      let response: Response;
      try {
        response = await postTelemetryBody(control, pending);
      } catch (error) {
        warnTelemetryDeliveryFailure(error);
        return;
      }
      if (response.status === 403) {
        clearControlToken();
        return;
      }
      if (!response.ok) {
        warnTelemetryDeliveryFailure(`HTTP ${response.status}`);
        return;
      }
      failedTelemetryBodies.shift();
    }
  } finally {
    flushingFailedTelemetry = false;
  }
}

export function peekBrowserTelemetryDeliveryBufferForTests(): readonly string[] {
  return failedTelemetryBodies.slice();
}

export function resetBrowserTelemetryDeliveryBufferForTests(): void {
  failedTelemetryBodies.length = 0;
  flushingFailedTelemetry = false;
}

export function postBrowserTelemetry(
  payload: BrowserTelemetryEventInput,
  _options?: { preferBeacon?: boolean },
) {
  if (typeof window === "undefined") {
    return;
  }

  const clientOccurredAt = new Date().toISOString();
  const clientMonotonicMs = typeof performance === "undefined" || typeof performance.now !== "function"
    ? Date.now()
    : performance.now();
  const body = JSON.stringify({
    ...payload,
    fields: {
      ...(payload.fields ?? {}),
      clientOccurredAt,
      clientMonotonicMs,
    },
  });
  void getControlToken()
    .then(async (control) => {
      const response = await postTelemetryBody(control, body);
      if (response.status === 403) {
        clearControlToken();
        return;
      }
      if (!response.ok) {
        rememberFailedTelemetryBody(body, `HTTP ${response.status}`);
        return;
      }
      await flushFailedTelemetryBodies(control);
    })
    .catch((error: unknown) => {
      rememberFailedTelemetryBody(body, error);
    });
}

function finiteNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
}

function toMegabytes(value: number): number {
  return Math.round((value / BYTES_PER_MEBIBYTE) * 10) / 10;
}
