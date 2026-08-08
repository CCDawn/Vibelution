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

export type ChallengeQuestionRunStatusPayload = {
  teamId: string;
  storePath: string;
  summary: {
    recordCount: number;
    validCandidateCount: number;
    validatedQuestionCount: number;
    validatedQuestionIds: string[];
    validatedOutcomeCounts: Record<string, number>;
    validatedQuestionResults: Array<{
      questionId: string;
      runId: string;
      status: string;
      validation: Record<string, unknown>;
      humanGates: Record<string, unknown>;
      outputSha256: string;
      artifactPath: string;
    }>;
    completedCount: number;
    completedQuestionIds: string[];
    latestCandidate: Record<string, unknown> | null;
  };
};

export function getChallengeQuestionRunStatus(
  teamId: string,
): Promise<ChallengeQuestionRunStatusPayload> {
  return fetchJson<ChallengeQuestionRunStatusPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/challenge-program/question-runs/status`,
  );
}
