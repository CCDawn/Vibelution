/**
 * Response segment presentation pure helpers (structure C3).
 * Pure: no React / DOM.
 */
import { isNoFinalAnswerStatusContent } from "./conversationInternalStatus";
import type { ResponseSegment } from "./messageResponseSegments";

export type ResponseSegmentLabelKey =
  | "responseSegmentStatus"
  | "responseSegmentCommit"
  | "responseSegmentVerification"
  | "responseSegmentCode"
  | "responseSegmentFiles"
  | "responseSegmentLogs"
  | "responseSegmentAnswer";

export function responseSegmentLabel(
  segment: Pick<ResponseSegment, "kind" | "language">,
  t: (key: ResponseSegmentLabelKey) => string,
) {
  switch (segment.kind) {
    case "status":
      return t("responseSegmentStatus");
    case "commit":
      return t("responseSegmentCommit");
    case "verification":
      return t("responseSegmentVerification");
    case "code":
      return segment.language || t("responseSegmentCode");
    case "files":
      return t("responseSegmentFiles");
    case "logs":
      return t("responseSegmentLogs");
    case "answer":
    default:
      return t("responseSegmentAnswer");
  }
}

export function isResponseSegmentCodeLike(segment: Pick<ResponseSegment, "kind" | "language" | "content">) {
  return segment.kind === "code"
    || Boolean(segment.language)
    || (["commit", "verification"].includes(segment.kind) && segment.content.includes("\n"));
}

export function shouldShowAgentResponseBlock(input: {
  hasResponseBlock: boolean;
  answerText: string;
  hasFeedbackTimeline: boolean;
  streaming: boolean;
  segments: Array<Pick<ResponseSegment, "kind">>;
}) {
  if (!input.hasResponseBlock) {
    return false;
  }
  if (isNoFinalAnswerStatusContent(input.answerText)) {
    return false;
  }
  if (!input.hasFeedbackTimeline) {
    return true;
  }
  if (input.streaming) {
    return true;
  }
  return input.segments.some((segment) => segment.kind !== "status");
}
