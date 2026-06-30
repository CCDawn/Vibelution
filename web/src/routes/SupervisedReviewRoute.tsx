import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, CheckCircle2, LibraryBig, LoaderCircle, Search, Square, SquareCheckBig, Trash2, TriangleAlert } from "lucide-react";
import { type CSSProperties, type KeyboardEvent, type PointerEvent, useEffect, useMemo, useState } from "react";
import { NavLink } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  EvolutionChatReviewBulkDeleteResponse,
  EvolutionChatReviewCandidate,
  EvolutionChatReviewDecisionResponse,
  EvolutionChatReviewQueue,
  EvolutionWorkspaceSnapshot,
  EvolutionWorkbench,
  SupervisedWorktreeRun,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import { VButton } from "../components/vui";
import { useAppI18n } from "../i18n/useAppI18n";
import { createEvolutionWorkspaceCache } from "./evolutionWorkspaceCache";
import { SupervisedWorkspaceControls } from "./SupervisedWorkspaceControls";
import { SupervisedWorktreeReviewPanel } from "./SupervisedWorktreeReviewPanel";
import { clampPaneWidth, keyboardPaneWidth, storedPaneWidth } from "./resizablePane";

type ReviewDecision = "positive" | "negative" | "discard";
type ReviewFilter = "all" | "pending" | "positive" | "negative" | "discard";

