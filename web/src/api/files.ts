import { fetchJson } from "./client";
import type { FileContent } from "./types";

export function fetchFileContent(path: string): Promise<FileContent> {
  return fetchJson<FileContent>(`/api/files/content?path=${encodeURIComponent(path)}`);
}
