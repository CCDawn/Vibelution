import { Trash2 } from "lucide-react";

import { VButton, VStateSurface } from "../../components/vui";
import {
  presentResearchWorkflowError,
  researchWorkflowErrorActionLabel,
  researchWorkflowErrorBody,
  researchWorkflowErrorTitle,
  type ResearchWorkflowErrorAction,
} from "./researchWorkflowErrorModel";

export type ResearchWorkflowErrorSurfaceProps = {
  lang: "zh" | "en";
  message: string;
  pending?: boolean;
  onRecommendedAction?: (action: ResearchWorkflowErrorAction) => void;
};

export function ResearchWorkflowErrorSurface({
  lang,
  message,
  pending = false,
  onRecommendedAction,
}: ResearchWorkflowErrorSurfaceProps) {
  const presented = presentResearchWorkflowError(message);
  const actionLabel = researchWorkflowErrorActionLabel(presented, lang);
  const showAction =
    Boolean(onRecommendedAction)
    && presented.recommendedAction !== "none"
    && presented.recommendedAction !== "wait_for_search"
    && Boolean(actionLabel);

  return (
    <VStateSurface
      title={researchWorkflowErrorTitle(presented, lang)}
      tone="error"
      actions={
        showAction ? (
          <VButton
            type="button"
            variant="danger"
            isDisabled={pending}
            onPress={() => onRecommendedAction?.(presented.recommendedAction)}
            icon={
              presented.recommendedAction === "reset_progress_cascade"
                || presented.recommendedAction === "reset_source_only" ? (
                <Trash2 size={14} />
              ) : null
            }
          >
            {pending ? (lang === "zh" ? "处理中…" : "Working…") : actionLabel}
          </VButton>
        ) : undefined
      }
    >
      <p className="m-0 text-[var(--vui-font-sm)] leading-relaxed text-[var(--fg-secondary)]">
        {researchWorkflowErrorBody(presented, lang)}
      </p>
      {message && message !== researchWorkflowErrorBody(presented, lang) ? (
        <p className="m-0 mt-2 text-[11px] leading-snug text-[var(--fg-tertiary)]">
          {message}
        </p>
      ) : null}
    </VStateSurface>
  );
}
