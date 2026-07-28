import { fetchJson } from "./client";
import type { ChallengeQuestionRunDetailPayload } from "./types";

export function getChallengeQuestionRunDetail(
  teamId: string,
  questionId: string,
  runId = "",
) {
  const query = runId ? `?runId=${encodeURIComponent(runId)}` : "";
  return fetchJson<ChallengeQuestionRunDetailPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/challenge-program/questions/${encodeURIComponent(questionId)}${query}`,
  );
}
