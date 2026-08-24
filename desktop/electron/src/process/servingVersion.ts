import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { launcherPortsPath, preferredWorkbenchPort, readLauncherStateFile } from "./workbenchBackend.js";
import { workbenchHealthUrl } from "./workbenchBackendHealth.js";

export const WORKBENCH_API_CONTRACT_VERSION = "v1";

export type ServingVersionInspection = {
  ok: boolean;
  reason: string;
  port: number;
  buildKey?: string;
  release?: string;
  apiContractVersion?: string;
  backendPid?: number;
  health?: Record<string, unknown>;
};

type ServingVersionInput = {
  workspaceRoot: string;
  port?: number;
  expectedBuildKey?: string;
  expectedRelease?: string;
  fetchHealth?: (url: string) => Promise<{ status: number; json?: () => Promise<unknown> }>;
  readActive?: (workspaceRoot: string) => { buildKey: string; release: string };
  currentCode?: (workspaceRoot: string) => { head: string; dirtyTreeDigest: string };
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeRelease(value: unknown): string {
  const text = String(value || "").trim();
  return text.startsWith("release-") ? text : "";
}

function activeFrontendRelease(workspaceRoot: string): { buildKey: string; release: string } {
  try {
    const payload = JSON.parse(readFileSync(join(workspaceRoot, "web", ".vibelution-builds", "active.json"), "utf8")) as unknown;
    if (!isRecord(payload)) {
      return { buildKey: "", release: "" };
    }
    return {
      buildKey: String(payload.buildKey || "").trim(),
      release: normalizeRelease(payload.release)
    };
  } catch {
    return { buildKey: "", release: "" };
  }
}

function currentBackendCode(workspaceRoot: string): { head: string; dirtyTreeDigest: string } {
  const git = (args: string[]): string => {
    try {
      return execFileSync("git", args, {
        cwd: workspaceRoot,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
        timeout: 10_000
      }).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    } catch {
      return "";
    }
  };
  const status = git(["status", "--porcelain=v1", "--untracked-files=all"]).replace(/\n+$/g, "");
  return {
    head: git(["rev-parse", "HEAD"]).trim(),
    dirtyTreeDigest: createHash("sha256").update(status, "utf8").digest("hex")
  };
}

async function defaultFetchHealth(url: string): Promise<{ status: number; json?: () => Promise<unknown> }> {
  return await fetch(url, {
    method: "GET",
    redirect: "manual",
    signal: AbortSignal.timeout(1500)
  });
}

function servingHealthPayload(body: Record<string, unknown>): {
  apiContractVersion: string;
  buildKey: string;
  release: string;
  backendPid: number;
  code: Record<string, unknown>;
} | null {
  const serving = isRecord(body.serving) ? body.serving : null;
  const frontend = serving && isRecord(serving.frontend) ? serving.frontend : null;
  const backend = serving && isRecord(serving.backend)
    ? serving.backend
    : isRecord(body.backendCodeFingerprint)
      ? body.backendCodeFingerprint
      : null;
  const apiContractVersion = String(body.apiContractVersion || serving?.apiContractVersion || "").trim();
  const buildKey = String(frontend?.buildKey || body.servingBuildKey || "").trim();
  const release = normalizeRelease(frontend?.release || body.servingRelease);
  const backendPid = Number(body.pid || backend?.pid || 0);
  if (!apiContractVersion || !buildKey || !release || !backend || !Number.isFinite(backendPid) || backendPid <= 0) {
    return null;
  }
  if (Number(backend.pid || 0) !== backendPid || !String(backend.head || "").trim()) {
    return null;
  }
  if (!String(backend.dirtyTreeDigest || "").trim() || Number(backend.createTime || 0) <= 0 || !String(backend.executable || "").trim()) {
    return null;
  }
  return { apiContractVersion, buildKey, release, backendPid, code: backend };
}

export async function inspectWorkbenchServingVersion(input: ServingVersionInput): Promise<ServingVersionInspection> {
  const port = Math.trunc(input.port || preferredWorkbenchPort({ workspaceRoot: input.workspaceRoot }));
  if (!Number.isFinite(port) || port <= 0) {
    return { ok: false, reason: "invalid_backend_port", port };
  }
  let response: { status: number; json?: () => Promise<unknown> };
  try {
    response = await (input.fetchHealth || defaultFetchHealth)(workbenchHealthUrl(port));
  } catch {
    return { ok: false, reason: "health_unreachable", port };
  }
  if (response.status !== 200 || typeof response.json !== "function") {
    return { ok: false, reason: "health_not_ready", port };
  }
  let raw: unknown;
  try {
    raw = await response.json();
  } catch {
    return { ok: false, reason: "health_invalid_json", port };
  }
  if (!isRecord(raw) || raw.status !== "ok" || raw.routesReady !== true) {
    return { ok: false, reason: "health_not_ready", port };
  }
  const serving = servingHealthPayload(raw);
  if (!serving) {
    return { ok: false, reason: "serving_contract_missing", port, health: raw };
  }
  if (serving.apiContractVersion !== WORKBENCH_API_CONTRACT_VERSION) {
    return {
      ok: false,
      reason: `api_contract_mismatch:${serving.apiContractVersion}`,
      port,
      apiContractVersion: serving.apiContractVersion,
      buildKey: serving.buildKey,
      release: serving.release,
      backendPid: serving.backendPid,
      health: raw
    };
  }
  const active = (input.readActive || activeFrontendRelease)(input.workspaceRoot);
  const expectedBuildKey = String(input.expectedBuildKey || active.buildKey || "").trim();
  const expectedRelease = normalizeRelease(input.expectedRelease || active.release);
  if (!expectedBuildKey || !expectedRelease) {
    return { ok: false, reason: "active_release_missing", port, health: raw };
  }
  if (serving.buildKey !== expectedBuildKey || serving.release !== expectedRelease) {
    return {
      ok: false,
      reason: "serving_release_mismatch",
      port,
      apiContractVersion: serving.apiContractVersion,
      buildKey: serving.buildKey,
      release: serving.release,
      backendPid: serving.backendPid,
      health: raw
    };
  }
  const current = (input.currentCode || currentBackendCode)(input.workspaceRoot);
  if (!current.head || !current.dirtyTreeDigest || serving.code.head !== current.head || serving.code.dirtyTreeDigest !== current.dirtyTreeDigest) {
    return {
      ok: false,
      reason: "backend_code_mismatch",
      port,
      apiContractVersion: serving.apiContractVersion,
      buildKey: serving.buildKey,
      release: serving.release,
      backendPid: serving.backendPid,
      health: raw
    };
  }
  return {
    ok: true,
    reason: "serving_version_current",
    port,
    apiContractVersion: serving.apiContractVersion,
    buildKey: serving.buildKey,
    release: serving.release,
    backendPid: serving.backendPid,
    health: raw
  };
}

export function servingVersionStateFilePort(workspaceRoot: string): number {
  const ports = readLauncherStateFile(launcherPortsPath(workspaceRoot));
  const value = Number(ports.backendPort || 0);
  return Number.isFinite(value) && value > 0 ? Math.trunc(value) : 0;
}
