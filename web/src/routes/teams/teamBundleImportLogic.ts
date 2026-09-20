/**
 * Team bundle import wizard state machine (pure reducer, no network).
 * Network orchestration lives in useTeamBundleImportActions.
 */
import type { TeamBundle, TeamBundleImportReport } from "../../api/types";

export type TeamBundleImportPhase = "idle" | "parsing" | "preview" | "importing" | "done" | "error";

export type TeamBundleImportState = {
  phase: TeamBundleImportPhase;
  bundle: TeamBundle | null;
  report: TeamBundleImportReport | null;
  errorMessage: string;
};

export type TeamBundleImportAction =
  | { type: "reset" }
  | { type: "load_started" }
  | { type: "load_succeeded"; bundle: TeamBundle; report: TeamBundleImportReport }
  | { type: "load_failed"; message: string }
  | { type: "confirm_started" }
  | { type: "confirm_succeeded"; report: TeamBundleImportReport }
  | { type: "confirm_failed"; message: string };

export function initialTeamBundleImportState(): TeamBundleImportState {
  return { phase: "idle", bundle: null, report: null, errorMessage: "" };
}

export function teamBundleImportReducer(
  state: TeamBundleImportState,
  action: TeamBundleImportAction,
): TeamBundleImportState {
  switch (action.type) {
    case "reset":
      return initialTeamBundleImportState();
    case "load_started":
      return { ...state, phase: "parsing", errorMessage: "" };
    case "load_succeeded":
      return {
        phase: "preview",
        bundle: action.bundle,
        report: action.report,
        errorMessage: "",
      };
    case "load_failed":
      return { ...state, phase: "error", errorMessage: action.message };
    case "confirm_started":
      return { ...state, phase: "importing", errorMessage: "" };
    case "confirm_succeeded":
      return { ...state, phase: "done", report: action.report };
    case "confirm_failed":
      return { ...state, phase: "error", errorMessage: action.message };
  }
}

/** True when the confirm step must re-send confirm=true (newer schema gate). */
export function reportNeedsSchemaConfirm(report: TeamBundleImportReport | null): boolean {
  return report?.status === "pending";
}
