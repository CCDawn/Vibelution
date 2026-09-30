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

  it("keeps task rows as status dot + title + kind badge + relative time", () => {
    expect(routeSource).toContain("auxTaskStatusTone(task.status)");
    expect(routeSource).toContain("<VChip");
    expect(routeSource).toContain("auxTaskKindLabel(task.kind, lang)");
    expect(routeSource).toContain("formatRelativeTime(task.startedAt, lang)");
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

  it("keeps decorative workbench backgrounds on stable surface tokens", () => {
    expect(styles.routeClass).toContain("!bg-vui-surface-panel");
    expect(styles.taskRowClass).toContain("!bg-vui-surface-row");
    expect(styles.emptyStateClass).toContain("bg-vui-surface-row");
  });
});
