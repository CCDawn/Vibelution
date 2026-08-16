import { fetchJson } from "./client";
import type {
  SelfEvolutionAutonomousLoopActionRequest,
  SelfEvolutionAutonomousLoopRun,
  SelfEvolutionAutonomousLoopStartRequest,
} from "./types";

export function startSelfEvolutionAutonomousLoop(
  payload: SelfEvolutionAutonomousLoopStartRequest,
): Promise<SelfEvolutionAutonomousLoopRun> {
  return fetchJson<SelfEvolutionAutonomousLoopRun>(
    "/api/evolution/self/autonomous-runs",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function executeSelfEvolutionAutonomousLoopAction(
  payload: SelfEvolutionAutonomousLoopActionRequest,
): Promise<SelfEvolutionAutonomousLoopRun> {
  return fetchJson<SelfEvolutionAutonomousLoopRun>(
    `/api/evolution/self/autonomous-runs/${encodeURIComponent(payload.runId)}/actions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: payload.action,
        comment: payload.comment ?? "",
      }),
    },
  );
}

export function fetchSelfEvolutionAutonomousActiveRun<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/self/autonomous-runs/active");
}

export function fetchSelfEvolutionAutonomousLatestRun<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/self/autonomous-runs/latest");
}

export function fetchSelfEvolutionAutonomousRun<T>(runId: string): Promise<T> {
  return fetchJson<T>(
    `/api/evolution/self/autonomous-runs/${encodeURIComponent(runId)}`,
  );
}
