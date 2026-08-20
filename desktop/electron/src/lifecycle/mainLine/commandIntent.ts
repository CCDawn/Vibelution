import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { randomBytes } from "node:crypto";

import type { MainLineIntentSnapshot } from "./commandQueue.js";

export const MAIN_LINE_INTENT_FILE = "main_line_intent.json";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function mainLineIntentPath(runtimeManagerDir: string): string {
  return join(runtimeManagerDir, MAIN_LINE_INTENT_FILE);
}

export async function readMainLineIntent(runtimeManagerDir: string): Promise<MainLineIntentSnapshot | null> {
  try {
    const payload = JSON.parse(await readFile(mainLineIntentPath(runtimeManagerDir), "utf8")) as unknown;
    if (!isRecord(payload) || payload.schemaVersion !== 1) {
      return null;
    }
    const desiredState = payload.desiredState === "closed" ? "closed" : payload.desiredState === "open" ? "open" : "";
    const operation = String(payload.operation || "").trim();
    const commandId = String(payload.commandId || "").trim();
    if (!desiredState || !operation || !commandId) {
      return null;
    }
    return {
      schemaVersion: 1,
      desiredState,
      operation: operation as MainLineIntentSnapshot["operation"],
      commandId,
      updatedAt: String(payload.updatedAt || ""),
    };
  } catch {
    return null;
  }
}

export async function writeMainLineIntent(
  runtimeManagerDir: string,
  intent: MainLineIntentSnapshot,
): Promise<void> {
  const target = mainLineIntentPath(runtimeManagerDir);
  await mkdir(dirname(target), { recursive: true });
  const tempPath = join(dirname(target), `.${randomBytes(6).toString("hex")}.${MAIN_LINE_INTENT_FILE}`);
  await writeFile(tempPath, `${JSON.stringify(intent, null, 2)}\n`, "utf8");
  await rename(tempPath, target);
}
