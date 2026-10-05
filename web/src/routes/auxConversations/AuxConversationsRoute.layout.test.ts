import { describe, expect, it } from "vitest";

import routeSource from "./AuxConversationsRoute.tsx?raw";
import styles from "./AuxConversationsRoute.styles";
import presentationSource from "./auxTaskPresentation.ts?raw";
import apiSource from "../../api/runtimeTasks.ts?raw";
import routerSource from "../../app/router.tsx?raw";
import layoutIdsSource from "../../components/layout/workbenchLayoutIds.ts?raw";

describe("AuxConversationsRoute layout contract", () => {
  it("routes aux center controls through VUI primitives", () => {
    expect(routeSource).toContain('from "../../components/vui"');
    expect(routeSource).toContain("<VNativeButton");
    expect(routeSource).toContain("<VRouteLinkButton");
    expect(routeSource).not.toMatch(/<button\b/);
  });

  it("uses the list-detail page recipe with a registry layout id", () => {
    expect(routeSource).toContain("VListDetailPage");
    expect(routeSource).toContain("layoutId={WORKBENCH_LAYOUT_IDS.auxConversations}");
    expect(layoutIdsSource).toContain('auxConversations: "aux-conversations"');
    expect(routerSource).toContain('path: "aux"');
    expect(routerSource).toContain("<AuxConversationsRoute />");
  });

  it("splits the list into running and ended sections with counts", () => {
    expect(routeSource).toContain('aria-label={copy.running}');
    expect(routeSource).toContain('aria-label={copy.ended}');
    expect(routeSource).toContain("runningTasks.length");
    expect(routeSource).toContain("{endedTotal}");
    expect(presentationSource).toContain('running: "运行中"');
  });

  it("keeps directory rows as neutral icon + title + status word + kind/summary + relative time", () => {
    expect(routeSource).toContain("auxTaskStatusIcon(task.status)");
    expect(routeSource).toContain("auxTaskStatusLabel(task.status, lang)");
    expect(routeSource).toContain("auxTaskKindLabel(task.kind, lang)");
    // Ended rows age from endedAt, running rows from startedAt; no ticking seconds.
    expect(routeSource).toContain('String(task.endedAt || "").trim() || task.startedAt');
    expect(routeSource).toContain("formatRelativeTime(timestamp, lang)");
    // Row-level presentation stays neutral: no tone dots or kind chips.
    expect(routeSource).not.toContain("auxTaskStatusTone(task.status)");
    expect(routeSource).not.toContain("<VChip");
    expect(routeSource).not.toContain("statusDotChipClass");
  });

  it("renders the seven-state glyph map from the presentation module", () => {
    expect(presentationSource).toContain("LoaderCircle");
    expect(presentationSource).toContain("PauseCircle");
    expect(presentationSource).toContain("CheckCircle2");
    expect(presentationSource).toContain("CircleAlert");
    expect(presentationSource).toContain("Ban");
    expect(presentationSource).toContain("CircleDashed");
    expect(routeSource).toContain("styles.taskRowIconSpinClass");
  });

  it("keeps the running-row stop action outside the row button", () => {
    expect(routeSource).toContain("onAskStop");
    expect(routeSource).toContain("event.stopPropagation()");
    expect(routeSource).toContain('aria-label={stopLabel}');
    // Ended rows carry no inline actions.
    expect(routeSource).toContain("if (!onAskStop)");
  });

  it("pages the ended directory 20 at a time", () => {
    expect(routeSource).toContain("AUX_ENDED_PAGE_SIZE = 20");
    expect(routeSource).toContain("limit: AUX_ENDED_PAGE_SIZE");
    expect(routeSource).toContain('loadMore: "再显示 20 个"');
  });

  it("keeps a running-section empty line and drops the ended-section copy", () => {
    expect(routeSource).toContain('noRunningTasks: "没有正在运行的任务"');
    expect(routeSource).not.toContain("noEndedTasks");
  });

  it("writes the section counts inline after the section titles", () => {
    expect(routeSource).toContain("{copy.running} · {runningTasks.length}");
    expect(routeSource).toContain("{copy.ended} · {endedTotal}");
  });

  it("polls only while the page is visible on the 4s beat", () => {
    expect(routeSource).toContain("usePageVisibility");
    expect(routeSource).toContain("refetchInterval: resolvePollingInterval(pageVisible, AUX_TASKS_POLL_MS)");
    expect(routeSource).toContain("refetchIntervalInBackground: false");
    expect(routeSource).toContain("export const AUX_TASKS_POLL_MS = 4_000;");
  });

  it("dedupes polls through the revision-aware list fetch", () => {
    expect(routeSource).toContain("listRuntimeTasksRevisionAware");
    expect(routeSource).toContain("queryClient.getQueryData<RuntimeTaskListPayload>(listKey)");
    expect(apiSource).toContain("export async function listRuntimeTasksRevisionAware");
    expect(apiSource).toContain("return previous;");
  });

  it("loads more ended tasks through the cursor contract", () => {
    expect(routeSource).toContain('status: "ended"');
    expect(routeSource).toContain("cursor: endedCursor");
    expect(apiSource).toContain("params.set(\"cursor\"");
  });

  it("wires the user stop intent through the shared confirm dialog", () => {
    expect(routeSource).toContain("<VConfirmDialog");
    expect(routeSource).toContain('tone="danger"');
    expect(routeSource).toContain("stopMutation.mutate(stopTargetId)");
    expect(apiSource).toContain('body: JSON.stringify({ initiator: "user" })');
  });

  it("opens child sessions in the chat workbench instead of a second event stream", () => {
    expect(routeSource).toContain("childSessionHref(selectedTask.childSessionId)");
    expect(apiSource).toContain("export function childSessionHref");
    expect(apiSource).toContain("/chat?session=");
    expect(routeSource).not.toContain("EventSource");
    expect(routeSource).not.toContain("useSessionDetailStream");
  });

  it("embeds the canon read-only chat workspace fed by the session detail window", () => {
    expect(routeSource).toContain("ChatReadOnlySessionWorkspace");
    expect(routeSource).toContain("fetchSessionDetailWindow");
    expect(routeSource).toContain('transcriptScope: "window"');
    // Aux keeps its own cache key: the snapshot must never overwrite the
    // /chat live-transcript cache entries.
    expect(routeSource).toContain('queryKey: ["aux-session-detail", selectedChildSessionId]');
    // Poll discipline mirrors the task list: live 4s beats only, background off,
    // ended tasks take a single snapshot.
    expect(routeSource).toContain("refetchInterval: selectedChildSessionId && selectedIsLive");
    expect(routeSource).toContain("refetchIntervalInBackground: false");
    // The synthetic timeline is the no-stream fallback only.
    expect(routeSource).toContain("selectedChildSessionId ?");
  });

  it("keeps the route local and shell-language only", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const COPY = {");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("uses independent scroll regions for list and detail", () => {
    expect(styles.routeClass).toContain("overflow-hidden");
    expect(styles.taskListClass).toContain("overflow-auto");
    expect(styles.detailContentClass).toContain("overflow-auto");
    expect(styles.taskRowClass).toContain("min-w-0");
    expect(styles.detailPaneClass).toContain("min-w-0");
  });

  it("gives the embedded stream its own scroll region inside the detail pane", () => {
    expect(styles.detailStreamLayoutClass).toContain("min-h-0");
    expect(styles.detailStreamLayoutClass).toContain("overflow-hidden");
    expect(styles.detailStreamHeadClass).toContain("shrink-0");
    // The stream body takes the remaining height; the panel scrolls inside it.
    expect(styles.detailStreamBodyClass).toContain("flex-1");
    expect(styles.detailStreamBodyClass).toContain("min-h-0");
    expect(styles.detailStreamBodyClass).toContain("overflow-hidden");
  });

  it("keeps decorative workbench backgrounds on stable surface tokens", () => {
    expect(styles.routeClass).toContain("!bg-vui-surface-panel");
    expect(styles.taskRowClass).toContain("!bg-vui-surface-row");
    expect(styles.emptyStateClass).toContain("bg-vui-surface-row");
  });
});
