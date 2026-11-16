import { fetchJson } from "./client";

export type ReadCursorScopeKind = "team" | "conversation";

export type ReadCursorEntry = {
  scopeKind: ReadCursorScopeKind;
  scopeId: string;
  readAt: string;
};

export type ReadCursorsPayload = {
  schemaVersion: number;
  cursors: ReadCursorEntry[];
  updatedAt: string;
};

export type MarkReadEntry = {
  scopeKind: ReadCursorScopeKind;
  scopeId: string;
  readAt?: string;
};

export const READ_CURSORS_QUERY_KEY = ["read-cursors"] as const;

export async function fetchReadCursors(signal?: AbortSignal): Promise<ReadCursorsPayload> {
  return fetchJson<ReadCursorsPayload>("/api/read-cursors", { signal });
}

export async function markReadCursors(
  entries: readonly MarkReadEntry[],
  signal?: AbortSignal,
): Promise<ReadCursorsPayload> {
  return fetchJson<ReadCursorsPayload>("/api/read-cursors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entries }),
    signal,
  });
}
