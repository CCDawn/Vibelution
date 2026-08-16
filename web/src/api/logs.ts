import { fetchJson } from "./client";
import type {
  LogDeleteResponse,
  LogFileContent,
  LogRoot,
  LogTreeResponse,
  RuntimeSceneDeleteResponse,
  RuntimeSceneDetail,
  RuntimeSceneListItem,
} from "./types";

function sendJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function fetchLogRoots(): Promise<LogRoot[]> {
  return fetchJson<LogRoot[]>("/api/logs/roots");
}

export function fetchLogTree(rootId: string): Promise<LogTreeResponse> {
  return fetchJson<LogTreeResponse>(`/api/logs/tree?root=${encodeURIComponent(rootId)}`);
}

export function fetchLogContent(rootId: string, path: string): Promise<LogFileContent> {
  return fetchJson<LogFileContent>(
    `/api/logs/content?root=${encodeURIComponent(rootId)}&path=${encodeURIComponent(path)}`,
  );
}

export function clearLogFile(root: string, path: string): Promise<LogFileContent> {
  return sendJson<LogFileContent>("/api/logs/clear", "POST", { root, path });
}

export function deleteLogFiles(root: string, paths: string[]): Promise<LogDeleteResponse> {
  return sendJson<LogDeleteResponse>("/api/logs/delete", "POST", { root, paths });
}

export function fetchRuntimeSceneList(): Promise<RuntimeSceneListItem[]> {
  return fetchJson<RuntimeSceneListItem[]>("/api/logs/runtime-scenes");
}

export function fetchRuntimeSceneDetail(sceneId: string): Promise<RuntimeSceneDetail> {
  return fetchJson<RuntimeSceneDetail>(
    `/api/logs/runtime-scenes/${encodeURIComponent(sceneId)}`,
  );
}

export function fetchRuntimeSceneLogContent(sceneId: string, path: string): Promise<LogFileContent> {
  return fetchJson<LogFileContent>(
    `/api/logs/runtime-scenes/${encodeURIComponent(sceneId)}/content?path=${encodeURIComponent(path)}`,
  );
}

export function deleteRuntimeScenes(sceneIds: string[]): Promise<RuntimeSceneDeleteResponse> {
  return sendJson<RuntimeSceneDeleteResponse>("/api/logs/runtime-scenes/delete", "POST", { sceneIds });
}
