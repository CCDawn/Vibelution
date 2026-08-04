/**
 * SC inject shell: project source-collection reset surface + search brief start form.
 * Reset success / draft hydration remain route-owned via callbacks.
 */
import { Trash2 } from "lucide-react";
import type { ReactNode } from "react";

import { VButton, VStateSurface } from "../../components/vui";
import { ResearchWorkflowErrorSurface } from "./ResearchWorkflowErrorSurface";
import { TeamSourceCollectionSearchBriefInject } from "./TeamSourceCollectionSearchBriefInject";
import type { SourceCollectionDraft } from "./source-collection/presentationModel";

export type TeamSourceCollectionSearchBriefShellProps = {
  lang: "zh" | "en";
  resetAvailable: boolean;
  runCount: number;
  resetPending: boolean;
  resetIncludeDownstream: boolean;
  resetError: Error | null;
  onReset: (input: { includeDownstream: boolean }) => void;
  draft: SourceCollectionDraft;
  modeFields: ReactNode;
  hasExistingRun: boolean;
  canStart: boolean;
  startPending: boolean;
  teamId?: string;
  onDraftChange: (patch: Partial<SourceCollectionDraft>) => void;
  onStart: (input: { teamId: string; draft: SourceCollectionDraft }) => void;
};

export function TeamSourceCollectionSearchBriefShell({
  lang,
  resetAvailable,
  runCount,
  resetPending,
  resetIncludeDownstream,
  resetError,
  onReset,
  draft,
  modeFields,
  hasExistingRun,
  canStart,
  startPending,
  teamId,
  onDraftChange,
  onStart,
}: TeamSourceCollectionSearchBriefShellProps) {
  return (
    <>
      {resetAvailable ? (
        <VStateSurface
          title={lang === "zh" ? "重新开始本项目的资料搜集" : "Restart this project's source collection"}
          tone="unavailable"
          facts={[
            {
              key: "scope",
              label: lang === "zh" ? "清理范围" : "Reset scope",
              value: lang === "zh" ? `${runCount} 个资料批次` : `${runCount} source runs`,
            },
          ]}
          actions={(
            <>
              <VButton
                type="button"
                variant="danger"
                onPress={() => onReset({ includeDownstream: false })}
                isDisabled={resetPending}
                icon={<Trash2 size={14} />}>{resetPending && !resetIncludeDownstream
                  ? (lang === "zh" ? "正在清空…" : "Clearing…")
                  : (lang === "zh" ? "清空本项目资料并重新开始" : "Clear this project's sources and restart")}</VButton>
              <VButton
                type="button"
                variant="danger"
                onPress={() => onReset({ includeDownstream: true })}
                isDisabled={resetPending}
                icon={<Trash2 size={14} />}>{resetPending && resetIncludeDownstream
                  ? (lang === "zh" ? "正在清空…" : "Clearing…")
                  : (lang === "zh" ? "连同实验与迭代一起清空" : "Clear sources + experiment/iteration")}</VButton>
            </>
          )}
        >
          {lang === "zh"
            ? "「清空资料」只清尚未进入实验的资料批次；若本项目已有实验/迭代，请用「连同实验与迭代一起清空」。不会删除其他项目、正式题目、知识库或 Agent 会话。"
            : "Source-only reset keeps experiment/iteration. Use the cascade button to also clear this project's experiment and iteration. Other projects, official records, knowledge, and Agent conversations stay."}
        </VStateSurface>
      ) : null}
      {resetError ? (
        <ResearchWorkflowErrorSurface
          lang={lang}
          message={resetError.message}
          pending={resetPending}
          onRecommendedAction={(action) => {
            if (action !== "reset_progress_cascade" && action !== "reset_source_only") {
              return;
            }
            onReset({ includeDownstream: action === "reset_progress_cascade" });
          }}
        />
      ) : null}
      <TeamSourceCollectionSearchBriefInject
        lang={lang}
        draft={draft}
        modeFields={modeFields}
        hasExistingRun={hasExistingRun}
        canStart={canStart}
        startPending={startPending}
        teamId={teamId}
        onDraftChange={onDraftChange}
        onStart={onStart}
      />
    </>
  );
}
