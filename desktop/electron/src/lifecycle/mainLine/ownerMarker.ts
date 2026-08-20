import { mkdir, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { randomBytes } from "node:crypto";

export const MAIN_LINE_QUEUE_OWNER_FILE = "main_line_queue_owner.json";

export type MainLineQueueOwnerMarker = {
  schemaVersion: 1;
  owner: "electron";
  pid: number;
  updatedAt: string;
};

export function mainLineQueueOwnerPath(runtimeManagerDir: string): string {
  return join(runtimeManagerDir, MAIN_LINE_QUEUE_OWNER_FILE);
}

export async function writeMainLineQueueOwnerMarker(
  runtimeManagerDir: string,
  input: { pid?: number; nowMs?: number } = {},
): Promise<MainLineQueueOwnerMarker> {
  const marker: MainLineQueueOwnerMarker = {
    schemaVersion: 1,
    owner: "electron",
    pid: Math.trunc(input.pid ?? process.pid),
    updatedAt: new Date(input.nowMs ?? Date.now()).toISOString(),
  };
  const target = mainLineQueueOwnerPath(runtimeManagerDir);
  await mkdir(dirname(target), { recursive: true });
  const tempPath = join(dirname(target), `.${randomBytes(6).toString("hex")}.${MAIN_LINE_QUEUE_OWNER_FILE}`);
  await writeFile(tempPath, `${JSON.stringify(marker, null, 2)}\n`, "utf8");
  await rename(tempPath, target);
  return marker;
}
