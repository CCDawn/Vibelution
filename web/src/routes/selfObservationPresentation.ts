import { ACTIVITY_CONTRACT } from "../api/generated/activityContract";
import { resolvePollingInterval } from "../app/pollingPolicy";

const contract = ACTIVITY_CONTRACT.selfObservation;
const normalize = (value: string | null | undefined) => String(value ?? "").trim().toLowerCase();

export function selfObservationIsActive(status: string | null | undefined) {
  return (contract.activeStatuses as readonly string[]).includes(normalize(status));
}

export function selfObservationStatusLabel(status: string | null | undefined, lang: "zh" | "en") {
  const labels: Readonly<Record<string, string>> = lang === "zh" ? contract.labels : contract.labelsEn;
  const key = normalize(status);
  return Object.prototype.hasOwnProperty.call(labels, key) ? labels[key] : labels.unknown;
}

export function selfObservationPollingInterval(status: string | null | undefined, pageVisible: boolean) {
  const key = normalize(status);
  const terminal = (contract.terminalStatuses as readonly string[]).includes(key);
  // Unknown nonempty states retain the existing fast recovery polling policy.
  return resolvePollingInterval(pageVisible, key && !terminal ? 2_000 : 10_000);
}