const REVIEW_FILTERS: ReviewFilter[] = ["all", "pending", "positive", "negative", "discard"];
const EMPTY_REVIEW_ITEMS: EvolutionChatReviewCandidate[] = [];
const REVIEW_QUEUE_WIDTH_KEY = "vibelution.supervised-review.queue-width";
const REVIEW_QUEUE_BOUNDS = { min: 320, max: 560 };
const REVIEW_QUEUE_DEFAULT_WIDTH = 380;
const styles = {
  page:
    "flex h-full min-h-0 flex-col gap-1.5 overflow-hidden px-3 py-2 pb-3 text-[var(--fg-primary)] max-[980px]:overflow-auto max-[980px]:pb-[18px]",
  toolbar: "flex min-w-0 flex-wrap items-center justify-between gap-[var(--route-topbar-gap)]",
  toolbarIntro: "grid min-w-[260px] max-w-[760px] gap-0.5",
  toolbarControls: "flex flex-wrap items-center justify-end gap-3",
  eyebrow: "m-0 mb-0.5 text-[0.7rem] uppercase tracking-[0.08em] text-[var(--accent-warm-2)]",
  title: "m-0 whitespace-nowrap text-[length:var(--route-topbar-title-size)] leading-[1.08]",
  subtitle:
    "m-0 max-w-none overflow-hidden text-ellipsis whitespace-nowrap text-[length:var(--route-topbar-subtitle-size)] leading-tight text-[var(--fg-secondary)]",
  summaryStrip: "grid grid-cols-5 gap-[var(--route-summary-gap)] max-[980px]:grid-cols-2 max-[720px]:grid-cols-1",
  summaryCard:
    "grid min-h-7 grid-cols-[auto_minmax(0,1fr)] items-baseline gap-1.5 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] px-2 py-1 [&_span]:whitespace-nowrap [&_span]:text-[0.68rem] [&_span]:uppercase [&_span]:tracking-[0.06em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis [&_strong]:whitespace-nowrap [&_strong]:text-[0.86rem]",
  lifecyclePanel:
    "flex min-h-[34px] items-center justify-between gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] px-2 py-1.5 max-[980px]:flex-col max-[980px]:items-start",
  lifecyclePills: "flex flex-wrap justify-end gap-2 max-[980px]:justify-start",
  workspace:
    "grid min-h-0 flex-1 grid-cols-[var(--review-queue-width,380px)_12px_minmax(0,1fr)] overflow-hidden max-[980px]:grid-cols-1 max-[980px]:gap-y-3 max-[980px]:overflow-visible",
  resizeHandle:
    "relative min-w-3 cursor-col-resize touch-none border-0 bg-transparent p-0 outline-none before:absolute before:inset-y-0 before:left-1/2 before:w-[3px] before:-translate-x-1/2 before:rounded-[var(--radius-control)] before:bg-[var(--surface-resize-track)] before:transition before:content-[''] hover:before:bg-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] hover:before:shadow-[var(--vui-shadow-soft)] focus-visible:before:bg-[color-mix(in_srgb,var(--accent-warm)_52%,transparent)] focus-visible:before:shadow-[var(--vui-shadow-soft)] max-[980px]:hidden",
  queuePanel:
    "flex min-h-0 flex-col gap-2 overflow-hidden rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] p-[9px] max-[980px]:max-h-none max-[980px]:overflow-visible",
  paneCollapsed: "overflow-hidden p-0 invisible",
  detailPanel:
    "flex min-h-0 flex-col gap-2.5 overflow-auto rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] p-[9px] max-[980px]:overflow-visible",
  panelHeader: "flex items-start justify-between gap-3.5",
  detailHeader: "flex items-start justify-between gap-3.5",
  sectionHeader: "flex items-start justify-between gap-3.5",
  sectionTitle: "m-0 text-base font-bold leading-snug",
  detailTitle: "m-0 text-base font-bold leading-snug",
  detailLead: "m-0 mt-1.5 leading-snug text-[var(--fg-secondary)]",
  secondaryPill:
    "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2 text-xs font-semibold text-[var(--fg-secondary)]",
  statusBadge:
    "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] border border-transparent px-2 text-xs font-semibold",
  statusPending:
    "border-[color-mix(in_srgb,var(--fg-tertiary)_20%,transparent)] bg-[color-mix(in_srgb,var(--fg-tertiary)_12%,transparent)] text-[var(--accent-warm-2)]",
  statusPositive:
    "border-[color-mix(in_srgb,var(--state-success)_20%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_12%,transparent)] text-[var(--accent-warm-2)]",
  statusNegative:
    "border-[color-mix(in_srgb,var(--fg-tertiary)_20%,transparent)] bg-[color-mix(in_srgb,var(--fg-tertiary)_12%,transparent)] text-[var(--accent-warm-2)]",
  statusDiscard:
    "border-[color-mix(in_srgb,var(--surface-card)_18%,transparent)] bg-[color-mix(in_srgb,var(--surface-card)_12%,transparent)] text-[var(--fg-secondary)]",
  queueControls: "flex flex-col gap-2.5",
  filterSegmented: "flex flex-wrap items-center gap-1.5",
  decisionSegmented: "flex flex-wrap items-center gap-1.5",
  filterButton:
    "inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2.5 text-[13px] font-semibold text-[var(--fg-primary)] no-underline transition hover:border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] disabled:cursor-not-allowed disabled:opacity-55",
  decisionButton:
    "inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2.5 text-[13px] font-semibold text-[var(--fg-primary)] no-underline transition hover:border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] disabled:cursor-not-allowed disabled:opacity-55",
  filterButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] text-[var(--accent-warm-2)]",
  decisionButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] text-[var(--accent-warm-2)]",
  primaryAction:
    "inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-[color-mix(in_srgb,var(--accent-warm)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] px-2.5 text-[13px] font-semibold text-[var(--accent-warm-2)] no-underline transition disabled:cursor-not-allowed disabled:opacity-55",
  secondaryAction:
    "inline-flex min-h-8 items-center justify-center gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2.5 text-[13px] font-semibold text-[var(--fg-primary)] no-underline transition hover:border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)]",
  compactAction:
    "inline-flex min-h-7 min-w-0 items-center justify-center gap-1.5 overflow-hidden whitespace-nowrap rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2 text-[11px] font-semibold text-[var(--fg-primary)] no-underline transition disabled:cursor-not-allowed disabled:opacity-55 [&_[data-slot=vui-button-content]]:min-w-0 [&_[data-slot=vui-button-label]]:truncate",
  dangerAction:
    "border-[color-mix(in_srgb,var(--fg-tertiary)_22%,transparent)] bg-[color-mix(in_srgb,var(--fg-tertiary)_8%,transparent)] text-[var(--accent-warm-2)]",
  searchField:
    "flex min-h-[34px] items-center gap-2 rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] px-2.5 text-[var(--fg-secondary)] [&_input]:w-full [&_input]:border-0 [&_input]:bg-transparent [&_input]:font-[inherit] [&_input]:text-[var(--fg-primary)] [&_input]:outline-none [&_input::placeholder]:text-[var(--fg-tertiary)]",
  queueMeta: "flex items-center justify-between gap-2.5 text-[13px] text-[var(--fg-tertiary)]",
  bulkToolbar:
    "grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2 rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card-subtle)] px-2 py-1.5",
  bulkCounter:
    "flex min-w-[70px] items-baseline justify-start gap-2 text-xs text-[var(--fg-secondary)] [&_strong]:text-base [&_strong]:text-[var(--fg-primary)]",
  bulkActions: "grid min-w-0 grid-cols-3 gap-1.5",
  queueList: "flex min-h-0 flex-col gap-1.5 overflow-auto pr-1 max-[980px]:max-h-[420px]",
  queueItem:
    "w-full cursor-pointer rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card)] px-2.5 py-[9px] text-left text-inherit transition hover:border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] hover:bg-[var(--surface-panel-strong)]",
  queueItemActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_28%,transparent)] bg-[var(--surface-panel-strong)]",
  queueItemTop: "flex items-center justify-between gap-2.5",
  queueTitleRow: "flex min-w-0 items-center justify-start gap-2.5 [&_strong]:min-w-0 [&_strong]:overflow-hidden [&_strong]:text-ellipsis",
  queueHeadline: "my-1.5 leading-normal text-[var(--fg-secondary)]",
  signalRow: "flex flex-wrap items-center justify-start gap-2.5",
  signalPill:
    "inline-flex min-h-6 items-center justify-center rounded-[var(--radius-control)] bg-[var(--surface-card-hover)] px-2 text-xs font-semibold text-[var(--fg-secondary)]",
  queueFooter: "flex items-center justify-between gap-2.5 text-xs text-[var(--fg-tertiary)]",
  selectionButton:
    "inline-flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-[var(--border-soft)] bg-[var(--surface-card-muted)] p-0 text-[var(--fg-tertiary)] disabled:cursor-not-allowed disabled:opacity-55",
  selectionButtonActive:
    "border-[color-mix(in_srgb,var(--accent-warm)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] text-[var(--accent-warm-2)]",
  factGrid: "grid grid-cols-4 gap-2 max-[980px]:grid-cols-2 max-[720px]:grid-cols-1",
  metricGrid: "grid grid-cols-4 gap-2 max-[980px]:grid-cols-2 max-[720px]:grid-cols-1",
  signalColumns: "grid grid-cols-2 gap-2 max-[980px]:grid-cols-1",
  formGrid: "grid grid-cols-2 gap-2 max-[980px]:grid-cols-1",
  factCard:
    "rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] px-2.5 py-2 [&_span]:mb-1 [&_span]:block [&_span]:text-xs [&_span]:uppercase [&_span]:tracking-[0.08em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:block [&_strong]:leading-normal",
  metricCard:
    "rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel-strong)] px-2.5 py-2 [&_span]:mb-1 [&_span]:block [&_span]:text-xs [&_span]:uppercase [&_span]:tracking-[0.08em] [&_span]:text-[var(--fg-tertiary)] [&_strong]:block [&_strong]:leading-normal [&_p]:m-0 [&_p]:mt-1 [&_p]:leading-snug [&_p]:text-[var(--fg-secondary)]",
  signalSection:
    "rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card-subtle)] px-2.5 py-[9px] [&_h3]:m-0 [&_h3]:mb-2.5 [&_h3]:text-[0.95rem] [&_h3]:font-bold [&_ul]:m-0 [&_ul]:pl-[18px] [&_ul]:leading-relaxed [&_ul]:text-[var(--fg-secondary)]",
  detailSection:
    "rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card-subtle)] px-2.5 py-[9px] [&_h3]:m-0 [&_h3]:mb-2.5 [&_h3]:text-[0.95rem] [&_h3]:font-bold",
  transcriptSection:
    "rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card-subtle)] px-2.5 py-[9px] [&_summary]:cursor-pointer [&_summary]:font-semibold",
  evidenceList: "flex flex-col gap-1.5",
  transcriptList: "flex flex-col gap-1.5",
  evidenceCard:
    "rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] px-2.5 py-[9px] [&_p]:m-0 [&_p]:mt-2 [&_p]:whitespace-pre-wrap [&_p]:leading-normal",
  transcriptCard:
    "rounded-lg border border-[var(--border-soft)] bg-[var(--surface-panel)] px-2.5 py-[9px] [&_p]:m-0 [&_p]:mt-2 [&_p]:whitespace-pre-wrap [&_p]:leading-normal",
  evidenceTop: "flex items-center justify-between gap-2.5",
  formField:
    "block [&_span]:mb-1 [&_span]:block [&_span]:text-xs [&_span]:uppercase [&_span]:tracking-[0.08em] [&_span]:text-[var(--fg-tertiary)] [&_input]:min-h-[34px] [&_input]:w-full [&_input]:rounded-lg [&_input]:border [&_input]:border-[var(--border-soft)] [&_input]:bg-[var(--surface-card-muted)] [&_input]:px-3 [&_input]:font-[inherit] [&_input]:text-[var(--fg-primary)] [&_input]:outline-none [&_input::placeholder]:text-[var(--fg-tertiary)] [&_select]:min-h-[34px] [&_select]:w-full [&_select]:rounded-lg [&_select]:border [&_select]:border-[var(--border-soft)] [&_select]:bg-[var(--surface-card-muted)] [&_select]:px-3 [&_select]:font-[inherit] [&_select]:text-[var(--fg-primary)] [&_select]:outline-none",
  textAreaField:
    "block [&_span]:mb-1 [&_span]:block [&_span]:text-xs [&_span]:uppercase [&_span]:tracking-[0.08em] [&_span]:text-[var(--fg-tertiary)] [&_textarea]:min-h-[84px] [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:rounded-lg [&_textarea]:border [&_textarea]:border-[var(--border-soft)] [&_textarea]:bg-[var(--surface-card-muted)] [&_textarea]:p-2.5 [&_textarea]:font-[inherit] [&_textarea]:text-[var(--fg-primary)] [&_textarea]:outline-none [&_textarea::placeholder]:text-[var(--fg-tertiary)]",
  actionRow: "flex items-center justify-between gap-2.5",
  detailHeaderActions: "flex items-center justify-between gap-2.5",
  feedbackText: "m-0 text-[var(--accent-warm-2)]",
  errorText: "m-0 text-[var(--accent-warm-2)]",
  hintText: "m-0 leading-normal text-[var(--fg-secondary)]",
  transcriptMeta: "mt-3.5 grid gap-2.5",
  metaRow:
    "flex items-start justify-between gap-4 text-[var(--fg-secondary)] [&_span]:flex-1 [&_span]:break-all [&_span]:text-right",
  emptyState:
    "flex min-h-[82px] flex-col justify-center gap-1 rounded-lg border border-dashed border-[var(--border-strong)] px-[11px] py-[9px] text-[var(--fg-secondary)] [&_h3]:m-0 [&_h3]:text-[var(--fg-primary)]",
  spin: "animate-spin",
} as const;

