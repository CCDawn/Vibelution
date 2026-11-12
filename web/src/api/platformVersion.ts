import { fetchJson } from "./client";

export type PlatformVersionEntry = {
  seq: number;
  version: string;
  build: number;
  head_sha: string;
  head_subject: string;
  kind: string;
  summary: string;
  changelog_digest: string;
  recorded_at: string;
  anchor: string;
};

export type PlatformVersionCadence = {
  major: number;
  minor: number;
  patch: number;
  patchPerMinor: number;
  minorPerMajor: number;
};

export type PlatformVersionSnapshot = {
  ledgerPath: string;
  currentVersion: string;
  build: number;
  cadence: PlatformVersionCadence;
  progress: { patchInMinor: number; minorInMajor: number };
  fileVersion: string;
  fileBehind: boolean;
  unreleasedPending: boolean;
  unreleasedSummary: string;
  lastError?: string;
  entries: PlatformVersionEntry[];
};

export type PlatformVersionFrame = {
  type: string;
  snapshot?: PlatformVersionSnapshot;
  entry?: PlatformVersionEntry;
};

export function fetchPlatformVersionSnapshot(): Promise<PlatformVersionSnapshot> {
  return fetchJson<PlatformVersionSnapshot>("/api/platform-version");
}

/**
 * Live position stream. Settlement is owned by the backend watcher; this only
 * mirrors frames, so the page never becomes a second writer of the version.
 */
export function subscribePlatformVersionEvents(
  onFrame: (frame: PlatformVersionFrame) => void,
): () => void {
  const source = new EventSource("/api/platform-version/stream");
  source.onmessage = (event) => {
    try {
      onFrame(JSON.parse(event.data) as PlatformVersionFrame);
    } catch {
      // A malformed frame must not tear down a live position stream.
    }
  };
  return () => source.close();
}
