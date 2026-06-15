import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { ConfigSummary } from "../api/types";
import { shellDictionary, type Language, type ShellTranslationKey } from "./shellDictionary";

const statusKeyMap: Record<string, ShellTranslationKey> = {
  idle: "status_idle",
  running: "status_running",
  failed: "status_failed",
  waiting: "status_waiting",
  timeout: "status_timeout",
  timed_out: "status_timeout",
  inconclusive: "status_inconclusive",
  done: "status_done",
  success: "status_success",
  queued: "status_queued",
  pending: "status_pending",
  planning: "status_planning",
  ready: "status_ready",
  reading: "status_reading",
  editing: "status_editing",
  verifying: "status_verifying",
  paused: "status_paused",
  paused_limit: "status_paused_limit",
  needs_continue: "status_needs_continue",
  pause_requested: "status_pause_requested",
  preparing: "status_preparing",
  evaluating: "status_evaluating",
  thinking: "status_thinking",
  tooling: "status_tooling",
  answering: "status_answering",
  blocked: "status_blocked",
  caution: "status_caution",
  disabled: "status_disabled",
  stopping: "status_stopping",
  stopped_by_user: "status_stopped_by_user",
  force_stopping: "status_force_stopping",
  stop_failed: "status_stop_failed",
  failed_provider: "status_failed_provider",
  failed_runtime: "status_failed_runtime",
  cancelled: "status_cancelled",
  available: "status_available",
  unavailable: "status_unavailable",
  submitted: "status_submitted",
  needs_input: "status_needs_input",
  "manual-approved": "status_manual_approved",
  manual_approved: "status_manual_approved",
  approved: "status_approved",
  rejected: "status_rejected",
  positive: "status_positive",
  negative: "status_negative",
  discard: "status_discard",
  proposed: "status_proposed",
  applied: "status_applied",
  active: "status_active",
  superseded: "status_superseded",
  rolled_back: "status_rolled_back",
  missing: "status_missing",
};

export function useShellI18n() {
  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
  });

  const lang: Language = configQuery.data?.language === "en" ? "en" : "zh";
  const table = shellDictionary[lang];

  function t(key: ShellTranslationKey): string {
    return table[key];
  }

  function statusLabel(status: string): string {
    const key = statusKeyMap[status];
    return key ? table[key] : status.replaceAll("_", " ");
  }

  return {
    lang,
    t,
    statusLabel,
  };
}
