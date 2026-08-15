import { fetchJson } from "./client";
import type {
  UserMarkdownSpaceImportPayload,
  UserMarkdownSpaceImportPreviewPayload,
  UserMarkdownSpaceListPayload,
  UserMarkdownSpacePageListPayload,
  UserMarkdownSpacePagePayload,
  UserMarkdownSpaceSearchPayload,
} from "./types";

function endpointWithUserId(path: string, userId: string, extras?: Record<string, string | number>) {
  const params = new URLSearchParams({ userId });
  for (const [key, value] of Object.entries(extras ?? {})) {
    const text = String(value ?? "").trim();
    if (text) {
      params.set(key, text);
    }
  }
  return `${path}?${params.toString()}`;
}

function sendJson<T>(url: string, body: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listUserMarkdownSpaces<T = UserMarkdownSpaceListPayload>(
  userId: string,
): Promise<T> {
  return fetchJson<T>(endpointWithUserId("/api/user-content/markdown-spaces", userId));
}

export function listUserMarkdownSpacePages<T = UserMarkdownSpacePageListPayload>(
  spaceId: string,
  options: { userId: string; query?: string; tag?: string },
): Promise<T> {
  return fetchJson<T>(
    endpointWithUserId(
      `/api/user-content/markdown-spaces/${encodeURIComponent(spaceId)}/pages`,
      options.userId,
      {
        query: options.query ?? "",
        tag: options.tag ?? "",
      },
    ),
  );
}

export function fetchUserMarkdownSpacePage<T = UserMarkdownSpacePagePayload>(
  spaceId: string,
  pageId: string,
  options: { userId: string },
): Promise<T> {
  return fetchJson<T>(
    endpointWithUserId(
      `/api/user-content/markdown-spaces/${encodeURIComponent(spaceId)}/pages/${encodeURIComponent(pageId)}`,
      options.userId,
    ),
  );
}

export function searchUserMarkdownSpaces<T = UserMarkdownSpaceSearchPayload>(options: {
  userId: string;
  query: string;
  spaceId?: string;
  limit?: number;
}): Promise<T> {
  return fetchJson<T>(
    endpointWithUserId("/api/user-content/markdown-spaces/search", options.userId, {
      query: options.query,
      spaceId: options.spaceId ?? "",
      limit: options.limit ?? 10,
    }),
  );
}

export function previewUserMarkdownSpaceImport<T = UserMarkdownSpaceImportPreviewPayload>(body: {
  sourcePath: string;
  userId: string;
}): Promise<T> {
  return sendJson<T>("/api/user-content/markdown-spaces/import-preview", body);
}

export function importUserMarkdownSpace<T = UserMarkdownSpaceImportPayload>(body: {
  sourcePath: string;
  spaceName: string;
  userId: string;
}): Promise<T> {
  return sendJson<T>("/api/user-content/markdown-spaces/import", body);
}