export function SupervisedReviewRoute() {
  const { lang, t, statusLabel } = useAppI18n();
  const queryClient = useQueryClient();
  const evolutionWorkspaceCache = useMemo(() => createEvolutionWorkspaceCache(queryClient), [queryClient]);
  const [filter, setFilter] = useState<ReviewFilter>("pending");
  const [searchInput, setSearchInput] = useState("");
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [draftDecision, setDraftDecision] = useState<ReviewDecision>("positive");
  const [reviewerNote, setReviewerNote] = useState("");
  const [reasonCode, setReasonCode] = useState("");
  const [errorType, setErrorType] = useState("");
  const [correctPrinciple, setCorrectPrinciple] = useState("");
  const [idealBehavior, setIdealBehavior] = useState("");
  const [actionFeedback, setActionFeedback] = useState("");
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([]);
  const [bulkFeedback, setBulkFeedback] = useState("");
  const [queuePanelWidth, setQueuePanelWidth] = useState(() =>
    storedPaneWidth(REVIEW_QUEUE_WIDTH_KEY, REVIEW_QUEUE_DEFAULT_WIDTH, REVIEW_QUEUE_BOUNDS),
  );
  const [queuePanelCollapsed, setQueuePanelCollapsed] = useState(false);
  const pageVisible = usePageVisibility();

  const reviewQuery = useQuery({
    queryKey: queryKeys.evolutionChatReview(),
    queryFn: () => fetchJson<EvolutionChatReviewQueue>("/api/evolution/chat-review"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
  });
  const workbenchQuery = useQuery({
    queryKey: queryKeys.evolutionWorkbench(),
    queryFn: () => fetchJson<EvolutionWorkbench>("/api/evolution/workbench"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
  });
  const workspaceSnapshotQuery = useQuery({
    queryKey: queryKeys.evolutionWorkspaceSnapshot(),
    queryFn: () => fetchJson<EvolutionWorkspaceSnapshot>("/api/evolution/workspace-snapshot"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
  });

  const decisionMutation = useMutation({
    mutationFn: () => {
      if (!selectedCandidate) {
        throw new Error(lang === "zh" ? "当前没有选中的样本。" : "There is no selected sample.");
      }
      return fetchJson<EvolutionChatReviewDecisionResponse>(
        `/api/evolution/chat-review/${selectedCandidate.candidateId}/decision`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            decision: draftDecision,
            reviewerNote,
            reasonCode,
            errorType,
            correctPrinciple,
            idealBehavior,
          }),
        },
      );
    },
    onMutate: () => {
      setActionFeedback("");
    },
    onSuccess: async (payload) => {
      setActionFeedback(payload.summary);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReviewCandidate(selectedCandidate?.candidateId ?? "") }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
      ]);
    },
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: () => {
      return fetchJson<EvolutionChatReviewBulkDeleteResponse>("/api/evolution/chat-review/delete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          candidateIds: selectedCandidateIds,
          reviewerNote: "bulk discard from review workspace",
        }),
      });
    },
    onMutate: () => {
      setBulkFeedback("");
      setActionFeedback("");
    },
    onSuccess: async (payload) => {
      setBulkFeedback(payload.summary);
      setSelectedCandidateIds([]);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
      ]);
    },
  });
  const worktreeActionMutation = useMutation({
    mutationFn: (variables: { runId: string; action: string; reviewerNote?: string }) =>
      fetchJson<SupervisedWorktreeRun>(`/api/evolution/worktree-runs/${variables.runId}/actions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          action: variables.action,
          reviewerNote: variables.reviewerNote ?? "",
        }),
      }),
    onSuccess: async () => {
      await evolutionWorkspaceCache.afterWorktreeRunChanged();
    },
  });

  const reviewData = reviewQuery.data;
  const workspaceSnapshot = workspaceSnapshotQuery.data;
  const worktreeRuns = workspaceSnapshot?.worktreeRuns ?? [];
  const activeWorktreeRun = workspaceSnapshot?.worktreeActiveRun ?? null;
  const items = reviewData?.items ?? EMPTY_REVIEW_ITEMS;
  const positiveDatasetVisible = workbenchQuery.data?.datasets.some(
    (item) => item.name === reviewData?.positiveDatasetName && item.available,
  ) ?? false;
  const consoleTarget = reviewData?.positiveDatasetName
    ? `/supervised-evolution?dataset=${encodeURIComponent(reviewData.positiveDatasetName)}`
    : "/supervised-evolution";
  const normalizedSearch = searchInput.trim().toLowerCase();
  const visibleItems = useMemo(() => {
    return items.filter((item) => {
      if (filter !== "all" && item.status !== filter) {
        return false;
      }
      if (!normalizedSearch) {
        return true;
      }
      const haystack = [
        item.topicSummary,
        item.structuredSample.promptSeed,
        item.sessionId,
        item.sourceLogPath,
        item.reviewProfile.suggestedReason,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalizedSearch);
    });
  }, [filter, items, normalizedSearch]);
  const selectedCandidate =
    visibleItems.find((item) => item.candidateId === selectedCandidateId)
    ?? visibleItems[0]
    ?? null;
  const candidateDetailQuery = useQuery({
    queryKey: queryKeys.evolutionChatReviewCandidate(selectedCandidate?.candidateId ?? ""),
    queryFn: () => fetchJson<EvolutionChatReviewCandidate>(
      `/api/evolution/chat-review/${encodeURIComponent(selectedCandidate?.candidateId ?? "")}`,
    ),
    enabled: Boolean(selectedCandidate?.candidateId),
    refetchInterval: false,
    refetchIntervalInBackground: false,
  });
  const selectedCandidateDetail = candidateDetailQuery.data?.candidateId === selectedCandidate?.candidateId
    ? candidateDetailQuery.data
    : null;
  const detailCandidate = selectedCandidateDetail ?? selectedCandidate;
  const reviewTabSummaries = {
    approval: {
      status: lang === "zh"
        ? `${reviewData?.pendingCount ?? 0} 待审`
        : `${reviewData?.pendingCount ?? 0} pending`,
      detail: lang === "zh"
        ? `${reviewData?.positiveCount ?? 0} 正例 / ${reviewData?.negativeCount ?? 0} 负例`
        : `${reviewData?.positiveCount ?? 0} positive / ${reviewData?.negativeCount ?? 0} negative`,
      count: reviewData?.pendingCount ?? 0,
    },
  };
  const visiblePendingItems = useMemo(() => {
    return visibleItems.filter((item) => item.status === "pending");
  }, [visibleItems]);
  const visiblePendingIds = useMemo(() => {
    return visiblePendingItems.map((item) => item.candidateId);
  }, [visiblePendingItems]);
  const evidenceTurns = useMemo(() => {
    if (!detailCandidate) {
      return [];
    }
    const highlightSet = new Set(detailCandidate.reviewProfile.evidenceTurnNumbers);
    const matching = detailCandidate.conversationTurns.filter((turn) => highlightSet.has(turn.turnNumber));
    return matching.length > 0 ? matching : detailCandidate.conversationTurns.slice(0, 3);
  }, [detailCandidate]);

  useEffect(() => {
    if (!visibleItems.some((item) => item.candidateId === selectedCandidateId)) {
      setSelectedCandidateId(visibleItems[0]?.candidateId ?? null);
    }
  }, [selectedCandidateId, visibleItems]);

  useEffect(() => {
    const visiblePendingSet = new Set(visiblePendingIds);
    setSelectedCandidateIds((current) => current.filter((candidateId) => visiblePendingSet.has(candidateId)));
  }, [visiblePendingIds]);

  useEffect(() => {
    if (!detailCandidate) {
      setDraftDecision("positive");
      setReviewerNote("");
      setReasonCode("");
      setErrorType("");
      setCorrectPrinciple("");
      setIdealBehavior("");
      return;
    }
    setDraftDecision((detailCandidate.reviewProfile.suggestedDecision as ReviewDecision) || "positive");
    setReviewerNote(detailCandidate.reviewerNote || "");
    setReasonCode(detailCandidate.reviewDecision.reasonCode || "");
    setErrorType(detailCandidate.reviewDecision.errorType || "");
    setCorrectPrinciple(detailCandidate.reviewDecision.correctPrinciple || "");
    setIdealBehavior(detailCandidate.reviewDecision.idealBehavior || "");
  }, [detailCandidate?.candidateId]);

  useEffect(() => {
    window.localStorage.setItem(REVIEW_QUEUE_WIDTH_KEY, String(queuePanelWidth));
  }, [queuePanelWidth]);

  const decisionError = decisionMutation.error?.message ?? "";
  const bulkError = bulkDeleteMutation.error?.message ?? "";
  const pendingOnlyCount = reviewData?.pendingCount ?? 0;
  const selectedCount = selectedCandidateIds.length;
  const visiblePendingCount = visiblePendingItems.length;
  const lifecycle = reviewData?.lifecycle;
  const workspaceStyle = useMemo(
    () =>
      ({
        "--review-queue-width": queuePanelCollapsed ? "0px" : `${queuePanelWidth}px`,
      }) as CSSProperties,
    [queuePanelCollapsed, queuePanelWidth],
  );
  const resizeQueueLabel = lang === "zh" ? "调整样本列表宽度" : "Resize sample list";

  function levelLabel(level: string) {
    if (level === "high") {
      return lang === "zh" ? "高" : "High";
    }
    if (level === "medium") {
      return lang === "zh" ? "中" : "Medium";
    }
    return lang === "zh" ? "低" : "Low";
  }

  function filterLabel(value: ReviewFilter) {
    if (value === "all") {
      return lang === "zh" ? "全部" : "All";
    }
    if (value === "pending") {
      return lang === "zh" ? "待审" : "Pending";
    }
    if (value === "positive") {
      return lang === "zh" ? "正例" : "Positive";
    }
    if (value === "negative") {
      return lang === "zh" ? "负例" : "Negative";
    }
    return lang === "zh" ? "丢弃" : "Discard";
  }

  function decisionLabel(value: ReviewDecision) {
    if (value === "positive") {
      return lang === "zh" ? "纳入正例" : "Positive example";
    }
    if (value === "negative") {
      return lang === "zh" ? "纳入负例" : "Negative example";
    }
    return lang === "zh" ? "丢弃" : "Discard";
  }

  function statusTone(status: string) {
    if (status === "positive") {
      return styles.statusPositive;
    }
    if (status === "negative") {
      return styles.statusNegative;
    }
    if (status === "discard") {
      return styles.statusDiscard;
    }
    return styles.statusPending;
  }

  function submitCurrentDecision() {
    if (!detailCandidate || detailCandidate.status !== "pending") {
      return;
    }
    decisionMutation.mutate();
  }

  function toggleCandidateSelection(candidateId: string) {
    setSelectedCandidateIds((current) => {
      if (current.includes(candidateId)) {
        return current.filter((item) => item !== candidateId);
      }
      return [...current, candidateId];
    });
  }

  function selectVisiblePendingItems() {
    setSelectedCandidateIds(visiblePendingIds);
  }

  function beginQueueResize(startX: number) {
    const startWidth = queuePanelWidth;
    const handleMove = (moveEvent: globalThis.PointerEvent) => {
      setQueuePanelWidth(clampPaneWidth(startWidth + moveEvent.clientX - startX, REVIEW_QUEUE_BOUNDS));
    };
    const handleEnd = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleEnd);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleEnd);
  }

  function handleQueueResizeStart(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    if (queuePanelCollapsed) {
      return;
    }
    event.preventDefault();
    beginQueueResize(event.clientX);
  }

  function handleQueueResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (queuePanelCollapsed) {
      return;
    }
    const nextWidth = keyboardPaneWidth(queuePanelWidth, event.key, REVIEW_QUEUE_BOUNDS);
    if (nextWidth === null) {
      return;
    }
    event.preventDefault();
    setQueuePanelWidth(nextWidth);
  }

  function triggerWorktreeReviewApproval(run: SupervisedWorktreeRun) {
    if (!run.runId) {
      return;
    }
    worktreeActionMutation.mutate({
      runId: run.runId,
      action: "approve_review",
      reviewerNote: t("selfWorktreeReviewNote"),
    });
  }

  function triggerWorktreeAction(run: SupervisedWorktreeRun, action: string) {
    if (!run.runId) {
      return;
    }
    if (action === "discard" || action === "merge") {
      const confirmKey = action === "discard" ? "discardWorktreeConfirm" : "mergeWorktreeConfirm";
      if (!window.confirm(t(confirmKey).replace("{runId}", run.runId))) {
        return;
      }
    }
    worktreeActionMutation.mutate({
      runId: run.runId,
      action,
    });
  }

  const reasonOptions = draftDecision === "positive"
    ? [
      { value: "grounded_workflow", label: lang === "zh" ? "过程扎实" : "Grounded workflow" },
      { value: "strong_closure", label: lang === "zh" ? "收束清楚" : "Strong closure" },
      { value: "reusable_pattern", label: lang === "zh" ? "可复用模式" : "Reusable pattern" },
    ]
    : draftDecision === "negative"
      ? [
        { value: "missing_evidence", label: lang === "zh" ? "缺少证据" : "Missing evidence" },
        { value: "weak_verification", label: lang === "zh" ? "验证不足" : "Weak verification" },
        { value: "repetitive_no_progress", label: lang === "zh" ? "重复但没推进" : "Repeated without progress" },
      ]
      : [
        { value: "thin_signal", label: lang === "zh" ? "信号太薄" : "Signal too thin" },
        { value: "duplicate_sample", label: lang === "zh" ? "样本重复" : "Duplicate sample" },
        { value: "too_noisy", label: lang === "zh" ? "噪声过多" : "Too noisy" },
      ];

  return (
    <div className={styles.page}>
      <section className={styles.toolbar}>
        <div className={styles.toolbarIntro}>
          <p className={styles.eyebrow}>{t("navSupervisedEvolution")}</p>
          <h1 className={styles.title}>{t("reviewWorkspace")}</h1>
          <p className={styles.subtitle}>{t("reviewWorkspaceSubtitle")}</p>
        </div>

        <div className={styles.toolbarControls}>
          <SupervisedWorkspaceControls activeView="review" activeWorkflowStepId="approval" tabSummaries={reviewTabSummaries} />
        </div>
      </section>

      <section className={styles.summaryStrip}>
        <article className={styles.summaryCard}>
          <span>{lang === "zh" ? "待审样本" : "Pending cases"}</span>
          <strong>{reviewData?.pendingCount ?? 0}</strong>
        </article>
        <article className={styles.summaryCard}>
          <span>{lang === "zh" ? "正例" : "Positive"}</span>
          <strong>{reviewData?.positiveCount ?? 0}</strong>
        </article>
        <article className={styles.summaryCard}>
          <span>{lang === "zh" ? "负例" : "Negative"}</span>
          <strong>{reviewData?.negativeCount ?? 0}</strong>
        </article>
        <article className={styles.summaryCard}>
          <span>{lang === "zh" ? "已丢弃" : "Discarded"}</span>
          <strong>{reviewData?.discardCount ?? 0}</strong>
        </article>
        <article className={styles.summaryCard}>
          <span>{lang === "zh" ? "正例数据集" : "Positive dataset"}</span>
          <strong>{reviewData?.positiveDatasetName ?? "--"}</strong>
        </article>
      </section>

      <section className={styles.lifecyclePanel}>
        <div>
          <p className={styles.eyebrow}>{lang === "zh" ? "生命周期边界" : "Lifecycle boundary"}</p>
          <h2 className={styles.sectionTitle}>
            {lifecycle?.candidateStage || "pending_review"}{" -> "}{lifecycle?.reviewedCaseStage || "reviewed_chat_case"}
          </h2>
        </div>
        <div className={styles.lifecyclePills}>
          <span className={styles.secondaryPill}>
            {lifecycle?.rawChatDirectTrainingAllowed
              ? (lang === "zh" ? "raw chat 可直训" : "raw chat training allowed")
              : (lang === "zh" ? "raw chat 不直训" : "no raw-chat training")}
          </span>
          <span className={styles.secondaryPill}>
            {lang === "zh" ? "正例" : "positive"}: {lifecycle?.datasetTarget || reviewData?.positiveDatasetName || "--"}
          </span>
          <span className={styles.secondaryPill}>
            {lang === "zh" ? "负例" : "negative"}: {lifecycle?.negativeTarget || reviewData?.negativeDatasetName || "--"}
          </span>
          {(lifecycle?.allowedDownstreamUses ?? []).map((use) => (
            <span key={use} className={styles.signalPill}>{use}</span>
          ))}
        </div>
      </section>

      <SupervisedWorktreeReviewPanel
        activeRun={activeWorktreeRun}
        runs={worktreeRuns}
        pending={worktreeActionMutation.isPending}
        feedback={worktreeActionMutation.data?.latestMessage || ""}
        error={worktreeActionMutation.error?.message ?? ""}
        onApproveReview={triggerWorktreeReviewApproval}
        onRunAction={triggerWorktreeAction}
      />

      <div className={styles.workspace} style={workspaceStyle}>
        <aside className={queuePanelCollapsed ? `${styles.queuePanel} ${styles.paneCollapsed}` : styles.queuePanel} aria-hidden={queuePanelCollapsed}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.eyebrow}>{lang === "zh" ? "待审队列" : "Review queue"}</p>
              <h2 className={styles.sectionTitle}>{lang === "zh" ? "样本列表" : "Cases"}</h2>
            </div>
            <span className={styles.secondaryPill}>{visibleItems.length}</span>
          </div>

          <div className={styles.queueControls}>
            <div className={styles.filterSegmented}>
              {REVIEW_FILTERS.map((value) => (
                <VButton
                  key={value}
                  type="button"
                  className={filter === value ? `${styles.filterButton} ${styles.filterButtonActive}` : styles.filterButton}
                  onClick={() => setFilter(value)}
                >
                  {filterLabel(value)}
                </VButton>
              ))}
            </div>
            <label className={styles.searchField}>
              <Search size={14} />
              <input
                type="text"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder={lang === "zh" ? "搜索标题、提示种子或日志" : "Search title, prompt seed, or log"}
              />
            </label>
          </div>

          <div className={styles.queueMeta}>
            <span>{lang === "zh" ? "默认先处理待审样本" : "Pending items stay at the front"}</span>
            <strong>{pendingOnlyCount}</strong>
          </div>

          <div className={styles.bulkToolbar}>
            <div className={styles.bulkCounter}>
              <strong>{selectedCount}</strong>
              <span>{lang === "zh" ? `已选 / 当前待审 ${visiblePendingCount}` : `selected / ${visiblePendingCount} visible pending`}</span>
            </div>
            <div className={styles.bulkActions}>
              <VButton
                type="button"
                className={styles.compactAction}
                isDisabled={visiblePendingCount === 0}
                onClick={selectVisiblePendingItems}
              >
                <SquareCheckBig size={14} />
                {lang === "zh" ? "选择当前待审" : "Select pending"}
              </VButton>
              <VButton
                type="button"
                className={styles.compactAction}
                isDisabled={selectedCount === 0}
                onClick={() => setSelectedCandidateIds([])}
              >
                {lang === "zh" ? "清空" : "Clear"}
              </VButton>
              <VButton
                type="button"
                className={`${styles.compactAction} ${styles.dangerAction}`}
                isDisabled={selectedCount === 0 || bulkDeleteMutation.isPending}
                onClick={() => bulkDeleteMutation.mutate()}
              >
                {bulkDeleteMutation.isPending ? <LoaderCircle size={14} className={styles.spin} /> : <Trash2 size={14} />}
                {lang === "zh" ? "丢弃所选" : "Discard selected"}
              </VButton>
            </div>
          </div>

          {bulkFeedback ? <p className={styles.feedbackText}>{bulkFeedback}</p> : null}
          {bulkError ? <p className={styles.errorText}>{bulkError}</p> : null}

          {visibleItems.length === 0 ? (
            <div className={styles.emptyState}>
              <h3>{lang === "zh" ? "当前没有匹配样本" : "No matching samples"}</h3>
              <p>{lang === "zh" ? "换个筛选条件，或者等新的多轮片段进入审核队列。" : "Try another filter or wait for new multi-turn excerpts to enter the queue."}</p>
            </div>
          ) : (
            <div className={styles.queueList}>
              {visibleItems.map((item) => {
                const itemSelected = selectedCandidateIds.includes(item.candidateId);
                const selectable = item.status === "pending";
                return (
                <article
                  key={item.candidateId}
                  role="button"
                  tabIndex={0}
                  className={
                    selectedCandidate?.candidateId === item.candidateId
                      ? `${styles.queueItem} ${styles.queueItemActive}`
                      : styles.queueItem
                  }
                  onClick={() => setSelectedCandidateId(item.candidateId)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedCandidateId(item.candidateId);
                    }
                  }}
                >
                  <div className={styles.queueItemTop}>
                    <div className={styles.queueTitleRow}>
                      <VButton
                        type="button"
                        className={
                          itemSelected
                            ? `${styles.selectionButton} ${styles.selectionButtonActive}`
                            : styles.selectionButton
                        }
                        isDisabled={!selectable}
                        title={selectable ? (lang === "zh" ? "加入批量丢弃" : "Select for bulk discard") : (lang === "zh" ? "已处理样本不可批量丢弃" : "Reviewed samples cannot be bulk discarded")}
                        aria-label={selectable ? (lang === "zh" ? "选择样本" : "Select sample") : (lang === "zh" ? "样本已处理" : "Sample already reviewed")}
                        onClick={(event) => {
                          event.stopPropagation();
                          if (selectable) {
                            toggleCandidateSelection(item.candidateId);
                          }
                        }}
                      >
                        {itemSelected ? <SquareCheckBig size={16} /> : <Square size={16} />}
                      </VButton>
                      <strong>{item.topicSummary || item.candidateId}</strong>
                    </div>
                    <span className={`${styles.statusBadge} ${statusTone(item.status)}`}>{statusLabel(item.status)}</span>
                  </div>
                  <p className={styles.queueHeadline}>{item.structuredSample.promptSeed || "--"}</p>
                  <div className={styles.signalRow}>
                    {item.qualitySignals.slice(0, 3).map((signal) => (
                      <span key={`${item.candidateId}-${signal}`} className={styles.signalPill}>{signal}</span>
                    ))}
                  </div>
                  <div className={styles.queueFooter}>
                    <span>{`T${item.startTurn}-${item.endTurn}`}</span>
                    <span>{decisionLabel((item.reviewProfile.suggestedDecision as ReviewDecision) || "positive")}</span>
                  </div>
                </article>
                );
              })}
            </div>
          )}
        </aside>

        <PaneCollapseHandle
          side="left"
          collapsed={queuePanelCollapsed}
          separatorLabel={resizeQueueLabel}
          collapseLabel={lang === "zh" ? "收起样本列表" : "Collapse sample list"}
          expandLabel={lang === "zh" ? "展开样本列表" : "Expand sample list"}
          className={styles.resizeHandle}
          onToggle={() => setQueuePanelCollapsed((current) => !current)}
          onPointerDown={handleQueueResizeStart}
          onKeyDown={handleQueueResizeKeyDown}
        />

        <section className={styles.detailPanel}>
          {detailCandidate ? (
            <>
              <div className={styles.detailHeader}>
                <div>
                  <p className={styles.eyebrow}>{lang === "zh" ? "当前裁决样本" : "Current review case"}</p>
                  <h2 className={styles.detailTitle}>{detailCandidate.topicSummary || detailCandidate.candidateId}</h2>
                  <p className={styles.detailLead}>{detailCandidate.reviewProfile.suggestedReason}</p>
                </div>
                <div className={styles.detailHeaderActions}>
                  <span className={`${styles.statusBadge} ${statusTone(detailCandidate.status)}`}>{statusLabel(detailCandidate.status)}</span>
                  <span className={styles.secondaryPill}>{decisionLabel((detailCandidate.reviewProfile.suggestedDecision as ReviewDecision) || "positive")}</span>
                </div>
              </div>

              <div className={styles.factGrid}>
                <article className={styles.factCard}>
                  <span>{lang === "zh" ? "学习重点" : "Learning focus"}</span>
                  <strong>{detailCandidate.reviewProfile.learningFocus}</strong>
                </article>
                <article className={styles.factCard}>
                  <span>{lang === "zh" ? "轮次范围" : "Turn range"}</span>
                  <strong>{`T${detailCandidate.startTurn}-${detailCandidate.endTurn}`}</strong>
                </article>
                <article className={styles.factCard}>
                  <span>{lang === "zh" ? "来源会话" : "Source session"}</span>
                  <strong>{detailCandidate.sessionId || "--"}</strong>
                </article>
                <article className={styles.factCard}>
                  <span>{lang === "zh" ? "训练层级" : "Training tier"}</span>
                  <strong>{detailCandidate.structuredSample.trainingTier || "--"}</strong>
                </article>
              </div>

              <div className={styles.metricGrid}>
                {[
                  { label: lang === "zh" ? "任务清晰度" : "Task clarity", item: detailCandidate.reviewProfile.taskClarity },
                  { label: lang === "zh" ? "目标稳定性" : "Goal stability", item: detailCandidate.reviewProfile.goalStability },
                  { label: lang === "zh" ? "输出可学性" : "Learning value", item: detailCandidate.reviewProfile.assistantLearningValue },
                  { label: lang === "zh" ? "反模式风险" : "Anti-pattern risk", item: detailCandidate.reviewProfile.antiPatternRisk },
                ].map((metric) => (
                  <article key={metric.label} className={styles.metricCard}>
                    <span>{metric.label}</span>
                    <strong>{levelLabel(metric.item.level)}</strong>
                    <p>{metric.item.note}</p>
                  </article>
                ))}
              </div>

              <div className={styles.signalColumns}>
                <section className={styles.signalSection}>
                  <h3>{lang === "zh" ? "正向信号" : "Positive signals"}</h3>
                  <ul>
                    {detailCandidate.reviewProfile.positiveSignals.map((signal) => (
                      <li key={signal}>{signal}</li>
                    ))}
                  </ul>
                </section>
                <section className={styles.signalSection}>
                  <h3>{lang === "zh" ? "反向信号" : "Negative signals"}</h3>
                  <ul>
                    {detailCandidate.reviewProfile.negativeSignals.map((signal) => (
                      <li key={signal}>{signal}</li>
                    ))}
                  </ul>
                </section>
              </div>

              <section className={styles.detailSection}>
                <div className={styles.sectionHeader}>
                  <div>
                    <p className={styles.eyebrow}>{lang === "zh" ? "关键证据" : "Key evidence"}</p>
                    <h3>{lang === "zh" ? "先判断，再读完整对话" : "Judge first, then inspect the full transcript"}</h3>
                  </div>
                  <span className={styles.secondaryPill}>{evidenceTurns.length}</span>
                </div>
                <div className={styles.evidenceList}>
                  {evidenceTurns.map((turn) => (
                    <article key={`${detailCandidate.candidateId}-${turn.turnNumber}`} className={styles.evidenceCard}>
                      <div className={styles.evidenceTop}>
                        <strong>{`Turn ${turn.turnNumber}`}</strong>
                        <span>{turn.toolCalls.join(", ") || "--"}</span>
                      </div>
                      <p>{lang === "zh" ? `用户：${turn.userMessage}` : `User: ${turn.userMessage}`}</p>
                      <p>{lang === "zh" ? `助手：${turn.assistantMessage}` : `Assistant: ${turn.assistantMessage}`}</p>
                    </article>
                  ))}
                </div>
              </section>

              <section className={styles.detailSection}>
                <div className={styles.sectionHeader}>
                  <div>
                    <p className={styles.eyebrow}>{lang === "zh" ? "裁决" : "Decision"}</p>
                    <h3>{lang === "zh" ? "把样本归进正例、负例或丢弃" : "Send the sample to positive, negative, or discard"}</h3>
                  </div>
                  {detailCandidate.status !== "pending" ? (
                    <span className={styles.secondaryPill}>{lang === "zh" ? "已处理" : "Already reviewed"}</span>
                  ) : null}
                </div>

                <div className={styles.decisionSegmented}>
                  {(["positive", "negative", "discard"] as ReviewDecision[]).map((value) => (
                    <VButton
                      key={value}
                      type="button"
                      className={draftDecision === value ? `${styles.decisionButton} ${styles.decisionButtonActive}` : styles.decisionButton}
                      isDisabled={detailCandidate.status !== "pending"}
                      onClick={() => setDraftDecision(value)}
                    >
                      {value === "positive" ? <CheckCircle2 size={15} /> : value === "negative" ? <TriangleAlert size={15} /> : <Trash2 size={15} />}
                      {decisionLabel(value)}
                    </VButton>
                  ))}
                </div>

                <div className={styles.formGrid}>
                  <label className={styles.formField}>
                    <span>{lang === "zh" ? "原因分类" : "Reason code"}</span>
                    <select
                      value={reasonCode}
                      disabled={detailCandidate.status !== "pending"}
                      onChange={(event) => setReasonCode(event.target.value)}
                    >
                      <option value="">{lang === "zh" ? "未填写" : "Not set"}</option>
                      {reasonOptions.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>

                  {draftDecision === "negative" ? (
                    <label className={styles.formField}>
                      <span>{lang === "zh" ? "错误类型" : "Error type"}</span>
                      <input
                        type="text"
                        value={errorType}
                        disabled={detailCandidate.status !== "pending"}
                        onChange={(event) => setErrorType(event.target.value)}
                        placeholder={lang === "zh" ? "例如：ungrounded_inference" : "For example: ungrounded_inference"}
                      />
                    </label>
                  ) : null}

                  {draftDecision === "negative" ? (
                    <label className={styles.formField}>
                      <span>{lang === "zh" ? "正确原则" : "Correct principle"}</span>
                      <input
                        type="text"
                        value={correctPrinciple}
                        disabled={detailCandidate.status !== "pending"}
                        onChange={(event) => setCorrectPrinciple(event.target.value)}
                        placeholder={lang === "zh" ? "例如：先查日志再下判断" : "For example: inspect logs before concluding"}
                      />
                    </label>
                  ) : null}

                  {draftDecision === "negative" ? (
                    <label className={styles.formField}>
                      <span>{lang === "zh" ? "理想做法" : "Ideal behavior"}</span>
                      <input
                        type="text"
                        value={idealBehavior}
                        disabled={detailCandidate.status !== "pending"}
                        onChange={(event) => setIdealBehavior(event.target.value)}
                        placeholder={lang === "zh" ? "补一句理想的处理方式" : "Describe the better behavior"}
                      />
                    </label>
                  ) : null}
                </div>

                <label className={styles.textAreaField}>
                  <span>{lang === "zh" ? "评审备注" : "Reviewer note"}</span>
                  <textarea
                    value={reviewerNote}
                    disabled={detailCandidate.status !== "pending"}
                    onChange={(event) => setReviewerNote(event.target.value)}
                    placeholder={lang === "zh" ? "给未来的 agent 留一句人话提醒" : "Leave one human-readable reminder for the future agent"}
                  />
                </label>

                <div className={styles.actionRow}>
                  <VButton
                    type="button"
                    className={styles.primaryAction}
                    isDisabled={detailCandidate.status !== "pending" || decisionMutation.isPending}
                    onClick={submitCurrentDecision}
                  >
                    {decisionMutation.isPending ? <LoaderCircle size={15} className={styles.spin} /> : <LibraryBig size={15} />}
                    {lang === "zh" ? "保存裁决" : "Save decision"}
                  </VButton>
                  <NavLink to={consoleTarget} className={styles.secondaryAction}>
                    <ArrowUpRight size={15} />
                    {positiveDatasetVisible
                      ? (lang === "zh" ? "回控制台并预选正例集" : "Return with positive dataset")
                      : (lang === "zh" ? "回到监督控制台" : "Back to supervised console")}
                  </NavLink>
                </div>

                {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
                {decisionError ? <p className={styles.errorText}>{decisionError}</p> : null}
                {positiveDatasetVisible ? (
                  <p className={styles.hintText}>
                    {lang === "zh"
                      ? "当前正例数据集已经可用，回到监督控制台后可以直接基于它发起下一轮监督运行。"
                      : "The positive dataset is already available. Return to the supervised console to launch the next run with it."}
                  </p>
                ) : null}
              </section>

              <details className={styles.transcriptSection}>
                <summary>{lang === "zh" ? "完整对话与来源" : "Full transcript and provenance"}</summary>
                <div className={styles.transcriptMeta}>
                  <article className={styles.metaRow}>
                    <strong>{lang === "zh" ? "来源日志" : "Source log"}</strong>
                    <span>{detailCandidate.sourceLogPath || "--"}</span>
                  </article>
                  <article className={styles.metaRow}>
                    <strong>{lang === "zh" ? "正例数据集" : "Positive dataset"}</strong>
                    <span>{reviewData?.positiveDatasetPath || "--"}</span>
                  </article>
                  <article className={styles.metaRow}>
                    <strong>{lang === "zh" ? "负例数据集" : "Negative dataset"}</strong>
                    <span>{reviewData?.negativeDatasetPath || "--"}</span>
                  </article>
                </div>
                <div className={styles.transcriptList}>
                  {detailCandidate.conversationTurns.map((turn) => (
                    <article key={`${detailCandidate.candidateId}-transcript-${turn.turnNumber}`} className={styles.transcriptCard}>
                      <div className={styles.evidenceTop}>
                        <strong>{`Turn ${turn.turnNumber}`}</strong>
                        <span>{turn.toolCalls.join(", ") || "--"}</span>
                      </div>
                      <p>{lang === "zh" ? `用户：${turn.userMessage}` : `User: ${turn.userMessage}`}</p>
                      <p>{lang === "zh" ? `助手：${turn.assistantMessage}` : `Assistant: ${turn.assistantMessage}`}</p>
                    </article>
                  ))}
                </div>
              </details>
            </>
          ) : (
            <div className={styles.emptyState}>
              <h3>{lang === "zh" ? "还没有可审的样本" : "No reviewable samples yet"}</h3>
              <p>{lang === "zh" ? "先在对话 / 编码里积累几轮真实任务，多轮样本会自动进入这里。" : "Accumulate a few real turns in Chat / Coding and reusable multi-turn samples will appear here."}</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
