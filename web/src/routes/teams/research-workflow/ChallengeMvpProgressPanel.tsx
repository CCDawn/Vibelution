/**
 * MVP acceptance progress for the research workflow workspace.
 *
 * Read-only projection of challenge-question run facts (machine validation,
 * human gates, completion) from the backend summary — never a second writer.
 * Question rows open the single-question acceptance detail via deep link.
 */
import { useQuery } from "@tanstack/react-query";

import { getChallengeQuestionRunStatus } from "../../../api/challengeQuestionRuns";
import { queryKeys } from "../../../api/queryKeys";
import {
  VButton,
  VEmptyState,
  VStateSurface,
  VSurface,
} from "../../../components/vui";

export type ChallengeMvpProgressPanelProps = {
  teamId: string;
  lang?: "zh" | "en";
  onOpenQuestion: (questionId: string) => void;
};

export function ChallengeMvpProgressPanel({
  teamId,
  lang = "zh",
  onOpenQuestion,
}: ChallengeMvpProgressPanelProps) {
  const zh = lang === "zh";
  const statusQuery = useQuery({
    queryKey: queryKeys.challengeQuestionRunStatus(teamId),
    queryFn: () => getChallengeQuestionRunStatus(teamId),
    enabled: Boolean(teamId.trim()),
    staleTime: 30_000,
  });

  if (statusQuery.isPending) {
    return (
      <VSurface tone="panel" className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
        <VStateSurface tone="loading" title={zh ? "读取题目进度" : "Loading question progress"} fill className="h-full min-h-0" />
      </VSurface>
    );
  }

  if (statusQuery.isError || !statusQuery.data) {
    return (
      <VSurface tone="panel" className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3">
        <div
          className="rounded border border-[var(--border-subtle)] bg-[var(--bg-elevated)] px-2 py-1.5 text-xs text-[var(--fg-primary)]"
          role="alert"
        >
          {statusQuery.error instanceof Error ? statusQuery.error.message : String(statusQuery.error)}
        </div>
        <VButton type="button" variant="secondary" onClick={() => void statusQuery.refetch()}>
          {zh ? "重试" : "Retry"}
        </VButton>
      </VSurface>
    );
  }

  const summary = statusQuery.data.summary;
  const results = summary.validatedQuestionResults ?? [];

  return (
    <VSurface tone="panel" className="flex h-full min-h-0 flex-col gap-3 overflow-auto p-3" data-vui="mvp-progress-panel">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[10px] uppercase tracking-wide text-[var(--fg-tertiary)]">
          {zh ? "MVP 验收进度" : "MVP acceptance"}
        </div>
        <VButton type="button" variant="ghost" onClick={() => void statusQuery.refetch()}>
          {zh ? "刷新" : "Refresh"}
        </VButton>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="rounded border border-[var(--border-subtle)] px-2 py-1.5">
          <div className="text-[var(--fg-tertiary)]">{zh ? "有效候选" : "Valid"}</div>
          <div className="text-lg font-semibold text-[var(--fg-primary)]">{summary.validCandidateCount}</div>
        </div>
        <div className="rounded border border-[var(--border-subtle)] px-2 py-1.5">
          <div className="text-[var(--fg-tertiary)]">{zh ? "已验证题" : "Validated"}</div>
          <div className="text-lg font-semibold text-[var(--fg-primary)]">{summary.validatedQuestionCount}</div>
        </div>
        <div className="rounded border border-[var(--border-subtle)] px-2 py-1.5">
          <div className="text-[var(--fg-tertiary)]">{zh ? "已批准" : "Approved"}</div>
          <div className="text-lg font-semibold text-[var(--fg-primary)]">{summary.completedCount}</div>
        </div>
      </div>

      {results.length === 0 ? (
        <VEmptyState title={zh ? "暂无已验证题目" : "No validated questions"} className="h-auto w-full border-0 bg-transparent">
          {zh ? "完成受控运行与候选晋升后，题目结果会出现在这里。" : "Question results appear here after controlled runs and candidate promotion."}
        </VEmptyState>
      ) : (
        <ul className="m-0 list-none space-y-1 p-0">
          {results.map((item) => (
            <li
              key={item.questionId}
              className="flex items-center justify-between gap-2 rounded border border-[var(--border-subtle)] px-2 py-1.5 text-xs"
            >
              <div className="min-w-0">
                <div className="font-medium break-all text-[var(--fg-primary)]">{item.questionId}</div>
                <div className="break-all text-[var(--fg-secondary)]">
                  {item.runId} · {item.status}
                </div>
              </div>
              <VButton
                type="button"
                variant="ghost"
                onClick={() => onOpenQuestion(item.questionId)}
              >
                {zh ? "详情" : "Detail"}
              </VButton>
            </li>
          ))}
        </ul>
      )}
    </VSurface>
  );
}
