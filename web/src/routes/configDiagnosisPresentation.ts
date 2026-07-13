export type ConfigDiagnosisRepair = {
  kind: "provider-api-key";
  providerId: string;
};

export type ConfigDiagnosisIssueGroup = {
  id: string;
  message: string;
  references: string[];
  rawItems: string[];
  repair?: ConfigDiagnosisRepair;
};

function splitDiagnosisIssue(item: string): { reference: string; message: string } {
  const normalized = String(item || "").trim();
  const match = /^([^:]+):\s+(.+)$/.exec(normalized);
  if (!match) {
    return { reference: "", message: normalized };
  }
  return { reference: match[1]?.trim() ?? "", message: match[2]?.trim() ?? normalized };
}

function deriveDiagnosisRepair(message: string): ConfigDiagnosisRepair | undefined {
  const zhMatch = /^provider\s+(`?)([^\s`]+)\1\s+缺少 API Key$/i.exec(message);
  const enMatch = /^provider\s+(`?)([^\s`]+)\1\s+(?:is\s+)?missing\s+(?:an?\s+)?API Key$/i.exec(message);
  const providerId = (zhMatch?.[2] ?? enMatch?.[2] ?? "").trim();
  return providerId ? { kind: "provider-api-key", providerId } : undefined;
}

export function groupConfigDiagnosisIssues(items: readonly string[]): ConfigDiagnosisIssueGroup[] {
  const groups = new Map<string, ConfigDiagnosisIssueGroup>();

  for (const rawItem of items) {
    const { reference, message } = splitDiagnosisIssue(rawItem);
    if (!message) continue;

    const existing = groups.get(message);
    if (existing) {
      existing.rawItems.push(rawItem);
      if (reference && !existing.references.includes(reference)) {
        existing.references.push(reference);
      }
      continue;
    }

    groups.set(message, {
      id: message,
      message,
      references: reference ? [reference] : [],
      rawItems: [rawItem],
      repair: deriveDiagnosisRepair(message),
    });
  }

  return [...groups.values()];
}
