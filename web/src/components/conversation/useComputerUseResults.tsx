import { useState } from "react";

import { fetchJson } from "../../api/client";
import { VButton } from "../vui";
import type { AgentMessageOperation } from "./agentMessageOperations";
import {
  computerUseResultForOperation,
  type ComputerUseResult,
} from "./conversationComputerUseState";
import type { ConversationImagePreviewRequest } from "./ConversationImagePreviewDialog";
import styles from "./ConversationView.styles";

export type UseComputerUseResultsInput = {
  lang: "zh" | "en";
  openImagePreview: (image: ConversationImagePreviewRequest) => void;
};

/**
 * Computer-use sandbox session state (results + pending confirm/cancel) and
 * the inline result panel renderer. State lives here so the panel can render
 * inside any extracted process-row module without prop drilling.
 */
export function useComputerUseResults({ lang, openImagePreview }: UseComputerUseResultsInput) {
  const [computerUseSessionResults, setComputerUseSessionResults] = useState<Record<string, ComputerUseResult>>({});
  const [computerUseSessionPending, setComputerUseSessionPending] = useState<Record<string, "confirm" | "cancel" | undefined>>({});

  function renderComputerUseResult(operation: AgentMessageOperation) {
    const result = computerUseResultForOperation(operation, computerUseSessionResults);
    if (!result) {
      return null;
    }
    const previewLabel = lang === "zh" ? "预览沙盒截图" : "Preview sandbox screenshot";
    const confirmLabel = lang === "zh" ? "确认继续" : "Confirm";
    const cancelLabel = lang === "zh" ? "停止任务" : "Stop";
    const pendingAction = computerUseSessionPending[result.sessionId];
    const imageAlt = result.summary || (lang === "zh" ? "Computer Use 沙盒截图" : "Computer Use sandbox screenshot");
    const confirmSession = () => {
      setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: "confirm" }));
      void fetchJson<ComputerUseResult>(`/api/computer-use/sessions/${encodeURIComponent(result.sessionId)}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation: "approved_from_chat" }),
      })
        .then((payload) => {
          setComputerUseSessionResults((current) => ({ ...current, [result.sessionId]: payload }));
        })
        .catch((error) => {
          setComputerUseSessionResults((current) => ({
            ...current,
            [result.sessionId]: {
              ...result,
              error: error instanceof Error ? error.message : String(error),
            },
          }));
        })
        .finally(() => {
          setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: undefined }));
        });
    };
    const cancelSession = () => {
      setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: "cancel" }));
      void fetchJson<ComputerUseResult>(`/api/computer-use/sessions/${encodeURIComponent(result.sessionId)}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "cancelled_from_chat" }),
      })
        .then((payload) => {
          setComputerUseSessionResults((current) => ({ ...current, [result.sessionId]: payload }));
        })
        .catch((error) => {
          setComputerUseSessionResults((current) => ({
            ...current,
            [result.sessionId]: {
              ...result,
              error: error instanceof Error ? error.message : String(error),
            },
          }));
        })
        .finally(() => {
          setComputerUseSessionPending((current) => ({ ...current, [result.sessionId]: undefined }));
        });
    };
    return (
      <section className={styles.computerUsePanel}>
        <div className={styles.computerUseHeader}>
          <span>{result.status || "computer_use"}</span>
          <code>{result.sessionId}</code>
        </div>
        {result.summary ? <p className={styles.computerUseSummary}>{result.summary}</p> : null}
        {result.screenshotUrl ? (
          <VButton
            type="button"
            className={`${styles.imageArtifactFrame} ${styles.imagePreviewButton}`}
            onClick={() =>
              openImagePreview({
                src: result.screenshotUrl,
                alt: imageAlt,
                downloadUrl: result.screenshotUrl,
                downloadName: true,
              })
            }
            aria-label={previewLabel}
            title={previewLabel}
          >
            <img className={styles.computerUseScreenshot} src={result.screenshotUrl} alt={imageAlt} loading="lazy" />
          </VButton>
        ) : null}
        {result.steps.length > 0 ? (
          <ol className={styles.computerUseSteps}>
            {result.steps.slice(0, 6).map((step, index) => (
              <li key={`${result.sessionId}-${step.index ?? index}`}>
                <span>{step.action || step.status || `${index + 1}`}</span>
                <p>{step.summary || step.status || ""}</p>
              </li>
            ))}
          </ol>
        ) : null}
        {result.error ? <p className={styles.computerUseError}>{result.error}</p> : null}
        {result.needsConfirmation || result.status === "running" ? (
          <div className={styles.computerUseActions}>
            {result.needsConfirmation ? (
              <VButton type="button" onClick={confirmSession} isDisabled={Boolean(pendingAction)}>
                {pendingAction === "confirm" ? (lang === "zh" ? "确认中" : "Confirming") : confirmLabel}
              </VButton>
            ) : null}
            <VButton type="button" onClick={cancelSession} isDisabled={Boolean(pendingAction)}>
              {pendingAction === "cancel" ? (lang === "zh" ? "停止中" : "Stopping") : cancelLabel}
            </VButton>
          </div>
        ) : null}
      </section>
    );
  }

  return {
    computerUseSessionResults,
    computerUseSessionPending,
    renderComputerUseResult,
  };
}
