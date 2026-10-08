import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { FINANCE_WORKSPACE_GROUPS } from "./financeWorkspaceNavigation";

const options = {
  area: FINANCE_WORKSPACE_GROUPS.flatMap(group => group.areas.map(area => area.id)),
  tab: ["research", "overview", "news", "fundamentals", "report"],
  asideTab: ["process", "evidence"],
  portfolioSource: ["manual", "paper"],
  reviewTab: ["trades", "validation", "backtest", "history", "cases"],
  taskTab: ["records", "batches", "schedules"],
  reportCollection: ["completed", "active", "archived"],
} as const;
const defaults = { area: "workspace", tab: "research", asideTab: "process", portfolioSource: "manual", reviewTab: "trades", taskTab: "records", reportCollection: "completed" };
export type FinanceWorkspaceNavigation = typeof defaults & {
  preparing: boolean;
  selectedReport: { sessionId: string; turnId: string } | null;
};

export function parseFinanceWorkspaceNavigation(search: string): FinanceWorkspaceNavigation {
  const params = new URLSearchParams(search);
  const values = { ...defaults };
  for (const key of Object.keys(options) as (keyof typeof options)[]) {
    const value = params.get(`finance_${key}`);
    if (value && (options[key] as readonly string[]).includes(value)) values[key] = value;
  }
  const sessionId = params.get("finance_report_session"), turnId = params.get("finance_report_turn");
  return { ...values, preparing: values.area === "workspace" && values.tab === "overview" && params.get("finance_prepare") === "1",
    selectedReport: sessionId && turnId ? { sessionId, turnId } : null };
}

export function serializeFinanceWorkspaceNavigation(search: string, value: FinanceWorkspaceNavigation) {
  const params = new URLSearchParams(search);
  for (const key of Object.keys(options) as (keyof typeof options)[]) {
    if (value[key] === defaults[key]) params.delete(`finance_${key}`);
    else params.set(`finance_${key}`, value[key]);
  }
  if (value.preparing && value.area === "workspace" && value.tab === "overview") params.set("finance_prepare", "1");
  else params.delete("finance_prepare");
  if (value.selectedReport) {
    params.set("finance_report_session", value.selectedReport.sessionId);
    params.set("finance_report_turn", value.selectedReport.turnId);
  } else { params.delete("finance_report_session"); params.delete("finance_report_turn"); }
  return params.toString();
}

/** Finance view parameters only; native session selection stays with useChatRouteSelection. */
export function useFinanceWorkspaceNavigation() {
  const location = useLocation(), navigate = useNavigate();
  const source = `${location.key}:${location.search}`;
  const latest = useRef({ source, search: location.search });
  if (latest.current.source !== source) latest.current = { source, search: location.search };
  const pendingSession = useRef<{ sessionId: string; patch: Partial<FinanceWorkspaceNavigation> } | null>(null);
  const scheduled = useRef<{ source: string; replace: boolean } | null>(null);
  function update(patch: Partial<FinanceWorkspaceNavigation>, replace = false) {
    const value = { ...parseFinanceWorkspaceNavigation(latest.current.search), ...patch };
    const search = serializeFinanceWorkspaceNavigation(latest.current.search, value);
    if (search === latest.current.search.replace(/^\?/, "")) return;
    latest.current.search = search;
    if (scheduled.current) { scheduled.current.replace = replace; return; }
    scheduled.current = { source, replace };
    queueMicrotask(() => {
      const pending = scheduled.current;
      scheduled.current = null;
      if (!pending || pending.source !== latest.current.source) return;
      const search = latest.current.search;
      navigate({ pathname: location.pathname, search: search ? `?${search}` : "" }, { replace: pending.replace });
    });
  }
  useEffect(() => {
    const pending = pendingSession.current;
    if (!pending) return;
    pendingSession.current = null;
    if (new URLSearchParams(location.search).get("session") === pending.sessionId) update(pending.patch, true);
  }, [location.key, location.search]);
  function showSession(sessionId: string) {
    const patch = { area: "workspace", tab: "research", asideTab: "process", preparing: false, selectedReport: null };
    if (new URLSearchParams(latest.current.search).get("session") === sessionId) update(patch);
    else pendingSession.current = { sessionId, patch };
  }
  return { ...parseFinanceWorkspaceNavigation(location.search), update, showSession };
}
