import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { ConfigSummary } from "../api/types";
import {
  dictionaryDomainsQueryKey,
  normalizeDictionaryDomains,
  type DictionaryDomainId,
} from "./dictionaryDomainIds";
import type { Language, TranslationKey } from "./dictionaryTypes";
import {
  dictionaryTableForLang,
  loadDictionaryDomains,
  type DictionaryLangTable,
} from "./loadDictionaryDomains";

const statusKeyMap: Record<string, TranslationKey> = {
  idle: "status_idle",
  running: "status_running",
  failed: "status_failed",
  partial: "status_partial",
  waiting: "status_waiting",
  inconclusive: "status_inconclusive",
  done: "status_done",
  success: "status_success",
  queued: "status_queued",
  pending: "status_pending",
  timeout: "status_timeout",
  timed_out: "status_timeout",
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
  "manual_approved": "status_manual_approved",
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

const intakeModeKeyMap: Record<string, TranslationKey> = {
  auto: "intakeAuto",
  manual_review: "intakeManualReview",
};

const viewKeyMap: Record<string, TranslationKey> = {
  live: "live",
  overview: "live",
  runs: "runs",
  library: "library",
  review: "reviewWorkspace",
};

const decisionKeyMap: Record<string, TranslationKey> = {
  PROMOTE: "decision_promote",
  HOLD: "decision_hold",
  ROLLBACK: "decision_rollback",
  REJECT: "decision_reject",
  INCONCLUSIVE: "decision_inconclusive",
};

const riskKeyMap: Record<string, TranslationKey> = {
  pending_review: "risk_pendingReview",
  none: "risk_none",
  low: "risk_low",
  medium: "risk_medium",
  high: "risk_high",
};

const workbenchSourceKeyMap: Record<string, TranslationKey> = {
  bundle: "workbenchSourceBundle",
  dataset: "workbenchSourceDataset",
  unknown: "workbenchSourceUnknown",
};

const proposalActionKeyMap: Record<string, TranslationKey> = {
  apply: "actionApply",
  activate: "actionActivate",
  rollback: "actionRollback",
};

const sourceKindKeyMap: Record<string, TranslationKey> = {
  dataset: "sourceDataset",
  bundle: "sourceBundle",
};

export type UseAppI18nOptions = {
  /**
   * Domain packs to load (core is always included).
   * Omit for full dictionary (compat). Prefer route-scoped packs for D1 ROI.
   */
  domains?: readonly DictionaryDomainId[];
};

const EMPTY_TABLE: DictionaryLangTable = {};

export function useAppI18n(options?: UseAppI18nOptions) {
  const domains = useMemo(
    () => normalizeDictionaryDomains(options?.domains),
    // serialize for stable dep when callers pass inline arrays
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dictionaryDomainsQueryKey(normalizeDictionaryDomains(options?.domains))],
  );

  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
  });

  const dictionaryQuery = useQuery({
    queryKey: ["i18n", "dictionary-domains", dictionaryDomainsQueryKey(domains)],
    queryFn: () => loadDictionaryDomains(domains),
    staleTime: Infinity,
    gcTime: Infinity,
  });

  const lang: Language = configQuery.data?.language === "en" ? "en" : "zh";
  const table = dictionaryQuery.data
    ? dictionaryTableForLang(dictionaryQuery.data, lang)
    : EMPTY_TABLE;

  function t(key: TranslationKey): string {
    return table[key] ?? String(key);
  }

  function statusLabel(status: string): string {
    const key = statusKeyMap[status];
    return key ? t(key) : status.replaceAll("_", " ");
  }

  function intakeModeLabel(mode: string): string {
    const key = intakeModeKeyMap[mode];
    return key ? t(key) : mode.replaceAll("_", " ");
  }

  function viewLabel(view: string): string {
    const key = viewKeyMap[view];
    return key ? t(key) : view;
  }

  function decisionLabel(decision: string): string {
    const key = decisionKeyMap[String(decision || "").trim().toUpperCase()];
    return key ? t(key) : decision;
  }

  function riskLabel(risk: string): string {
    const key = riskKeyMap[String(risk || "").trim().toLowerCase()];
    return key ? t(key) : risk.replaceAll("_", " ");
  }

  function workbenchSourceLabel(source: string): string {
    const key = workbenchSourceKeyMap[String(source || "").trim().toLowerCase()];
    return key ? t(key) : source.replaceAll("_", " ");
  }

  function proposalActionLabel(action: string): string {
    const key = proposalActionKeyMap[String(action || "").trim().toLowerCase()];
    return key ? t(key) : action.replaceAll("_", " ");
  }

  function sourceKindLabel(source: string): string {
    const key = sourceKindKeyMap[String(source || "").trim().toLowerCase()];
    return key ? t(key) : source.replaceAll("_", " ");
  }

  return {
    lang,
    t,
    statusLabel,
    intakeModeLabel,
    viewLabel,
    decisionLabel,
    riskLabel,
    workbenchSourceLabel,
    proposalActionLabel,
    sourceKindLabel,
    dictionaryDomains: domains,
    dictionaryReady: Boolean(dictionaryQuery.data),
  };
}
