const PAGE_INSTANCE_PREFIX = "page";

let currentPageInstanceId = "";

export function createPageInstanceId(nowMs = Date.now(), randomValue = Math.random()): string {
  const timePart = Math.max(0, Math.floor(nowMs)).toString(36);
  const randomPart = Math.max(0, randomValue).toString(36).slice(2, 8) || "000000";
  return `${PAGE_INSTANCE_PREFIX}-${timePart}-${randomPart.padEnd(6, "0").slice(0, 6)}`;
}

export function getPageInstanceId(): string {
  if (!currentPageInstanceId) {
    currentPageInstanceId = createPageInstanceId();
  }
  return currentPageInstanceId;
}

export function resetPageInstanceIdForTests(): void {
  currentPageInstanceId = "";
}
