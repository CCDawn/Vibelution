export const CLIENT_OPERATION_ID_HEADER = "X-Vibelution-Client-Operation-Id";

const activeClientOperationIds: string[] = [];

export function pushClientOperationContext(clientOperationId: string) {
  const normalized = String(clientOperationId || "").trim();
  if (!normalized) {
    return;
  }
  activeClientOperationIds.push(normalized);
}

export function popClientOperationContext() {
  activeClientOperationIds.pop();
}

export function currentClientOperationId(): string {
  return activeClientOperationIds[activeClientOperationIds.length - 1] ?? "";
}

export function resetClientOperationContextForTests() {
  activeClientOperationIds.length = 0;
}
