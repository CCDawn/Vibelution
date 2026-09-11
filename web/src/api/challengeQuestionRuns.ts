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
    registeredQuestionIds: string[];
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

export type ChallengeQuestionCitationReverificationPayload = {
  /** already_passed | reverified | still_failed */
  status: string;
  record: Record<string, unknown>;
  output?: Record<string, unknown>;
  citation?: Record<string, unknown>;
  verification?: {
    verifiedSourceUrls: Record<string, boolean>;
    attemptedCount: number;
    verifiedCount: number;
  };
  summary?: Record<string, unknown>;
};

/** POST …/questions/{questionId}/runs/{runId}/reverify-citations (sanctioned repair). */
export function reverifyChallengeQuestionCitations(
  teamId: string,
  questionId: string,
  runId: string,
): Promise<ChallengeQuestionCitationReverificationPayload> {
  return fetchJson<ChallengeQuestionCitationReverificationPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/challenge-program/questions/${encodeURIComponent(questionId)}/runs/${encodeURIComponent(runId)}/reverify-citations`,
    { method: "POST" },
  );
}

export type ChallengeQuestionRegistrationRepairPayload = {
  teamId: string;
  questionId: string;
  runId: string;
  repaired: boolean;
  reason?: string;
  officialModelCall: boolean;
  record: Record<string, unknown>;
};

/** POST …/questions/{questionId}/runs/{runId}/repair-registration (sanctioned repair). */
export function repairChallengeQuestionRegistration(
  teamId: string,
  questionId: string,
  runId: string,
): Promise<ChallengeQuestionRegistrationRepairPayload> {
  return fetchJson<ChallengeQuestionRegistrationRepairPayload>(
    `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/challenge-program/questions/${encodeURIComponent(questionId)}/runs/${encodeURIComponent(runId)}/repair-registration`,
    { method: "POST" },
  );
}
