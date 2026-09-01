import { readFileSync } from "node:fs";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import conversationStyles from "../components/conversation/ConversationView.styles";
import conversationStylesModuleSource from "../components/conversation/ConversationView.styles.ts?raw";
import conversationViewSource from "../components/conversation/ConversationView.tsx?raw";
import routeErrorBoundarySource from "../app/RouteErrorBoundary.tsx?raw";
import routerSource from "../app/router.tsx?raw";
import shellStoreSource from "../store/shellStore.ts?raw";
import chatApiSource from "../api/chat.ts?raw";
import agentsApiSource from "../api/agents.ts?raw";
import filesApiSource from "../api/files.ts?raw";
import cliAgentsApiSource from "../api/cliAgents.ts?raw";
import agentSessionTabStripSource from "./AgentSessionTabStrip.tsx?raw";
import chatCodingRouteWorkbenchSource from "./chat/ChatCodingRouteWorkbench.tsx?raw";
import chatWorkbenchCatalogQueriesSource from "./chat/useChatWorkbenchCatalogQueries.ts?raw";
import chatCenterTabStripSource from "./chat/ChatCenterTabStrip.tsx?raw";
import chatCenterSessionSurfaceSource from "./chat/ChatCenterSessionSurface.tsx?raw";
import chatConversationIndexPanelContentSource from "./chat/ChatConversationIndexPanelContent.tsx?raw";
import chatToolApprovalBridgeSource from "./chat/useChatToolApprovalBridge.ts?raw";
import chatComposerBridgeStateSource from "./chat/useChatComposerBridgeState.ts?raw";
import chatGroupRoomViewModelSource from "./chat/useChatGroupRoomViewModel.ts?raw";
import chatGroupDraftStateSource from "./chat/useChatGroupDraftState.ts?raw";
import chatGroupRoomActionModelSource from "./chat/chatGroupRoomActionModel.ts?raw";
import chatWorkbenchContextMenusSource from "./chat/useChatWorkbenchContextMenus.ts?raw";
import chatConversationIndexChromeSource from "./chat/useChatConversationIndexChrome.ts?raw";
import chatSessionWorkbenchShellSource from "./chat/ChatSessionWorkbenchShell.tsx?raw";
import chatWorkbenchCenterColumnSource from "./chat/ChatWorkbenchCenterColumn.tsx?raw";
import chatWorkbenchFormatSource from "./chat/chatWorkbenchFormat.ts?raw";
import chatWorkbenchPresentationSource from "./chat/useChatWorkbenchPresentation.ts?raw";
import conversationIndexRailSource from "./chat/ChatConversationIndexRail.tsx?raw";
import sessionBulkOperationsPanelSource from "./chat/SessionBulkOperationsPanel.tsx?raw";
import chatSessionBulkModelSource from "./chat/chatSessionBulkModel.ts?raw";
import chatSessionBulkSelectionSource from "./chat/useChatSessionBulkSelection.ts?raw";
import chatWorkbenchConfirmDialogSource from "./chat/useChatWorkbenchConfirmDialog.ts?raw";
import chatVisibleSessionCatalogSource from "./chat/useChatVisibleSessionCatalog.ts?raw";
import chatAgentSessionTabsSource from "./chat/useChatAgentSessionTabs.ts?raw";
import chatSessionIndexRailModelSource from "./chat/useChatSessionIndexRailModel.ts?raw";
import chatGroupRoomChromeModelSource from "./chat/useChatGroupRoomChromeModel.ts?raw";
import chatVisibleSessionCatalogModelSource from "./chat/chatVisibleSessionCatalogModel.ts?raw";
import chatSessionIndexRailPresentationSource from "./chat/chatSessionIndexRailPresentation.ts?raw";
import chatAgentDirectoryMapsSource from "./chat/chatAgentDirectoryMaps.ts?raw";
import chatAgentDirectoryMapsHookSource from "./chat/useChatAgentDirectoryMaps.ts?raw";
import chatIndexDerivedStateSource from "./chat/useChatIndexDerivedState.ts?raw";
import agentDirectoryActionsSource from "./chat/useChatAgentDirectoryActions.ts?raw";
import chatStatusRailSource from "./chat/ChatStatusRail.tsx?raw";
import chatComposerPlusMenuSource from "./chat/ChatComposerPlusMenu.tsx?raw";
import chatComposerPlusMenuStyles from "./chat/ChatComposerPlusMenu.styles";
import chatGroupManagementDialogSource from "./chat/ChatGroupManagementDialog.tsx?raw";
import chatGroupManagementDialogStyles from "./chat/ChatGroupManagementDialog.styles";
import cliAgentRunModelSource from "./chat/cliAgentRunModel.ts?raw";
import sessionCacheCompositionSource from "./chat/sessionCacheComposition.ts?raw";
import chatSubmitTelemetrySource from "./chat/chatSubmitTelemetry.ts?raw";
import chatComposerSubmitModelSource from "./chat/chatComposerSubmitModel.ts?raw";
import chatComposerSubmitHookSource from "./chat/useChatComposerSubmit.ts?raw";
import chatActiveTurnLayerSource from "./chatActiveTurnLayer.ts?raw";
import chatStreamApplyControllerSource from "./chatStreamApplyController.ts?raw";
import terminalPanelSource from "./chat/CliAgentRunTerminalPanel.tsx?raw";
import conversationIndexModelSource from "./conversationIndexModel.ts?raw";
import conversationIndexTreeSource from "./ConversationIndexTree.tsx?raw";
import conversationIndexTreeStyles from "./ConversationIndexTree.styles";
import conversationIndexSectionSource from "./ConversationIndexSection.tsx?raw";
import conversationIndexSectionStyles from "./ConversationIndexSection.styles";
import directSessionIndexItemStyles from "./DirectSessionIndexItem.styles";
import directSessionIndexItemSource from "./DirectSessionIndexItem.tsx?raw";
import directSessionIndexListSource from "./DirectSessionIndexList.tsx?raw";
import groupSessionIndexItemsStyles from "./GroupSessionIndexItems.styles";
import groupSessionIndexItemsSource from "./GroupSessionIndexItems.tsx?raw";
import sessionContextMenuStyles from "./SessionContextMenu.styles";
import sessionContextMenuSource from "./SessionContextMenu.tsx?raw";
import agentContextMenuSource from "./AgentContextMenu.tsx?raw";
import agentConversationDirectorySource from "./AgentConversationDirectory.tsx?raw";
import agentSessionTabStripStyles from "./AgentSessionTabStrip.styles";
import routeStylesBase from "./ChatCodingRoute.styles";
import cacheDetailStyles from "./chat/CacheDetailDialog.styles";
import conversationIndexRailStyles from "./chat/ChatConversationIndexRail.styles";
import chatStatusRailStyles from "./chat/ChatStatusRail.styles";
import tokenCoreStatusPanelStyles from "./chat/TokenCoreStatusPanel.styles";

/** Workbench shell + catalog queries hook (R01c F1) + Phase F2/F3 extract modules. */
const routeSource = [
  chatCodingRouteWorkbenchSource,
  chatWorkbenchCatalogQueriesSource,
  chatToolApprovalBridgeSource,
  chatComposerBridgeStateSource,
  chatGroupRoomViewModelSource,
  chatGroupDraftStateSource,
  chatGroupRoomActionModelSource,
  chatWorkbenchContextMenusSource,
  chatConversationIndexChromeSource,
  chatVisibleSessionCatalogSource,
  chatAgentSessionTabsSource,
  chatSessionIndexRailModelSource,
  chatGroupRoomChromeModelSource,
  chatVisibleSessionCatalogModelSource,
  chatSessionIndexRailPresentationSource,
  chatAgentDirectoryMapsSource,
  chatAgentDirectoryMapsHookSource,
  chatIndexDerivedStateSource,
].join("\n");

/** Wave 8C/8D: layout contracts resolve class strings across route shell + panel/component maps. */
const routeStyles = {
  ...routeStylesBase,
  ...cacheDetailStyles,
  ...conversationIndexRailStyles,
  ...chatStatusRailStyles,
  ...tokenCoreStatusPanelStyles,
  ...agentSessionTabStripStyles,
  ...sessionContextMenuStyles,
  ...directSessionIndexItemStyles,
  ...groupSessionIndexItemsStyles,
  ...conversationIndexSectionStyles,
  ...cliAgentRunTerminalPanelStyles,
  ...chatSessionWorkspacePanelStyles,
  ...chatToolApprovalDialogStyles,
  ...chatFileWorkspaceTabsStyles,
  ...chatFilePreviewPanelStyles,
  ...chatLoadingShellStyles,
  ...chatRuntimeNoticeStackStyles,
  // Legacy aliases after donut key rename (cacheDonutShell → cacheDetailDonutShell).
  cacheDonutShell: cacheDetailStyles.cacheDonutShell ?? cacheDetailStyles.cacheDetailDonutShell,
  cacheDonutStats: cacheDetailStyles.cacheDonutStats ?? cacheDetailStyles.cacheDetailDonutLegend,
} as Record<string, string>;
import routeStylesModuleSource from "./ChatCodingRoute.styles.ts?raw";
import cacheDetailDialogSource from "./chat/CacheDetailDialog.tsx?raw";
import chatConversationComposerBridgeSource from "./chat/ChatConversationComposerBridge.tsx?raw";
import chatConversationComposerBridgeTestSource from "./chat/ChatConversationComposerBridge.test.ts?raw";
import chatFilePreviewPanelStyles from "./chat/ChatFilePreviewPanel.styles";
import chatFilePreviewPanelSource from "./chat/ChatFilePreviewPanel.tsx?raw";
import chatFileWorkspaceTabsStyles from "./chat/ChatFileWorkspaceTabs.styles";
import chatFileWorkspaceTabsSource from "./chat/ChatFileWorkspaceTabs.tsx?raw";
import chatLoadingShellStyles from "./chat/ChatLoadingShell.styles";
import chatRuntimeNoticeStackStyles from "./chat/ChatRuntimeNoticeStack.styles";
import chatRuntimeNoticeStackSource from "./chat/ChatRuntimeNoticeStack.tsx?raw";
import chatSessionWorkspacePanelStyles from "./chat/ChatSessionWorkspacePanel.styles";
import chatSessionWorkspacePanelSource from "./chat/ChatSessionWorkspacePanel.tsx?raw";
import chatCodingRouteViewModelSource from "./chat/chatCodingRouteViewModel.ts?raw";
import chatWorkbenchLayoutSource from "./chat/useChatWorkbenchLayout.ts?raw";
import chatSessionStreamConnectSource from "./chat/chatSessionStreamConnect.ts?raw";
import sessionDetailStreamSource from "./chat/useSessionDetailStream.ts?raw";
import groupRoomStreamSource from "./chat/useGroupRoomStream.ts?raw";
import chatRoomEventStreamSource from "./chat/chatRoomEventStream.ts?raw";
import chatSessionSelectionSource from "./chat/useChatSessionSelection.ts?raw";
import chatArchivedAgentRetirementSource from "./chat/useChatArchivedAgentRetirement.ts?raw";
import chatSessionDetailHelpersSource from "./chat/chatSessionDetailHelpers.ts?raw";
import chatRoutePresentationSource from "./chat/chatRoutePresentation.tsx?raw";
import chatWorkspaceLifecycleSource from "./chat/useChatWorkspaceLifecycle.ts?raw";
import chatSessionDetailMutationsSource from "./chat/useChatSessionDetailMutations.ts?raw";
import chatWorkspaceActionsSource from "./chat/useChatWorkspaceActions.ts?raw";
import chatGroupMessagePresentationSource from "./chat/ChatGroupMessagePresentation.tsx?raw";
import chatSessionRenameMenuSource from "./chat/useChatSessionRenameMenu.ts?raw";
import chatCliAgentTerminalSource from "./chat/useChatCliAgentTerminal.ts?raw";
import chatCacheDetailModelSource from "./chat/chatCacheDetailModel.ts?raw";
import chatCacheDetailDialogSource from "./chat/useChatCacheDetailDialog.ts?raw";
import chatTokenStatusModelSource from "./chat/chatTokenStatusModel.ts?raw";
import chatGroupCenterSurfaceSource from "./chat/ChatGroupCenterSurface.tsx?raw";
import chatGroupCenterSurfaceStyles from "./chat/ChatGroupCenterSurface.styles";
import chatGroupMessagePresentationStyles from "./chat/ChatGroupMessagePresentation.styles";
import chatCliAgentTerminalStackSource from "./chat/ChatCliAgentTerminalStack.tsx?raw";
import chatCliAgentTerminalStackStyles from "./chat/ChatCliAgentTerminalStack.styles";
import chatSessionSurfaceModelSource from "./chat/chatSessionSurfaceModel.ts?raw";
import chatToolApprovalDialogStyles from "./chat/ChatToolApprovalDialog.styles";
import chatToolApprovalDialogSource from "./chat/ChatToolApprovalDialog.tsx?raw";
import { ChatToolApprovalDialog } from "./chat/ChatToolApprovalDialog";
import cliAgentRunTerminalPanelStyles from "./chat/CliAgentRunTerminalPanel.styles";
import llmPayloadTracePanelSource from "./chat/LlmPayloadTracePanel.tsx?raw";
import { TokenCoreStatusPanel, type TokenCoreStatusMetric } from "./chat/TokenCoreStatusPanel";
import tokenCoreStatusPanelSource from "./chat/TokenCoreStatusPanel.tsx?raw";
import agentContextMenuStyles from "./AgentContextMenu.styles";

// Wave 8D: re-merge after late style imports so dead route keys resolve via component maps.
Object.assign(routeStyles, {
  ...conversationIndexTreeStyles,
  ...chatGroupCenterSurfaceStyles,
  ...chatGroupMessagePresentationStyles,
  ...chatCliAgentTerminalStackStyles,
  ...agentContextMenuStyles,
});

const appShellCssSource = readFileSync(new URL("../design/workbench-shell.css", import.meta.url), "utf-8");
const routeCssSource = [
  routeStylesModuleSource,
  ...Object.keys(routeStyles).map((key) => `.${key}`),
  ...Object.values(routeStyles),
].join("\n");
const conversationCssSource = [
  conversationStylesModuleSource,
  ...Object.keys(conversationStyles).map((key) => `.${key}`),
  ...Object.values(conversationStyles),
].join("\n");

function sliceRequiredSection(source: string, startMarker: string, endMarker: string) {
  const startIndex = source.indexOf(startMarker);
  expect(startIndex, `missing start marker: ${startMarker}`).toBeGreaterThanOrEqual(0);
  const endIndex = source.indexOf(endMarker, startIndex + startMarker.length);
  expect(endIndex, `missing end marker after ${startMarker}: ${endMarker}`).toBeGreaterThan(startIndex);
  return source.slice(startIndex, endIndex);
}

function expectOrderedFragments(source: string, fragments: string[]) {
  let cursor = 0;
  for (const fragment of fragments) {
    const index = source.indexOf(fragment, cursor);
    expect(index, `missing fragment: ${fragment}`).toBeGreaterThanOrEqual(0);
    cursor = index + fragment.length;
  }
}

const tokenCoreStatusMetrics: TokenCoreStatusMetric[] = [
  {
    key: "cache",
    label: "缓存",
    value: "--",
    meta: "暂无详情",
    title: "缓存详情不可用",
    percent: 0,
    tone: "cache",
  },
  {
    key: "modelInput",
    label: "模型输入",
    value: "12k",
    meta: "上一轮",
    title: "模型输入 token",
    percent: 40,
    tone: "modelInput",
  },
  {
    key: "compression",
    label: "压缩状态",
    value: "72%",
    meta: "阈值",
    title: "压缩状态",
    percent: 72,
    tone: "compression",
  },
  {
    key: "speed",
    label: "响应速度",
    value: "快",
    meta: "估算",
    title: "响应速度",
    percent: 80,
    tone: "speed",
  },
];

const routeAndIndexRailSource = `${routeSource}\n${conversationIndexRailSource}\n${chatStatusRailSource}\n${chatConversationIndexPanelContentSource}`;
const routeAndLayoutSource = `${routeSource}\n${chatWorkbenchLayoutSource}\n${chatSessionWorkbenchShellSource}\n${chatWorkbenchCenterColumnSource}`;
const routeAndCenterPackSource = `${routeSource}\n${chatCenterTabStripSource}\n${chatCenterSessionSurfaceSource}\n${chatWorkbenchCenterColumnSource}\n${chatSessionWorkbenchShellSource}`;
const routeAndPresentationSource = `${routeSource}\n${chatWorkbenchPresentationSource}\n${chatWorkbenchFormatSource}`;
const routeAndComposerSource = `${routeSource}\n${chatComposerSubmitModelSource}\n${chatComposerSubmitHookSource}\n${chatActiveTurnLayerSource}\n${chatSubmitTelemetrySource}`;
const routeAndStreamSource = `${routeSource}\n${sessionDetailStreamSource}\n${groupRoomStreamSource}\n${chatRoomEventStreamSource}\n${chatSessionStreamConnectSource}\n${chatStreamApplyControllerSource}\n${chatActiveTurnLayerSource}`;
const routeAndSelectionSource = `${routeSource}\n${chatSessionSelectionSource}`;
const routeAndHelpersSource = `${routeSource}\n${chatSessionDetailHelpersSource}\n${chatRoutePresentationSource}`;
const routeAndLifecycleSource = `${routeSource}\n${chatWorkspaceLifecycleSource}\n${chatSessionDetailHelpersSource}`;
const routeAndDetailMutationsSource = `${routeSource}\n${chatSessionDetailMutationsSource}\n${chatApiSource}`;
const routeAndActionsSource = `${routeSource}\n${chatWorkspaceActionsSource}`;
const routeAndGroupPresentationSource = `${routeSource}\n${chatGroupMessagePresentationSource}\n${chatRoutePresentationSource}`;
const routeAndRenameMenuSource = `${routeSource}\n${chatSessionRenameMenuSource}`;
const routeAndCliTerminalSource = `${routeSource}\n${chatCliAgentTerminalSource}\n${cliAgentRunModelSource}`;
const routeAndCacheDetailSource = `${routeSource}\n${chatCacheDetailModelSource}\n${chatCacheDetailDialogSource}\n${sessionCacheCompositionSource}\n${chatRoutePresentationSource}`;
const routeAndTokenStatusSource = `${routeSource}\n${chatTokenStatusModelSource}`;
const routeAndGroupCenterSource = `${routeSource}\n${chatGroupCenterSurfaceSource}\n${chatGroupMessagePresentationSource}\n${chatRoutePresentationSource}`;
const routeAndCliStackSource = `${routeSource}\n${chatCliAgentTerminalStackSource}\n${chatCliAgentTerminalSource}\n${cliAgentRunModelSource}`;
const routeAndSessionSurfaceSource = `${routeSource}\n${chatSessionSurfaceModelSource}`;

describe("ChatCodingRoute layout contract", () => {
  it("keeps the center conversation readable and the composer as a stable bottom layer", () => {
    expect(conversationStyles.timeline).toBeTypeOf("string");
    expect(conversationStyles.markdownBody).toBeTypeOf("string");
    expect(conversationStyles.operationSummary).toBeTypeOf("string");
    expect(conversationStyles.composer).toBeTypeOf("string");
    expect(conversationStyles.sendButton).toBeTypeOf("string");
    expect(conversationStyles.assistantTurn).toBeTypeOf("string");
    expect(conversationStyles.turnContent).toBeTypeOf("string");
    expect(conversationStyles.responseSegment_status).toBeTypeOf("string");
    expect(conversationStyles.userMessageBody).toBeTypeOf("string");
    expect(conversationStyles.messageBody).toBeTypeOf("string");
    expect(conversationStyles.imageArtifact).toBeTypeOf("string");
    expect(conversationStyles.imageDownloadButton).toBeTypeOf("string");
  });

  it("keeps the center conversation as an opaque product board over theme wallpaper", () => {
    expect(appShellCssSource).toContain("--theme-background-overlay-mid: color-mix(in srgb, var(--bg-canvas) 34%, transparent);");
    expect(appShellCssSource).toContain("--theme-background-overlay-mid: color-mix(in srgb, var(--bg-canvas) 18%, transparent);");
    expect(appShellCssSource).toContain("--theme-background-overlay-mid: color-mix(in srgb, var(--bg-canvas) 44%, transparent);");
    expect(appShellCssSource).toContain("--theme-background-overlay-mid: color-mix(in srgb, var(--bg-canvas) 60%, transparent);");
    expect(routeStyles.centerPane).toMatch(/!bg-vui-surface-chat|bg-\[var\(--vui-surface-chat\)\]/);
    expect(routeStyles.centerSurface).toMatch(/!bg-vui-surface-chat|!bg-\[var\(--vui-surface-chat\)\]/);
    expect(routeStyles.centerSurface).not.toContain("transparent");
    expect(routeStyles.centerSurface).not.toContain("color-mix");
    expect(conversationStyles.timeline).toContain("bg-[var(--vui-surface-chat)]");
    expect(conversationStyles.surface).toContain("bg-[var(--vui-surface-chat)]");
    expect(conversationStyles.surfaceCompact).toContain("[&_.timeline]:bg-[var(--vui-surface-chat)]");
    expect(appShellCssSource).not.toContain("--theme-background-overlay-mid: rgba(");
    expect(routeCssSource).not.toContain("background: color-mix(in srgb, var(--surface-page) 92%, var(--bg-canvas));");
  });

  it("keeps empty chat states centered inside the full-height conversation workspace", () => {
    expect(routeStyles.layout).toContain("h-[calc(100dvh_-_var(--shell-topbar-height))]");
    expect(routeStyles.layout).toContain("overflow-hidden");
    expect(routeStyles.layout).toContain("[--chat-workbench-gap:4px]");
    expect(routeStyles.leftRail).toContain("h-full");
    expect(routeStyles.leftRail).toContain("min-h-0");
    expect(routeStyles.leftRail).toContain("overflow-auto");
    expect(routeStyles.centerPane).toContain("grid");
    expect(routeStyles.centerPane).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(routeStyles.centerPane).toContain("overflow-hidden");
    expect(routeStyles.centerSurface).toContain("grid");
    expect(routeStyles.centerSurface).toContain("h-full");
    expect(routeStyles.centerSurface).toContain("min-h-0");
    expect(routeStyles.centerSurface).toContain("overflow-hidden");
    expect(chatSessionWorkspacePanelSource).toContain("styles.conversationShell");
    expect(chatSessionWorkspacePanelStyles.conversationShell).toContain("h-full");
    expect(chatSessionWorkspacePanelStyles.conversationFrame).toContain("flex");
    expect(chatSessionWorkspacePanelStyles.conversationFrame).toContain("flex-1");
    expect(chatSessionWorkspacePanelStyles.conversationFrame).toContain("min-h-0");
    expect(chatSessionWorkspacePanelStyles.conversationFrame).toContain("overflow-hidden");
    expect(conversationStyles.surface).toContain("flex");
    expect(conversationStyles.surface).toContain("h-full");
    expect(conversationStyles.surface).toContain("min-h-0");
    expect(conversationStyles.surface).toContain("overflow-hidden");
    expect(conversationStyles.timeline).toContain("flex-1");
    expect(conversationStyles.timeline).toContain("min-h-0");
    expect(conversationStyles.timeline).toContain("overflow-y-auto");
    expect(conversationStyles.timeline).toContain("overflow-x-hidden");
    expect(conversationStyles.composer).toContain("flex-none");
    expect(chatSessionWorkspacePanelStyles.emptySurface).toContain("min-h-[min(420px,calc(100dvh_-_190px))]");
    expect(chatSessionWorkspacePanelStyles.emptySurface).toContain("place-items-center");
    expect(chatSessionWorkspacePanelStyles.emptySurface).toContain("text-center");
    expect(chatLoadingShellStyles.workspaceShell).toContain("h-full");
    expect(chatLoadingShellStyles.workspaceShell).toContain("min-h-0");
    expect(chatLoadingShellStyles.workspaceShell).toContain("grid-rows-[minmax(0,1fr)_auto]");
    expect(routeStyles.rightPane).toContain("h-full");
    expect(routeStyles.rightPane).toContain("overflow-hidden");
    expect(routeStyles.rightPaneWithTabs).toContain("grid-rows-[auto_auto_minmax(0,1fr)]");
    expect(routeStyles.rightPaneWithoutTabs).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(routeStyles.panelBody).toContain("min-h-0");
    expect(routeStyles.panelBody).toContain("h-full");
    expect(routeStyles.panelBody).toContain("overflow-auto");
    expect(routeStyles.panelBody).not.toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.panelBody).not.toMatch(/border border-vui-border-subtle|border border-\[var\(--vui-border-subtle\)\]/);
    expect(routeStyles.panelBody).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(routeStyles.panelBody).not.toContain("shadow-[var(--vui-shadow-hairline)]");
  });

  it("keeps the no-session center state compact on wide screens", () => {
    expect(routeSource).toContain("noSessionsLabel={t(\"noSessionsYet\")}");
    expect(chatSessionWorkspacePanelStyles.emptyConversationSurface).toContain("place-self-center");
    expect(chatSessionWorkspacePanelStyles.emptyConversationSurface).toContain("!w-[min(360px,calc(100%_-_32px))]");
    expect(chatSessionWorkspacePanelStyles.emptyConversationSurface).toContain("min-h-[74px]");
    expect(chatSessionWorkspacePanelStyles.emptyConversationSurface).toContain("!content-center");
    expect(chatSessionWorkspacePanelStyles.emptyConversationSurface).toContain("!text-center");
    expect(chatSessionWorkspacePanelStyles.emptyConversationSurface).not.toContain("h-full");
    expect(chatSessionWorkspacePanelStyles.emptyConversationSurface).not.toContain("min-h-[min(420px,calc(100dvh_-_190px))]");
  });

  it("uses a structural shell for loading and VStateSurface for terminal center states", () => {
    expect(chatSessionWorkspacePanelSource).toContain('import { VStateSurface } from "../../components/vui"');
    expect(chatSessionWorkspacePanelSource).toContain("ConversationWorkspaceLoadingShell");
    expect(chatSessionWorkspacePanelSource).not.toContain('tone="loading"');
    expect(chatSessionWorkspacePanelSource).toContain('tone="empty"');
    expect(chatSessionWorkspacePanelSource).toContain('tone="error"');
    expect(chatSessionWorkspacePanelSource).toContain('tone="unavailable"');
    expect(chatSessionWorkspacePanelSource).not.toContain("<div className={styles.emptyConversationSurface}");
    expect(chatSessionWorkspacePanelSource).not.toContain("<div className={styles.emptySurface}");
    expect(chatSessionWorkspacePanelStyles.emptySurface).toContain("!content-center");
    expect(chatSessionWorkspacePanelStyles.emptySurface).toContain("!text-center");
    for (const geometryClass of [
      chatSessionWorkspacePanelStyles.emptyConversationSurface,
      chatSessionWorkspacePanelStyles.emptySurface,
    ]) {
      expect(geometryClass).not.toContain("border");
      expect(geometryClass).not.toContain("bg-");
      expect(geometryClass).not.toContain("shadow");
    }
  });

  it("keeps the conversation page aligned to the V2.1 quiet light style system", () => {
    expect(conversationStyles.surfaceCompact).toContain("bg-[var(--vui-surface-chat)]");
    expect(conversationStyles.surfaceCompact).not.toContain("white)");
    expect(conversationStyles.surfaceCompact).not.toContain("bg-[var(--surface-panel-strong)]");

    expect(conversationStyles.composer).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(conversationStyles.composer).toMatch(/!bg-vui-surface-panel|!bg-\[var\(--vui-surface-panel\)\]/);
    expect(conversationStyles.composer).not.toContain("backdrop-blur");
    expect(conversationStyles.composer).not.toContain("var(--surface-panel-strong)_92%");

    expect(conversationStyles.sendButton).toContain("!bg-[var(--fg-primary)]");
    expect(conversationStyles.sendButton).toContain("focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)]");
    expect(conversationStyles.sendButton).toContain("shadow-none");
    expect(conversationStyles.sendButton).not.toContain("bg-[#");
    expect(conversationStyles.sendButton).not.toContain("-translate-y");
    expect(conversationStyles.attachButton).toMatch(/bg-\[|!bg-\[|var\(--vui-surface/);
    expect(conversationStyles.attachButton).toContain("active:bg-[color-mix(in_srgb,var(--vui-surface-workspace)_18%,var(--vui-control-muted-hover))]");
    expect(conversationStyles.stopButton).toContain("!border-[color-mix(in_srgb,var(--state-error)_34%,transparent)]");
    expect(conversationStyles.stopButton).toContain("!text-[var(--state-error)]");

    expect(conversationStyles.userCard).toMatch(/bg-\[|!bg-\[|var\(--vui-surface/);
    expect(conversationStyles.userCard).not.toContain("bg-[var(--surface-panel-strong)]");

    expect(directSessionIndexItemStyles.sessionItemActive).toContain("!bg-[color-mix(in_srgb,var(--accent-cool)_10%");
    expect(directSessionIndexItemStyles.sessionItemActive).toContain("data-[selected=true]:!bg-[color-mix(in_srgb,var(--accent-cool)_10%");
    expect(directSessionIndexItemStyles.sessionItemActive).not.toContain("shadow-[var(--vui-shadow-inset-accent)]");
    expect(routeStyles.sessionItemActive).not.toContain("linear-gradient");
    expect(routeStyles.sessionItemActive).not.toContain("shadow-lg");
  });

  it("renders runtime notices outside the Agent reply timeline", () => {
    expect(routeSource).toContain("detail?.runtimeNotices");
    expect(routeSource).toContain(".slice(-1)");
    expect(routeSource).toContain("<ChatSessionWorkspacePanel");
    expect(routeSource).toContain("notices={activeRuntimeNotices}");
    expect(chatSessionWorkspacePanelSource).toContain("<ChatRuntimeNoticeStack");
    expect(chatSessionWorkspacePanelSource.indexOf("<ChatRuntimeNoticeStack")).toBeLessThan(
      chatSessionWorkspacePanelSource.indexOf("<ChatConversationComposerBridge"),
    );
    expect(chatSessionWorkspacePanelSource).not.toContain("ChatCodingRoute.styles");
    expect(chatSessionWorkspacePanelSource).not.toContain("useQuery");
    expect(chatSessionWorkspacePanelSource).not.toContain("useMutation");
    expect(routeStylesModuleSource).not.toContain("runtimeNoticeStack:");
    expect(routeStylesModuleSource).not.toContain("runtimeNoticeMessage:");
    expect(chatRuntimeNoticeStackSource).toContain("role=\"status\"");
    expect(chatRuntimeNoticeStackSource).toContain("runtimeNoticeToneClassName");
    expect(chatRuntimeNoticeStackSource).toContain("VErrorSummary");
    expect(chatRuntimeNoticeStackSource).toContain("summarizeErrorText");
    expect(chatRuntimeNoticeStackStyles.stack).toBeTypeOf("string");
    expect(chatRuntimeNoticeStackStyles.stack).toContain("bg-transparent");
    expect(chatRuntimeNoticeStackStyles.stack).toContain("shadow-none");
    expect(chatRuntimeNoticeStackStyles.stack).not.toContain("vui-surface-glass");
    expect(chatRuntimeNoticeStackStyles.stack).not.toContain("vui-shadow-hairline");
    expect(chatRuntimeNoticeStackStyles.notice).toContain("grid-cols-[16px_minmax(0,1fr)]");
    expect(chatRuntimeNoticeStackStyles.notice).toMatch(/!bg-vui-surface-panel|!bg-\[var\(--vui-surface-panel\)\]/);
    expect(chatRuntimeNoticeStackStyles.notice).toContain("shadow-none");
    expect(chatRuntimeNoticeStackStyles.notice).not.toContain("vui-surface-glass");
    expect(chatRuntimeNoticeStackStyles.notice).not.toContain("vui-shadow-hairline");
    expect(chatRuntimeNoticeStackStyles.message).toBeTypeOf("string");
    expect(chatRuntimeNoticeStackStyles.toneWarning).toContain("var(--state-warning)");
  });

  it("surfaces pending tool approvals as an in-session dialog", () => {
    expect(routeSource).toContain("pendingToolGovernanceRequests");
    expect(routeSource).toContain("sessionToolApprovalsQuery");
    expect(routeSource).toContain("queryKeys.sessionToolApprovals");
    expect(routeSource).toContain("listPendingSessionToolApprovals");
    expect(chatApiSource).toContain("/tool-approvals?status=pending");
    expect(routeSource).toContain("runtimeHasChatTurnForSession(runtime, activeSessionId)");
    expect(routeSource).toContain("sessionToolApprovalRuntimeActive");
    expect(routeSource).toContain("resolveToolApprovalMutation");
    expect(routeAndDetailMutationsSource).toContain("resolveSessionToolApprovalDecision");
    expect(chatApiSource).toContain("/tool-approvals/");
    expect(routeAndDetailMutationsSource).toContain('"acceptForSession"');
    expect(routeSource).toContain('"acceptAlways"');
    expect(routeAndDetailMutationsSource).toContain("resolveAgentToolGovernanceRequest");
    expect(routeSource).toContain("onApproveToolApproval={handleApproveToolApproval}");
    expect(routeSource).toContain("if (!pendingToolGovernanceApproval) {");
    expect(routeSource).toContain("resolveToolApprovalMutation.mutate({ request: pendingToolGovernanceApproval, decision: \"approve\" })");
    expect(routeSource).toContain("onRejectToolApproval={handleRejectToolApproval}");
    expect(routeSource).toContain("resolveToolApprovalMutation.mutate({ request: pendingToolGovernanceApproval, decision: \"reject\" })");
    expect(chatSessionWorkspacePanelSource).toContain("<ChatToolApprovalDialog");
    expect(chatSessionWorkspacePanelSource).toContain("variant=\"banner\"");
    // Composer-adjacent host (not sticky column top).
    expect(chatSessionWorkspacePanelSource).toContain('data-chat-tool-approval-host="composer"');
    expect(chatSessionWorkspacePanelSource).not.toContain("toolApprovalHost");
    expect(chatSessionWorkspacePanelSource).not.toContain("sticky top-0");
    expect(chatSessionWorkspacePanelSource).toContain("toolApproval={approvalSurface}");
    expect(chatSessionWorkspacePanelSource).toContain("conversationShell");
    expect(chatSessionWorkspacePanelSource).toContain('from "./ChatToolApprovalDialog"');
    expect(chatSessionWorkspacePanelSource.indexOf("<ChatToolApprovalDialog")).toBeLessThan(
      chatSessionWorkspacePanelSource.indexOf("<ChatConversationComposerBridge"),
    );
    expect(routeSource).toContain("return 750");
    expect(routeSource).toContain("return 2_000");
    expect(routeSource).toContain("return 4_000");
    expect(chatSessionDetailMutationsSource).toContain("onMutate: async (variables) =>");
    expect(routeStylesModuleSource).not.toContain("toolApprovalOverlay:");
    expect(routeStylesModuleSource).not.toContain("toolApprovalDialog:");
    expect(chatToolApprovalDialogSource).toContain("role=\"dialog\"");
    expect(chatToolApprovalDialogSource).toContain("toolApprovalCodexTitle");
    expect(chatToolApprovalDialogSource).toContain("Allow this action?");
    expect(chatToolApprovalDialogSource).toContain("允许执行？");
    expect(chatToolApprovalDialogSource).toContain("aria-labelledby={titleId}");
    expect(chatToolApprovalDialogSource).toContain("aria-describedby={descriptionIds}");
    expect(chatToolApprovalDialogSource).toContain("aria-busy={pending}");
    expect(chatToolApprovalDialogSource).toContain("id={titleId}");
    expect(chatToolApprovalDialogSource).toContain("id={descriptionId}");
    expect(chatToolApprovalDialogSource).toContain("id={scopeId}");
    expect(chatToolApprovalDialogSource).toContain("id={riskId}");
    expect(chatToolApprovalDialogSource).toContain("id={toolListId}");
    expect(chatToolApprovalDialogSource).toContain("role=\"list\"");
    expect(chatToolApprovalDialogSource).toContain("role=\"listitem\"");
    expect(chatToolApprovalDialogSource).toContain("onApproveForSession");
    expect(chatToolApprovalDialogSource).toContain("toolApprovalCodexButtonLabels");
    expect(chatToolApprovalDialogSource).toContain("commandPreview");
    expect(chatToolApprovalDialogSource).toContain("sessionGrantScope");
    expect(chatToolApprovalDialogSource).toContain("Y Yes · A Always · N No");
    expect(chatToolApprovalDialogSource).toContain("Y 是 · A 始终 · N 否");
    expect(chatToolApprovalDialogSource).toContain("className={styles.toolItem}");
    expect(chatToolApprovalDialogSource).toContain("showGrant");
    expect(chatToolApprovalDialogStyles.dialog).toContain("grid-cols-[22px_minmax(0,1fr)_auto]");
    expect(chatToolApprovalDialogStyles.dialog).toContain("max-w-[min(44rem,100%)]");
    expect(chatToolApprovalDialogStyles.dialog).toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(chatToolApprovalDialogStyles.actions).toContain("flex");
    expect(chatToolApprovalDialogStyles.commandPreview).toContain("font-mono");
    expect(chatToolApprovalDialogStyles.commandPreview).toContain("[-webkit-line-clamp:2]");
    expect(chatToolApprovalDialogStyles.toolList).toContain("sr-only");
    expect(chatToolApprovalDialogStyles.toolItem).toContain("min-w-0");
  });

  it("marks tool approval resolving state as busy without losing dialog semantics", () => {
    const markup = renderToStaticMarkup(createElement(ChatToolApprovalDialog, {
      lang: "en",
      pending: true,
      rawTitle: "very_long_tool_name_that_should_wrap_inside_the_dialog_surface",
      riskLabel: "Approval required",
      scopeLabel: "current session",
      toolLabels: [
        { id: "long", label: "very_long_tool_name_that_should_wrap_inside_the_dialog_surface" },
      ],
      onApprove: () => undefined,
      onReject: () => undefined,
    }));

    expect(markup).toContain('role="dialog"');
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain("Resolving");
    expect(markup).toContain("Allow this action?");
    expect(markup.match(/disabled=""/g)?.length).toBe(2);
    expect(markup).toContain("very_long_tool_name_that_should_wrap_inside_the_dialog_surface");
  });

  it("renders tool approval dialog labels, descriptions, and tools as accessible relationships", () => {
    const markup = renderToStaticMarkup(createElement(ChatToolApprovalDialog, {
      lang: "zh",
      pending: false,
      rawTitle: "shell_command, read_file",
      riskLabel: "需要审批",
      scopeLabel: "当前会话",
      actionPreview: '$ .\\.venv\\Scripts\\python.exe -c "print(123)"\ncwd: C:\\workspace\\repo',
      sessionGrantScope: { kind: "exact_arguments" },
      toolName: "exec_command",
      toolLabels: [
        { id: "shell", label: "shell_command" },
        { id: "read", label: "read_file" },
      ],
      onApprove: () => undefined,
      onApproveForSession: () => undefined,
      onReject: () => undefined,
    }));

    expect(markup).toContain('role="dialog"');
    // Non-modal by contract: this banner/inline surface has no focus trap, so
    // declaring aria-modal would promise behavior the component does not provide.
    expect(markup).not.toContain('aria-modal="true"');
    expect(markup).toContain("aria-labelledby=");
    expect(markup).toContain("aria-describedby=");
    expect(markup).toContain("允许执行？");
    expect(markup).toContain("是");
    expect(markup).toContain("始终（此 Agent）");
    expect(markup).toContain("否");
    expect(markup).toContain("需要审批");
    expect(markup).toContain("当前会话");
    expect(markup).toContain("python.exe -c");
    expect(markup).toContain("C:\\workspace\\repo");
    expect(markup).toContain("参数完全相同");
    expect(markup).toContain('role="list"');
    expect(markup.match(/role="listitem"/g)?.length).toBe(2);
    expect(markup).toContain("shell_command");
    expect(markup).toContain("read_file");
  });

  it("loads the heavy conversation renderer through a lazy bridge", () => {
    expect(routeSource).toContain("ChatSessionWorkspacePanel");
    expect(routeSource).not.toContain("<ChatConversationComposerBridge");
    expect(chatSessionWorkspacePanelSource).toContain("ChatConversationComposerBridge");
    expect(routeSource).not.toContain("<LazyConversationView");
    expect(chatConversationComposerBridgeSource).toContain("LazyConversationView");
    expect(chatConversationComposerBridgeSource).toContain("composerValue={composer.value}");
    expect(chatConversationComposerBridgeSource).toContain("composerAttachments={composer.attachments}");
    expect(routeAndComposerSource).toContain("conversationConstants");
    expect(chatSessionWorkspacePanelSource).toContain("const conversationLoadingFallback = (");
    expect(chatSessionWorkspacePanelSource).toContain("fallback={conversationLoadingFallback}");
    expect(routeSource).not.toContain("fallback={<div className={styles.emptySurface}>{t(\"loadingSession\")}</div>}");
    expect(routeSource).not.toContain("<div className={styles.emptySurface}>{t(\"loadingSession\")}</div>");
    expect(routeSource).not.toContain('import { COMPOSER_SESSION_REFERENCE_MIME, ConversationView } from "../components/conversation/ConversationView"');
  });

  it("moves composer attachment and active-send display wiring into a route-local bridge", () => {
    expect(routeSource).toContain('from "./ChatConversationComposerBridge"');
    expect(routeSource).toContain("buildConversationComposerBridgeState({");
    expect(routeSource).toContain("const composerDisabled = conversationComposer.disabled");
    expect(routeSource).toContain("<ChatSessionWorkspacePanel");
    expect(routeSource).toContain("conversation={detail ? {");
    expect(routeSource).toContain("composer: companionConversationComposer");
    expect(chatSessionWorkspacePanelSource).toContain("<ChatConversationComposerBridge");
    expect(chatSessionWorkspacePanelSource).toContain("composer={conversation.composer}");
    expect(routeSource).toContain("submitTurnMutation");
    expect(routeSource).toContain("editResubmitMutation");
    expect(routeSource).toContain("stopTurnMutation");
    expect(routeSource).toContain("sessionGuidanceMutation");
    expect(routeAndComposerSource).toContain("submitTurnWithAttachments");
    expect(routeSource).toContain("useChatComposerTurnMutations");
    expect(routeSource).toContain("useChatComposerSubmitActions");
    expect(routeSource).not.toContain("composerActionDisabled={composerActionDisabled}");
    expect(routeSource).not.toContain("composerActionMode={composerStopMode ? \"stop\" : \"send\"}");
    expect(routeSource).not.toContain("composerAttachments={activeImageAttachments.map");
    expect(chatConversationComposerBridgeSource).toContain("export function buildConversationComposerBridgeState");
    expect(chatConversationComposerBridgeSource).toContain("export function mapChatComposerImageAttachments");
    expect(chatConversationComposerBridgeSource).toContain("attachmentInputDisabled: disabled || Boolean(input.editTargetMessageId) || input.imageInputUnsupported");
    expect(chatConversationComposerBridgeSource).not.toContain("useMutation");
    expect(chatConversationComposerBridgeSource).not.toContain("useQuery");
    expect(chatConversationComposerBridgeSource).not.toContain("queryClient");
    expect(chatConversationComposerBridgeSource).not.toContain("fetchJson");
    expect(chatConversationComposerBridgeTestSource).toContain("keeps send disabled until text, image attachments, or references exist");
    expect(chatConversationComposerBridgeTestSource).toContain("switches active-send controls into stop mode");
  });

  it("keeps live assistant output in an active turn layer outside committed session messages", () => {
    expect(routeSource).toContain("activeTurnLayersBySession");
    expect(routeSource).toContain("Object.entries(activeTurnLayersBySession).forEach");
    expect(routeSource).toContain("runningSessionIds.add(sessionId)");
    expect(routeSource).toContain("activeStatusSource: paintedActiveTurn?.ledgerSeq ? \"assistant_delta\" : \"optimistic_submit\"");
    expect(routeSource).toContain("activeTurnMessage,");
    expect(routeAndStreamSource).toContain("planAppliedAssistantDeltaDrain");
    expect(chatStreamApplyControllerSource).toContain("mergeAssistantDeltaIntoActiveTurnLayer");
    expect(routeSource).toContain("isActiveTurnSettledByDetail");
    expect(routeSource).not.toContain("mergeLiveAssistantMessagesIntoSessionDetail");
    expect(routeSource).not.toContain("setLiveAssistantMessagesBySession");
  });

  it("clears transient active-turn UI state when a session is removed or stale", () => {
    expect(routeSource).toContain("const clearSessionTransientUiState = useCallback(");
    expect(routeSource).toContain("setActiveTurnLayersBySession((current) =>");
    expect(routeSource).toContain("setActiveTurnLayerForSession(current, normalizedSessionId, undefined)");
    expect(routeSource).toContain("queryClient.cancelQueries({ queryKey: queryKeys.session(normalizedSessionId), exact: true })");
    expect(routeSource).toContain("queryClient.removeQueries({ queryKey: queryKeys.session(normalizedSessionId), exact: true })");

    const deleteCleanupIndex = routeAndLifecycleSource.indexOf("clearSessionTransientUiState(variables.sessionId");
    const deleteRemoveIndex = routeAndLifecycleSource.indexOf("removeSessionWorkspace(variables.sessionId");
    expect(deleteCleanupIndex).toBeGreaterThan(0);
    expect(deleteCleanupIndex).toBeLessThan(deleteRemoveIndex);
  });

  it("disables image attachment affordance when the active Agent image route model cannot read images", () => {
    expect(routeSource).toContain("modelImageInputSupportById");
    expect(routeSource).toContain("imageInputModelIdForAgent(activeSessionAgent, detail?.dialogueModelId)");
    expect(routeSource).toContain("activeAgentImageInputSupported === false");
    expect(routeAndHelpersSource).toContain("const visionModelId = String(agent?.llmBindings?.vision?.modelId ?? \"\").trim()");
    expect(routeSource).toContain("imageInputUnsupported: activeAgentImageInputUnsupported");
    expect(chatConversationComposerBridgeSource).toContain("attachmentInputDisabled: disabled || Boolean(input.editTargetMessageId) || input.imageInputUnsupported");
    expect(routeSource).toContain("clearSessionImageAttachments(current, activeSessionId)");
  });

  it("passes agent avatar context into the conversation timeline", () => {
    expect(routeSource).toContain("assistantAvatarImageUrl: activeAgentAvatarImageUrl");
    expect(routeSource).toContain("assistantAvatarFallback: activeAgentAvatarFallback");
    expect(routeSource).toContain("resolveTurnAvatar: resolveConversationTurnAvatar");
    expect(routeSource).toContain("resolveConversationTurnAvatar");
    expect(routeSource).toContain("agentsByCode");
    expect(conversationStyles.turnAvatarImage).toBeTypeOf("string");
  });

  it("selects direct sessions through the backend active-session endpoint", () => {
    expect(routeSource).toContain("latestDirectSessionSelectionRef");
    expect(routeSource).toContain("selectDirectSessionMutation");
    expect(routeSource).toContain("useChatSessionSelection");
    expect(routeSource).toContain("useChatRouteSelection");
    expect(chatApiSource).toContain("`/api/sessions/${encodeURIComponent(sessionId)}/select`");
    expect(routeAndSelectionSource).toContain("selectChatSession(sessionId)");
    // The committed route is the only select input; clicks delegate to openSession.
    expect(routeAndActionsSource).toContain("chatRoute.openSession(normalizedSessionId, {");
    expect(routeAndSelectionSource).toContain("routeSessionId");
    // Select is generation-guarded and short-debounced so rapid tab thrash collapses to one POST.
    expect(routeAndSelectionSource).toContain("selectDirectSessionMutation.mutate({ sessionId: latestSessionId, generation })");
    expect(routeAndSelectionSource).toContain("setTimeout");
    expect(routeAndSelectionSource).toContain("80");
    expect(routeSource).toContain("shouldShowStickyTranscriptPending");
    expect(routeSource).toContain("resolveStickySessionDetailPaint");
    expect(routeSource).toContain("transcriptPending: sessionTranscriptPending");
    expect(routeSource).not.toContain("isForeignSessionDetailQueryKey(query.queryKey, activeId)");
    expect(routeAndSelectionSource).toContain("syncSessionDetail(nextDetail)");
    expect(routeAndSelectionSource).toContain("chatWorkspaceCache.afterSessionSelected()");
    expect(routeAndSelectionSource).not.toContain("afterSessionChanged({\n        sessionId: nextDetail.id");
    // Late /select responses must never chase a newer pointer back.
    expect(routeAndSelectionSource).toContain("// Late response for a session the user already left: cache only, never navigate.");
  });

  it("derives responsive layout from the workbench ResizeObserver without overwriting pane preferences", () => {
    expect(routeAndLayoutSource).toContain("resolveChatResponsiveLayout");
    expect(routeAndLayoutSource).toContain("new ResizeObserver(syncResponsiveLayout)");
    expect(routeAndLayoutSource).toContain("data-chat-responsive-mode={responsiveMode}");
    expect(routeAndLayoutSource).toContain("responsiveMode={responsiveLayout.mode}");
    expect(routeAndLayoutSource).not.toContain("CHAT_COMPACT_DESKTOP_MEDIA_QUERY");
    expect(routeAndLayoutSource).not.toContain("compactDesktopAutoCollapseRef");
    expect(routeAndLayoutSource).toContain(
      "const [rightPaneCollapsed, setRightPaneCollapsed] = useState(false)",
    );
    expect(routeAndLayoutSource).toContain("styles.layoutCompactDesktop");
    expect(routeAndLayoutSource).toContain("styles.layoutOverlay");
    expect(routeSource).toContain("useChatWorkbenchLayout");
    expect(routeSource).toContain("ChatSessionWorkbenchShell");
  });

  it("keeps Chat workbench as hook composition plus ChatSessionWorkbenchShell slots", () => {
    expect(routeSource).toContain("useChatGroupDraftState");
    expect(routeSource).toContain("useSyncChatGroupManageDrafts");
    expect(routeSource).toContain("useChatWorkbenchContextMenus");
    expect(routeSource).toContain("useChatConversationIndexChrome");
    expect(routeSource).toContain("deriveChatGroupRoundState");
    expect(routeSource).toContain("buildChatGroupRoomActionDisabledFlags");
    expect(chatCodingRouteWorkbenchSource).not.toContain('from "./ChatConversationIndexPanel"');
    expect(chatCodingRouteWorkbenchSource).toContain("lazy(() =>");
    expect(chatCodingRouteWorkbenchSource).toContain('import("./ChatStatusRail")');
    expect(chatCodingRouteWorkbenchSource).toContain('import("./CliAgentRunTerminalPanel")');
    expect(chatSessionWorkbenchShellSource).toContain("WORKBENCH_LAYOUT_IDS.chat");
    expect(chatSessionWorkbenchShellSource).toContain("VSessionWorkbenchPage");
  });

  it("places shared collapse-resize handles on the chat gutters", () => {
    expect(routeStyles.layout.split(/\s+/)).toContain("grid");
    expect(routeStyles.layout).toContain("!gap-0");
    expect(routeStyles.layout).toContain("!p-0");
    expect(routeStyles.layout).toContain("w-full");
    expect(routeStyles.layout).toContain("[--chat-pane-gutter:0px]");
    expect(routeStyles.layout).toContain(
      "grid-cols-[var(--chat-left-pane-width,300px)_var(--chat-pane-gutter)_minmax(0,1fr)_var(--chat-pane-gutter)_var(--chat-right-pane-width,240px)]",
    );
    expect(routeStyles.layoutCompactDesktop).toContain(
      "grid-cols-[minmax(220px,var(--chat-left-pane-width,248px))_var(--chat-pane-gutter)_minmax(0,1fr)]",
    );
    expect(routeStyles.layoutOverlay).toContain("grid-cols-[minmax(0,1fr)]");
    expect(routeStyles.overlayPane).toContain("fixed");
    expect(routeStyles.overlayPane).toContain("w-[min(86vw,320px)]");
    expect(routeStyles.overlayBackdrop).toContain("fixed");
    expect(routeStyles.layout).not.toContain("_0px_minmax(0,1fr)_0px_");
    expect(routeStyles.layoutCompactDesktop).not.toContain("minmax(420px");
    expect(routeStyles.layoutCompactDesktop).not.toContain("minmax(260px");
    expect(routeStyles.layout).not.toContain("_8px_");
    expect(routeStyles.layoutCompactDesktop).not.toContain("_8px_");
    // Placement only — shared visual/keyboard contract lives on PaneCollapseHandle.
    expect(routeStyles.resizeHandleLeft).toContain("h-full");
    expect(routeStyles.resizeHandleLeft).toContain("w-full");
    expect(routeStyles.resizeHandleLeft).toContain("[grid-column:2]");
    expect(routeStyles.resizeHandleRight).toContain("[grid-column:4]");
    expect(routeSource).toContain("PaneCollapseHandle");
    expect(routeSource).toContain("valueNow={leftPanelWidth}");
    expect(routeSource).toContain("valueNow={rightPanelWidth}");
    expect(routeSource).toContain("MIN_LEFT_PANEL_WIDTH");
    expect(routeSource).toContain("MIN_RIGHT_PANEL_WIDTH");
  });

  it("fills the conversation reading track whenever the optional status rail is closed", () => {
    expect(chatSessionWorkbenchShellSource).toContain(
      'data-chat-status-rail={statusRailCollapsed ? "collapsed" : "visible"}',
    );
    expect(routeSource).toContain("statusRailCollapsed={statusRailCollapsed}");
    expect(routeSource).toContain("conversationFocused={statusRailCollapsed}");
    expect(chatSessionWorkspacePanelSource).toContain("conversationFocused");
    expect(chatSessionWorkspacePanelSource).toContain("styles.conversationFrameFocus");
    expect(chatSessionWorkspacePanelStyles.conversationFrameFocus).toBeTypeOf("string");
    expect(chatSessionWorkspacePanelStyles.conversationFrameFocus).toContain("w-full");
    expect(chatSessionWorkspacePanelStyles.conversationFrameFocus).toContain("max-w-full");
    expect(chatSessionWorkspacePanelStyles.conversationFrameFocus).not.toContain("justify-self-center");
  });

  it("reclaims the status rail grid track when closed without leaving implicit columns", () => {
    expect(routeAndLayoutSource).toContain("reclaimStatusRailTrack");
    expect(routeAndLayoutSource).toContain("styles.layoutStatusRailCollapsed");
    expect(routeAndLayoutSource).toContain(
      "const statusRailDocked = responsiveLayout.rightVisible && !rightPaneCollapsed",
    );
    expect(routeAndLayoutSource).toContain(
      "const statusRailCollapsed = !statusRailDocked && !statusRailOverlayOpen",
    );
    // Collapsed docked rail must not keep grid-column:5 (creates blank right track).
    expect(routeAndLayoutSource).toContain("? styles.paneCollapsed");
    expect(routeAndLayoutSource).toContain(": styles.leftRail");
    expect(routeSource).toContain("className={chatLayoutClassName}");
    expect(routeStyles.layoutStatusRailCollapsed).toContain("!grid-cols-[var(--chat-left-pane-width,300px)_var(--chat-pane-gutter)_minmax(0,1fr)]");
    expect(routeStyles.leftRail).toContain("flex");
    expect(routeStyles.leftRail).not.toContain("!flex");
    expect(routeStyles.leftRail).toContain("[grid-column:5]");
  });

  it("defaults Chat to a wider left conversation column and narrower right status rail", () => {
    expect(shellStoreSource).toContain("leftPanelWidth: 300");
    expect(shellStoreSource).toContain("rightPanelWidth: 220");
    expect(shellStoreSource).toContain("normalizePersistedChatPanelWidths");
    expect(shellStoreSource).toContain("merge: (persistedState, currentState)");
    expect(routeAndLayoutSource).toContain('"--chat-left-pane-width": conversationIndexCollapsed ? "0px" : `${leftPanelWidth}px`');
    expect(routeAndLayoutSource).toContain('"--chat-right-pane-width": statusRailDocked ? `${rightPanelWidth}px` : "0px"');
    expect(routeStyles.leftRail).toContain("flex");
    expect(routeStyles.leftRail).toContain("flex-col");
    expect(routeStyles.leftRail).toContain("p-1");
    expect(routeStyles.leftBlock).toContain("shrink-0");
    expect(routeStyles.leftBlock).toContain("gap-1.5");
    expect(routeStyles.leftBlock).toContain("p-2");
    expect(routeStyles.leftBlock).not.toContain("gap-[2px]");
    expect(routeStyles.leftBlock).not.toContain("p-[2px]");
    expect(routeStyles.companionBlock).not.toContain("!flex-1");
    expect(routeStyles.companionBlock).toContain("content-start");
    expect(routeStyles.companionBlock).not.toContain("max-h-[min(420px,70dvh)]");
    expect(routeStyles.companionBlock).toContain("overflow-visible");
    expect(routeStyles.rightPane).toContain("grid");
    expect(routeStyles.rightPane).toContain("gap-[var(--chat-workbench-gap)]");
    expect(routeStyles.rightPane).toContain("p-[var(--chat-workbench-gap)]");
    expect(routeAndLayoutSource).toContain("styles.rightPaneWithTabs");
    expect(routeAndLayoutSource).toContain("styles.rightPaneWithoutTabs");
    expect(routeCssSource).not.toContain(".sessionAgentStatusControl");
  });

  it("places the conversation index on the left and the status rail on the right", () => {
    const statusAsideMount = routeSource.indexOf("<ChatStatusRail");
    const centerPaneStart = routeSource.indexOf("<ChatWorkbenchCenterColumn");
    const conversationAsideMount = routeSource.indexOf("<ChatConversationIndexRail");
    const statusAsideStart = chatStatusRailSource.indexOf('id="chat-status-pane"');
    const conversationAsideStart = conversationIndexRailSource.indexOf('id="chat-conversation-index-pane"');
    const shellStatusSlot = chatSessionWorkbenchShellSource.indexOf("statusRail={statusRail}");
    const shellSessionSlot = chatSessionWorkbenchShellSource.indexOf("session={center}");
    const shellIndexSlot = chatSessionWorkbenchShellSource.indexOf("indexRail={conversationIndex}");

    expect(statusAsideMount).toBeGreaterThan(-1);
    expect(centerPaneStart).toBeGreaterThan(statusAsideMount);
    expect(conversationAsideMount).toBeGreaterThan(centerPaneStart);
    expect(statusAsideStart).toBeGreaterThan(-1);
    expect(conversationAsideStart).toBeGreaterThan(-1);
    expect(shellStatusSlot).toBeGreaterThan(-1);
    expect(shellSessionSlot).toBeGreaterThan(shellStatusSlot);
    expect(shellIndexSlot).toBeGreaterThan(shellSessionSlot);
    expect(routeStyles.rightPane).toContain("[grid-column:1]");
    expect(routeStyles.rightPane).toContain("[grid-row:1]");
    expect(routeStyles.resizeHandleLeft).toContain("[grid-column:2]");
    expect(routeStyles.resizeHandleLeft).toContain("[grid-row:1]");
    expect(routeStyles.centerPane).toContain("[grid-column:3]");
    expect(routeStyles.centerPane).toContain("[grid-row:1]");
    expect(routeStyles.resizeHandleRight).toContain("[grid-column:4]");
    expect(routeStyles.resizeHandleRight).toContain("[grid-row:1]");
    expect(routeStyles.leftRail).toContain("[grid-column:5]");
    expect(routeStyles.leftRail).toContain("[grid-row:1]");
    expect(routeAndLayoutSource).toContain("const conversationIndexCollapsed = responsiveLayout.leftVisible");
    expect(routeAndLayoutSource).toContain("const statusRailDocked = responsiveLayout.rightVisible");
    expect(routeAndLayoutSource).toContain("const statusRailCollapsed = !statusRailDocked");
    expect(conversationIndexRailSource.indexOf("{conversationIndexPanel}")).toBeGreaterThan(-1);
    expect(conversationIndexRailSource.indexOf("styles.systemEntryGroup")).toBeGreaterThan(
      conversationIndexRailSource.indexOf('id="chat-conversation-index-pane"'),
    );
    const currentSessionIndex = chatStatusRailSource.indexOf("styles.currentSessionBlock");
    const activeSkillIndex = chatStatusRailSource.indexOf("styles.activeSkillStatus");
    const promptInspectorIndex = chatStatusRailSource.indexOf("<ChatPromptAssemblyInspector");
    const payloadTraceIndex = chatStatusRailSource.indexOf("<LlmPayloadTracePanel");
    const companionIndex = chatStatusRailSource.indexOf("styles.companionBlock");
    expect(currentSessionIndex).toBeGreaterThan(-1);
    expect(activeSkillIndex).toBeGreaterThan(currentSessionIndex);
    expect(promptInspectorIndex).toBeGreaterThan(activeSkillIndex);
    expect(payloadTraceIndex).toBeGreaterThan(promptInspectorIndex);
    expect(companionIndex).toBeGreaterThan(payloadTraceIndex);
    expect(chatStatusRailSource).not.toContain("TokenCoreStatusPanel");
  });

  it("uses shared readable scale tokens instead of page-local micro typography", () => {
    const chatSurfaceCss = [
      appShellCssSource,
      routeCssSource,
      conversationCssSource,
      routerSource,
      routeErrorBoundarySource,
    ].join("\n");

    expect(chatSurfaceCss).toContain("var(--vui-font-xs)");
    expect(chatSurfaceCss).toContain("var(--vui-font-sm)");
    expect(chatSurfaceCss).toContain("var(--vui-font-md)");
    expect(conversationCssSource).toContain("var(--vui-font-chat)");
    expect(chatSurfaceCss).not.toMatch(/font-size:\s*0\.(?:6\d|7[0-7])rem/);
  });

  it("uses the unified Agent session tab strip for multi-session or CLI states", () => {
    expect(routeSource).toContain("selectedChatAgentId || agentSessionTabs.length > 0 || cliAgentRunTabs.length > 0");
    expect(routeSource).not.toContain("agentSessionTabs.length > 1 || cliAgentRunTabs.length > 0");
    expect(agentSessionTabStripSource).not.toContain("cliAgentRuns.length === 0 && sessions.length === 0");
    expect(agentSessionTabStripSource).not.toContain("sessions.length <= 1");

    expect(routeStyles.agentSessionTabGroup).toBeTypeOf("string");
    expect(routeStyles.agentSessionTab).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabRoot).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabChild).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabActive).toBeTypeOf("string");
  });

  it("renders Agent sessions as a compact browser-like navigation rail", () => {
    expect(routeStyles.tabStrip).toContain("overflow-hidden");
    expect(routeStyles.tabStrip).toContain("border-b");
    // Shell row is vertically centered; session scroller keeps items-end for tab feet.
    expect(routeStyles.tabStrip).toContain("items-center");
    expect(routeStyles.tabStripSessions).toContain("items-end");
    expect(agentSessionTabStripStyles.agentSessionTabRail).toContain("w-fit");
    expect(agentSessionTabStripStyles.agentSessionTabRail).toContain("max-w-full");
    expect(agentSessionTabStripStyles.agentSessionTabGroup).toContain("flex-nowrap");
    expect(agentSessionTabStripStyles.agentSessionTabRail).toContain("overflow-x-auto");
    expect(agentSessionTabStripStyles.agentSessionTab).toContain("shrink-0");
    expect(agentSessionTabStripStyles.agentSessionTab).toContain("rounded-t-[var(--radius-control)]");
    expect(agentSessionTabStripStyles.agentSessionTabMainActionActive).toContain("!shadow-none");
    // Selection chrome is on the outer card so the close control stays inside the same surface.
    expect(agentSessionTabStripStyles.agentSessionTabActive).toContain("border-[color-mix");
    expect(agentSessionTabStripStyles.agentSessionTabActive).toContain("bg-[color-mix");
    expect(agentSessionTabStripStyles.agentSessionTabActive).toContain("data-[selected=true]:!bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-panel))]");
    expect(agentSessionTabStripStyles.agentSessionTabCloseButton).toContain("h-6");
    expect(agentSessionTabStripStyles.agentSessionTabCreateButton).toContain("shrink-0");
    expect(agentSessionTabStripStyles.agentSessionTabRail).toContain("flex-[0_1_auto]");
    expect(agentSessionTabStripStyles.agentSessionTabStatusDotRunning).toContain("state-success");
    expect(agentSessionTabStripStyles.agentSessionTabStatusDotError).toContain("state-error");
    expect(agentSessionTabStripStyles.agentSessionTabStatusDotApproval).toContain("state-warning");
    expect(agentSessionTabStripStyles.agentSessionTab).not.toContain("opacity-[0.72]");
    expect(agentSessionTabStripStyles.agentSessionTabTitle).toContain("truncate");
  });

  it("routes chat session navigation controls through VUI primitives", () => {
    const sessionControlSources = [
      agentSessionTabStripSource,
      sessionContextMenuSource,
      directSessionIndexItemSource,
      groupSessionIndexItemsSource,
      conversationIndexSectionSource,
    ];

    for (const source of sessionControlSources) {
      expect(source).toContain("from \"../components/vui\"");
      expect(source).not.toMatch(/<button\b/);
    }

    expect(agentSessionTabStripSource).toContain("<VButton");
    expect(agentSessionTabStripSource).toContain("<VIconButton");
    expect(sessionContextMenuSource).toContain("<VDropdownMenu");
    expect(directSessionIndexItemSource).toContain("<VNativeButton");
    expect(directSessionIndexItemSource).toContain("<VIconButton");
    expect(groupSessionIndexItemsSource).toContain("<VNativeButton");
    expect(conversationIndexSectionSource).toContain("<VNativeButton");
    // Menu items are Radix DropdownMenu items (domain class hooks, not VButton grids).
    expect(routeStyles.sessionContextMenuItem).toContain("sessionContextMenuItem");
  });

  it("shows a safe return link when Chat is opened from another workspace surface", () => {
    expect(routeAndPresentationSource).toContain(
      "safeAgentCenterReturnToPath(new URLSearchParams(locationSearch).get(\"returnTo\"))",
    );
    expect(routeAndPresentationSource).toContain("new URLSearchParams(locationSearch).get(\"returnLabel\")");
    expect(routeSource).toContain("useChatReturnNavigation(location.search, lang)");
    expect(routeAndPresentationSource).toContain("返回来源");
    expect(routeAndCenterPackSource).toContain("styles.chatReturnLink");
    expect(routeAndCenterPackSource).toContain("styles.tabStripSessions");
    expect(routeAndCenterPackSource).toContain("to={chatReturnTarget}");
    expect(routeAndCenterPackSource).toContain("title={chatReturnLabel}");
    expect(routeAndCenterPackSource).toContain("aria-label={chatReturnLabel}");
    // Visible text stays short; full destination is only in title/aria.
    expect(routeAndCenterPackSource).toContain('{lang === "zh" ? "返回" : "Back"}');
    expect(routeAndCenterPackSource).toContain("styles.chatReturnLinkIcon");
    expect(routeStyles.chatReturnLink).toBeTypeOf("string");
    expect(routeStyles.chatReturnLink).toContain("shrink-0");
    expect(routeStyles.chatReturnLink).toContain("max-w-[7.5rem]");
    expect(routeStyles.chatReturnLink).toContain("[&_span]:truncate");
    expect(routeStyles.tabStripSessions).toContain("flex-1");
    expect(routeStyles.tabStripSessions).toContain("overflow-x-auto");
  });

  it("keeps the conversation index compact enough for 1024px workbench use", () => {
    expect(routeStyles.layout).toContain("minmax(0,1fr)");
    expect(routeStyles.layout).not.toContain("minmax(192px,var(--chat-left-pane-width,220px))");
    expect(routeStyles.layout).not.toContain("minmax(244px,var(--chat-right-pane-width,284px))");
    expect(routeStyles.layoutCompactDesktop).toContain("minmax(0,1fr)");
    expect(routeStyles.layoutCompactDesktop).not.toContain("minmax(420px");
    expect(routeStyles.conversationTitleRow).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(routeStyles.conversationTitleRow).toContain("max-w-full");
    expect(conversationStyles.surfaceCompact).not.toContain("[&_.timeline]:px-3");
    expect(conversationStyles.surfaceCompact).toContain("[&_.timeline]:pt-[9px]");
    expect(conversationStyles.surfaceCompact).toContain("[&_.timeline]:pb-[11px]");
    expect(conversationStyles.surfaceCompact).toContain("[&_.composer]:gap-[7px]");
  });

  it("keeps the embedded composer compact inside the workbench frame", () => {
    expect(conversationStyles.composer).toContain("items-center");
    expect(conversationStyles.composer).not.toContain("items-end");
    expect(conversationStyles.composerField).toContain("[&_textarea]:min-h-[72px]");
    expect(conversationStyles.composerField).toContain("[&_textarea]:max-h-[220px]");
    expect(conversationStyles.composerField).not.toContain("[&_textarea]:min-h-20");
    expect(conversationStyles.surfaceCompact).toContain("[&_.composer]:pt-1.5");
    expect(conversationStyles.surfaceCompact).toContain("[&_.composer]:pb-2");
    expect(conversationStyles.surfaceCompact).not.toContain("[&_.composer]:py-4");
    expect(conversationStyles.sendButton).toContain("h-[var(--vui-control-height-sm)]");
    expect(conversationStyles.sendButton).toContain("w-[var(--vui-control-height-sm)]");
    expect(conversationStyles.attachButton).toContain("h-[var(--vui-control-height-sm)]");
    expect(conversationStyles.attachButton).toContain("w-[var(--vui-control-height-sm)]");
  });

  it("does not ship micro typography in the chat workbench surface", () => {
    expect(routeCssSource).not.toMatch(/font-size:\s*0\.(?:6\d|7[0-7])rem/);
    expect(routeStyles.agentModelTag).toBeTypeOf("string");
    expect(routeStyles.agentModelTag).toContain("[font-size:var(--vui-font-xs)]");
  });

  it("uses overlay drawers instead of fixed compatibility floors below 960px", () => {
    expect(routeStyles.layout).toContain("minmax(0,1fr)");
    expect(routeStyles.layout).not.toContain("minmax(192px,var(--chat-left-pane-width,220px))");
    expect(routeStyles.layout).not.toContain("minmax(244px,var(--chat-right-pane-width,284px))");
    expect(routeStyles.layoutCompactDesktop).toContain("minmax(220px,var(--chat-left-pane-width,248px))");
    expect(routeStyles.layoutCompactDesktop).not.toContain("minmax(260px");
    expect(routeStyles.layoutCompactDesktop).not.toContain("minmax(420px");
    expect(routeStyles.layoutOverlay).toContain("grid-cols-[minmax(0,1fr)]");
    expect(routeAndCenterPackSource).toContain('aria-controls="chat-conversation-index-pane"');
    expect(routeAndCenterPackSource).toContain('aria-controls="chat-status-pane"');
    expect(routeAndLayoutSource).toContain('event.key !== "Escape"');
    expect(routeAndLayoutSource).toContain("closeResponsiveOverlayPane");
    expect(routeStyles.paneCollapsed).toContain("!overflow-hidden");
    expect(routeStyles.paneCollapsed).toContain("invisible");
    expect(routeStyles.paneCollapsed).toContain("!hidden");
  });

  it("keeps actions in the composer plus menu and the status rail read-only", () => {
    expect(routeSource).toContain('import { ChatComposerPlusMenu } from "./ChatComposerPlusMenu"');
    expect(routeSource).toContain("composerLeadingControl: verifiedCompanionMode ? undefined : (");
    expect(routeSource).toContain("<ChatComposerPlusMenu");
    expect(chatComposerPlusMenuSource).toContain('label: lang === "zh" ? "添加与引用" : "Add and reference"');
    expect(chatComposerPlusMenuSource).toContain('label: lang === "zh" ? "对话能力" : "Conversation capabilities"');
    expect(chatComposerPlusMenuSource).toContain('label: lang === "zh" ? "会话与陪伴" : "Session and companion"');
    expect(chatComposerPlusMenuSource).toContain('label: lang === "zh" ? "群聊与团队" : "Group and team"');
    expect(chatComposerPlusMenuSource).not.toContain("CHAT_FEATURE_PRESETS.map");
    expect(chatComposerPlusMenuSource).not.toMatch(/label:\s*["']\//);
    expect(chatStatusRailSource).not.toContain("TokenCoreStatusPanel");
    expect(chatStatusRailSource).not.toContain("mentalModelEnabledForNextTurn");
    expect(chatStatusRailSource).not.toContain("onOpenDirectSession");
    expect(chatStatusRailSource).toContain("styles.companionBlock");
    expect(chatStatusRailSource).toContain("styles.companionCompact");
    expect(chatStatusRailSource).toContain("styles.petMiniAvatar");
    expect(routeStyles.companionBlock).toBeTypeOf("string");
    expect(routeStyles.companionCompact).toBeTypeOf("string");
    expect(routeStyles.petMiniAvatar).toBeTypeOf("string");
  });

  it("keeps the companion details toggle as a single compact control", () => {
    expect(routeAndIndexRailSource).toContain("<details className={styles.compactDetails}>");
    expect(routeAndIndexRailSource).toContain("<ChevronRight size={14} aria-hidden=\"true\" />");
    expect(routeStyles.compactDetails).toContain("[&>summary]:list-none");
    expect(routeStyles.compactDetails).toContain("[&>summary::-webkit-details-marker]:hidden");
    expect(routeStyles.compactDetails).toContain("[&_.compactDetailsOpenLabel]:hidden");
    expect(routeStyles.compactDetails).toContain("[&[open]_.compactDetailsOpenLabel]:inline");
    expect(routeStyles.compactDetails).toContain("[&[open]_.compactDetailsClosedLabel]:hidden");
    expect(routeStyles.compactDetailsClosedLabel).toContain("compactDetailsClosedLabel");
    expect(routeStyles.compactDetailsOpenLabel).toContain("compactDetailsOpenLabel");
  });

  it("keeps the left rail status stack soft and non-nested", () => {
    expect(routeStyles.leftRail).toContain("rounded-none");
    expect(routeStyles.leftRail).toContain("border-l");
    expect(routeStyles.leftRail).toMatch(/bg-vui-surface-rail|bg-\[var\(--vui-surface-rail\)\]/);
    expect(routeStyles.leftRail).toContain("shadow-none");
    // Sections separate by whitespace rhythm; hairline rules are removed.
    expect(routeStyles.leftBlock).not.toContain("border-b");
    expect(routeStyles.leftBlock).toContain("border-0");
    expect(routeStyles.leftBlock).toContain("bg-transparent");
    expect(routeStyles.leftBlock).toContain("shadow-none");
    expect(routeStyles.leftBlock).not.toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.leftBlock).not.toContain("!bg-[var(--vui-surface-rail)]");
    expect(routeStyles.blockEyebrow).toContain("[font-size:var(--vui-font-xs)]");
    expect(routeStyles.blockEyebrow).toContain("font-semibold");

    expect(routeStyles.tokenCompressionCard).toBe("vui-routes-chatcodingroute tokenCompressionCard min-w-0");
    expect(routeStyles.tokenCompressionCard).not.toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.tokenCompressionCard).not.toMatch(/border border-vui-border-subtle|border border-\[var\(--vui-border-subtle\)\]/);
    expect(routeStyles.tokenCompressionCard).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(routeStyles.tokenCompressionCard).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(routeStyles.tokenCompressionCard).not.toContain("p-2");

    expect(routeStyles.contextLineCompact).toMatch(/bg-vui-surface-row|bg-\[var\(--vui-surface-row\)\]/);
    expect(routeStyles.contextLineCompact).not.toContain("white)");
    expect(routeStyles.contextLineCompact).toContain("px-1.5");
    expect(routeStyles.contextLineCompact).toContain("shadow-none");
    expect(routeStyles.contextLineCompact).not.toContain("p-2");
    expect(routeStyles.oneLineValue).toMatch(/!bg-vui-surface-row|!bg-\[var\(--vui-surface-row\)\]/);
    expect(routeStyles.oneLineValue).not.toContain("p-2");

    expect(routeStyles.companionBlock).not.toContain("!flex-1");
    expect(routeStyles.companionBlock).toContain("content-start");
    expect(routeStyles.companionBlock).not.toContain("max-h-[min(420px,70dvh)]");
    expect(routeStyles.companionCompact).toContain("grid-cols-[32px_minmax(0,1fr)]");
    expect(routeStyles.companionCompact).toContain("bg-[var(--vui-surface-raised)]");
    expect(routeStyles.companionCompact).not.toContain("white)");
    expect(routeStyles.companionCompact).toContain("shadow-none");
    expect(routeStyles.companionCopy).toContain("[font-size:var(--vui-font-xs)]");
    expect(routeStyles.petShowcaseFeedback).toContain("[font-size:var(--vui-font-sm)]");
    expect(routeStyles.companionTopLine).not.toMatch(/bg-vui-surface-row|bg-\[var\(--vui-surface-row\)\]/);
    // Wave 6H: max-h lives on open body height shell, not the outer <details>.
    expect(routeStyles.compactDetails).not.toContain("max-h-[220px]");
    expect(routeStyles.compactDetailsBody).toContain("overflow-auto");
    expect(chatStatusRailSource).toContain("CHAT_COMPACT_DETAILS_HEIGHT_PANE");
    expect(chatStatusRailSource).toContain("PersistedHeightListShell");
    expect(routeStyles.inlineMetaPill).toContain("min-h-7");
    expect(routeStyles.petShowcaseAction).toContain("min-h-8");
    expect(routeStyles.petShowcaseAction).toContain("text-xs");
  });

  it("accents the running rail block and collapses empty rail panels", () => {
    // Busy session/group blocks get the inset accent bar; idle blocks stay neutral.
    expect(chatStatusRailSource).toContain("isBusyPhase(sessionStateValue)");
    expect(chatStatusRailSource).toContain("styles.railBlockActive");
    expect(chatStatusRailSource).toContain("groupRoundRunning ? ` ${styles.railBlockActive}`");
    expect(routeStyles.railBlockActive).toContain("inset_2px_0_0_var(--accent-cool)");
    expect(routeStyles.currentSessionBlock).not.toContain("accent-cool");
    // Empty states fold to one line instead of rendering hollow detail chrome.
    expect(chatStatusRailSource).toContain("{pet ? (");
    expect(tokenCoreStatusPanelSource).toContain("hasMetricData");
    expect(tokenCoreStatusPanelSource).toContain("--token-status-bar-fill");
    expect(tokenCoreStatusPanelSource).toContain("styles.tokenStatusEmpty");
    expect(routeStyles.tokenStatusEmpty).toContain("text-[var(--fg-tertiary)]");
  });

  it("compresses repeated status prose while keeping critical guidance visible", () => {
    expect(tokenCoreStatusPanelSource).toContain("VTooltip");
    expect(tokenCoreStatusPanelSource).not.toContain('<p className={styles.blockEyebrow}>Token</p>');
    expect(llmPayloadTracePanelSource).toContain("VTooltip");
    expect(llmPayloadTracePanelSource).toContain("renderTrigger");
    expect(llmPayloadTracePanelSource).toContain("aria-label={subtitle}");
    expect(llmPayloadTracePanelSource).not.toContain("<span className={styles.llmPayloadTraceHelp} tabIndex={0}");
    expect(llmPayloadTracePanelSource).not.toContain('<p className={styles.blockEyebrow}>LLM</p>');
    expect(routeSource).not.toContain('<p className={styles.blockEyebrow}>{lang === "zh" ? "模式控制" : "Mode controls"}</p>');
    expect(routeSource).not.toContain('<p className={styles.sectionMetaLine}>{mentalCompactLine || mentalSourceLabel}</p>');
    expect(chatStatusRailSource).not.toContain("mentalCompactLine");
    expect(chatStatusRailSource).not.toContain("mentalStateLabel");
    expect(chatStatusRailSource).toContain("VContextualHint");
    expect(chatStatusRailSource).toContain("管理操作已移至输入框下方的加号菜单");
    expect(chatComposerPlusMenuSource).toContain('hint: lang === "zh" ? "下轮生效" : "Applies next turn"');
    expect(chatComposerPlusMenuSource).toContain('hint: lang === "zh" ? "把预算与进度注入上下文"');
    expect(routeAndGroupCenterSource).toContain("styles.groupConversationTitleRow");
    expect(routeAndGroupCenterSource).toContain("暂无通知。");
    expect(routeSource).not.toContain("className={styles.featurePresetNote}");
    expect(chatStatusRailSource).toContain("sessionBindingNotice");
  });

  it("keeps compact VButton cards and plus-menu rows from collapsing their internal layout", () => {
    expect(tokenCoreStatusPanelSource).toContain("tokenMetricShortLabel(metric, lang)");
    expect(tokenCoreStatusPanelSource).toContain("<div key={metric.key} className={metricClassName}");
    expect(routeStyles.tokenStatusMetric).toContain("place-items-stretch");
    expect(routeStyles.tokenStatusMetric).toContain("min-h-[64px]");
    expect(routeStyles.tokenStatusMetric).not.toContain("min-h-[96px]");
    expect(routeStyles.tokenStatusMetric).toContain("bg-[var(--vui-surface-raised)]");
    expect(routeStyles.tokenStatusMetric).not.toContain("white)");
    expect(routeStyles.tokenStatusMetric).toContain("shadow-none");
    expect(routeStyles.tokenStatusMetric).toContain("!grid");
    expect(routeStyles.tokenStatusMetric).toContain("!w-full");
    expect(routeStyles.tokenStatusMetric).toContain("overflow-visible");
    expect(routeStyles.tokenStatusVisualGrid).toContain("!grid");
    expect(routeStyles.tokenStatusVisualGrid).toContain("grid-cols-[repeat(4,minmax(0,1fr))]");
    expect(routeStyles.tokenStatusVisualGrid).toContain("items-stretch");
    expect(routeStyles.tokenStatusVisualGrid).toContain("w-full");
    expect(routeStyles.tokenStatusCopy).toContain("min-w-0");
    expect(routeStyles.tokenStatusCopy).toContain("overflow-visible");
    expect(routeStyles.tokenStatusCopy).toContain("self-center");
    expect(routeStyles.tokenStatusLabel).toContain("whitespace-nowrap");
    expect(routeStyles.tokenStatusLabel).toContain("text-[11px]");
    expect(routeStyles.tokenStatusMeta).toContain("sr-only");
    expect(routeStyles.tokenStatusRing).toContain("size-[28px]");
    expect(routeStyles.tokenStatusRingCore).toContain("text-[10px]");
    expect(routeStyles.tokenStatusRingCore).toContain("max-w-full");
    expect(routeStyles.tokenStatusRingCore).toContain("overflow-hidden");
    expect(routeStyles.tokenStatusRingCore).toContain("text-ellipsis");
    expect(routeStyles.tokenStatusRingCore).toContain("whitespace-nowrap");
    expect(routeStyles.tokenStatusRingCore).toContain("tabular-nums");
    expect(routeStyles.tokenStatusBar).toContain("block h-1 overflow-hidden");
    expect(routeStyles.tokenStatusBar).toContain("[&>span]:bg-[var(--token-status-bar-fill,var(--accent-cool))]");
    expect(routeStyles.tokenStatusMetricButton).toContain("[&_[data-slot=vui-button-content]]:contents");
    expect(routeStyles.tokenStatusMetricButton).toContain("!grid");
    expect(routeStyles.tokenStatusMetricButton).toContain("grid-rows-[28px_minmax(0,1fr)]");
    expect(routeStyles.tokenStatusMetricButton).toContain("!w-full");
    expect(routeStyles.tokenStatusMetricButton).toContain("!justify-self-stretch");
    expect(routeStyles.tokenStatusMetricButton).toContain("!bg-transparent");
    expect(routeStyles.tokenStatusMetricButton).toContain("[&_[data-slot=vui-button-label]]:contents");
    expect(routeStyles.tokenStatusMetric_cache).not.toContain("inline-flex");
    expect(routeStyles.tokenStatusMetric_modelInput).not.toContain("inline-flex");
    expect(routeStyles.tokenStatusMetric_compression).not.toContain("inline-flex");
    expect(routeStyles.tokenStatusMetric_speed).not.toContain("inline-flex");
    expect(routeStyles.featureChipRow).toContain("grid-cols-2");
    expect(routeStyles.featureChip).toContain("min-h-[28px]");
    expect(routeStyles.featureChip).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(routeStyles.featureChip).not.toContain("before:content-['']");
    expect(routeStyles.featureChip).not.toContain("before:h-1.5");
    expect(routeStyles.featureChip).toContain("[&_[data-slot=vui-button-content]]:min-w-0");
    expect(routeStyles.featureChip).toContain("[&_[data-slot=vui-button-content]]:max-w-full");
    expect(routeStyles.featureChip).toContain("[&_[data-slot=vui-button-label]]:grid-cols-[minmax(0,1fr)_auto]");
    expect(routeStyles.featureChipActive).toContain("[&_em]:text-[var(--accent-cool)]");
    expect(routeStyles.featureChipPrimaryActive).toContain("[&_em]:text-[var(--accent-warm-2)]");
    expect(routeStyles.currentSessionLine).toContain("[-webkit-line-clamp:2]");
    expect(routeStyles.currentSessionLine).toContain("[font-size:var(--vui-font-xs)]");
    expect(routeStyles.railSectionHeading).toContain("[font-size:var(--vui-font-xs)]");
    expect(routeStyles.sectionTitle).toContain("[font-size:var(--vui-font-sm)]");
    expect(chatStatusRailSource).toContain('lang === "zh" ? "陪伴" : "Companion"');
    expect(chatStatusRailSource).not.toContain('lang === "zh" ? "心智与运行" : "Mental & runtime"');
    expect(chatComposerPlusMenuSource).toContain('role="menuitemcheckbox"');
    expect(chatComposerPlusMenuSource).toContain("aria-checked={options.checked}");
    expect(chatComposerPlusMenuStyles.menuItem).toContain("!flex");
    expect(chatComposerPlusMenuStyles.itemCopy).toContain("grid");
    expect(chatComposerPlusMenuStyles.itemCopy).toContain("min-w-0");
    expect(chatStatusRailSource).toContain('lang === "zh" ? "明细" : "Details"');
  });

  it("optimistically renders the agent turn while submitted chat content is waiting for backend stream", () => {
    expect(routeAndComposerSource).toContain("createOptimisticActiveTurnLayer");
    expect(routeAndComposerSource).toContain("optimisticTurnIdForSubmission");

    const submitMutationStart = routeAndComposerSource.indexOf("const submitTurnMutation = useMutation");
    const submitMutateStart = routeAndComposerSource.indexOf("onMutate: async (variables)", submitMutationStart);
    const submitSuccessStart = routeAndComposerSource.indexOf("onSuccess: (acceptedTurn, variables, context)", submitMutateStart);
    const submitErrorStart = routeAndComposerSource.indexOf("onError: (error, variables, context)", submitSuccessStart);
    const submitMutateBlock = routeAndComposerSource.slice(submitMutateStart, submitSuccessStart);
    const submitSuccessBlock = routeAndComposerSource.slice(submitSuccessStart, submitErrorStart);
    const submitErrorBlock = routeAndComposerSource.slice(submitErrorStart, routeAndComposerSource.indexOf("const editResubmitMutation", submitErrorStart));

    expect(submitMutateBlock).toContain("setActiveTurnLayersBySession((current) =>");
    expect(submitMutateBlock).toContain("createOptimisticActiveTurnLayer({");
    expect(submitMutateBlock).toContain("sessionId: variables.sessionId");
    expect(submitMutateBlock).toContain("turnId: optimisticTurnIdForSubmission(\"submit\", variables.sessionId, createdAt)");
    expect(submitSuccessBlock).toContain("createOptimisticActiveTurnLayer({");
    expect(submitSuccessBlock).toContain("turnId: acceptedTurn.turnId");
    expect(submitErrorBlock).toContain("setActiveTurnLayerForSession(current, variables.sessionId, undefined)");

    const editMutationStart = routeAndComposerSource.indexOf("const editResubmitMutation = useMutation");
    const editMutateStart = routeAndComposerSource.indexOf("onMutate: async (variables)", editMutationStart);
    const editSuccessStart = routeAndComposerSource.indexOf("onSuccess: (nextDetail, variables, context)", editMutateStart);
    const editErrorStart = routeAndComposerSource.indexOf("onError: (error, variables, context)", editSuccessStart);
    const editMutateBlock = routeAndComposerSource.slice(editMutateStart, editSuccessStart);
    const editSuccessBlock = routeAndComposerSource.slice(editSuccessStart, editErrorStart);
    const editErrorBlock = routeAndComposerSource.slice(editErrorStart, routeAndComposerSource.indexOf("const stopTurnMutation", editErrorStart));

    expect(editMutateBlock).toContain("setActiveTurnLayersBySession((current) =>");
    expect(editMutateBlock).toContain("createOptimisticActiveTurnLayer({");
    expect(editMutateBlock).toContain("turnId: optimisticTurnIdForSubmission(\"edit\", variables.sessionId, createdAt)");
    expect(editMutateBlock).toContain("applyOptimisticEditResubmit");
    expect(editMutateBlock).toContain("previousDetail");
    expect(editSuccessBlock).toContain("const acceptedTurnId = latestUserTurnId(nextDetail)");
    expect(editSuccessBlock).toContain("setActiveTurnLayersBySession((current) =>");
    expect(editSuccessBlock).toContain("turnId: acceptedTurnId");
    expect(editSuccessBlock).toContain("setActiveTurnLayerForSession(current, variables.sessionId, undefined)");
    expect(editErrorBlock).toContain("previousDetail");
    expect(editErrorBlock).toContain("setActiveTurnLayerForSession(current, variables.sessionId, undefined)");
  });

  it("keeps group settings in the right status rail and member status in the left conversation index", () => {
    expect(chatCodingRouteWorkbenchSource).toContain("useChatWorkbenchCatalogQueries");
    expect(chatWorkbenchCatalogQueriesSource).toContain("hasActiveSession: Boolean(activeSessionId)");
    expect(chatCodingRouteWorkbenchSource).toContain("&& allVisibleSessions.length === 0");
    expect(routeSource).toContain("expandedGroupAgentSessionIds");
    expect(routeSource).toContain("useQueries");
    expect(routeSource).toContain("expandedGroupAgentDetailQueries");
    // F2: expanded agent session windows stop polling once group SSE is open.
    expect(routeSource).toContain("groupStreamConnected ? false : 3_000");
    expect(routeSource).toContain("isAvailableGroupParticipant");
    expect(routeSource).toContain("availableGroupParticipants");
    expect(routeSource).toContain("groupParticipantIdentity");
    expect(routeSource).toContain("formatAgentIdentityWithRole");
    expect(routeSource).toContain("rightIndexPanel");
    expect(routeAndActionsSource).toContain("setRightIndexPanel(\"members\")");
    expect(routeSource).toContain("latestMentalSnapshot");
    expect(routeAndIndexRailSource).toContain("styles.groupProfileBlock");
    expect(routeAndIndexRailSource).toContain("styles.rightIndexTabs");
    expect(routeAndIndexRailSource).toContain("<VTabs");
    expect(routeAndIndexRailSource).toContain("styles.agentIndexRoster");
    expect(routeAndIndexRailSource).toContain("styles.agentIndexHeader");
    expect(routeAndIndexRailSource).toContain("styles.agentIndexExpandButton");
    expect(routeAndIndexRailSource).toContain("styles.agentIndexOpenButton");
    expect(routeAndIndexRailSource).toContain("onClick={() => onOpenDirectSession(participant.sessionId)}");
    expect(routeAndIndexRailSource).toContain("avatarImageUrlFrom(participantAgent, participant)");
    expect(routeAndHelpersSource).toContain("styles.agentAvatarImage");
    expect(routeAndIndexRailSource).toContain("styles.agentIndexNameLine");
    expect(routeAndIndexRailSource).toContain("styles.agentIndexEmptyState");
    expect(routeAndIndexRailSource).toContain("aria-expanded={expanded}");
    expect(routeAndIndexRailSource).toContain("只展示可用成员；已归档或断链的历史成员保留在日志里，不在这里打扰。");
    expect(routeAndIndexRailSource).toContain("暂无可用群成员。请在右侧群设置中选择成员并应用变更。");
    expect(routeSource).not.toContain("添加群成员");
    expect(routeSource).not.toContain("Add members");
    expect(routeSource).not.toContain("已从群聊调度中停用");
    expect(routeStyles.leftRail).toContain("[grid-column:5]");
    expect(routeStyles.rightPane).toContain("[grid-column:1]");
    expect(chatStatusRailSource.indexOf("styles.groupProfileBlock")).toBeGreaterThan(-1);
    expect(routeSource.indexOf("<ChatStatusRail")).toBeGreaterThan(-1);
    expect(routeAndIndexRailSource.indexOf("styles.agentIndexRoster")).toBeGreaterThan(-1);
    expect(routeSource.indexOf("<ChatConversationIndexRail")).toBeGreaterThan(
      routeSource.indexOf('id="chat-status-pane"'),
    );

    expect(routeStyles.groupProfileBlock).toBeTypeOf("string");
    expect(routeStyles.rightIndexTabs).toBeTypeOf("string");
    expect(routeStyles.rightIndexTab).toBeTypeOf("string");
    expect(routeStyles.memberIndexSummary).toBeTypeOf("string");
    expect(routeStyles.agentIndexRoster).toBeTypeOf("string");
    expect(routeStyles.agentIndexList).toBeTypeOf("string");
    expect(routeStyles.agentIndexCard).toBeTypeOf("string");
    expect(routeStyles.agentIndexHeader).toBeTypeOf("string");
    expect(routeStyles.agentIndexExpandButton).toBeTypeOf("string");
    expect(routeStyles.agentIndexOpenButton).toBeTypeOf("string");
    expect(routeStyles.agentIndexNameLine).toBeTypeOf("string");
    expect(routeStyles.agentIndexDetails).toBeTypeOf("string");
    expect(routeStyles.agentIndexMentalBlock).toBeTypeOf("string");
    expect(routeStyles.agentIndexEmptyState).toBeTypeOf("string");
  });

  it("hides the right index tab switcher when only the conversation index is available", () => {
    const rightAsideStart = conversationIndexRailSource.indexOf('id="chat-conversation-index-pane"');
    const tabsRenderStart = conversationIndexRailSource.indexOf("{standardGroupRoomActive ? (", rightAsideStart);
    // Radix VTabs owns the tablist; domain geometry stays via listClassName.
    const tabsClassStart = conversationIndexRailSource.indexOf("listClassName={styles.rightIndexTabs}", tabsRenderStart);
    const memberSummaryStart = conversationIndexRailSource.indexOf("{rightIndexPanel === \"members\" && standardGroupRoomActive", tabsClassStart);
    expect(rightAsideStart).toBeGreaterThan(-1);
    expect(tabsRenderStart).toBeGreaterThan(rightAsideStart);
    expect(tabsClassStart).toBeGreaterThan(tabsRenderStart);
    expect(tabsClassStart).toBeLessThan(memberSummaryStart);
    expect(conversationIndexRailSource).toContain("<VTabs");
    expect(conversationIndexRailSource).toContain("triggerClassName={styles.rightIndexTab}");
    expect(routeAndIndexRailSource).not.toContain("rightIndexTabsSingle");
  });

  it("keeps prompt cache observation visible in the current session status strip", () => {
    expect(routeAndTokenStatusSource).toContain("const sessionCacheUsage = detail?.cacheUsage");
    expect(routeAndTokenStatusSource).toContain("sessionCacheUsage?.source === \"provider_usage\"");
    expect(routeAndTokenStatusSource).toContain("sessionCacheUsage?.source === \"not_called\"");
    expect(routeAndTokenStatusSource).toContain("key: \"cache\"");
    expect(routeAndTokenStatusSource).toContain("label: t(\"previousCacheHit\")");
    expect(routeAndTokenStatusSource).toContain("turnCachedInputTokens");
    expect(routeAndTokenStatusSource).toContain("cacheCreationInputTokens");
    expect(routeAndTokenStatusSource).toContain("turnInputTokens");
    expect(routeAndTokenStatusSource).toContain("turnCacheHitRate");
    expect(routeAndTokenStatusSource).toContain("cacheHitNotCalled");
    expect(routeAndTokenStatusSource).toContain("cacheHitMissing");
    expect(routeAndTokenStatusSource).toContain("const tokenStatusCacheTitleLines");
    expect(routeAndTokenStatusSource).toContain("const tokenStatusCacheTitle = tokenStatusCacheTitleLines.join");
    expect(routeAndTokenStatusSource).toContain("titleLines: tokenStatusCacheTitleLines");
    expect(routeAndTokenStatusSource).toContain("llmUsageTitle");
  });

  it("keeps previous-turn token diagnostics out of the read-only status rail", () => {
    expect(routeSource).toContain("const lastContextComposition = detail?.lastContextComposition ?? null");
    expect(routeSource).toContain("const lastCacheComposition = detail?.lastCacheComposition ?? null");
    expect(routeSource).toContain("const lastLlmPayloadTrace = detail?.lastLlmPayloadTrace ?? null");
    expect(routeSource).toContain('import("./CacheDetailDialog")');
    expect(chatStatusRailSource).toContain('import("./LlmPayloadTracePanel")');
    expect(chatStatusRailSource).not.toContain("TokenCoreStatusPanel");
    expect(routeSource).not.toContain('from "./chatTokenStatusModel"');
    expect(routeSource).not.toContain("<details className={styles.sessionDiagnosticsDetails}>");
    expect(routeSource).not.toContain("<summary className={styles.sessionDiagnosticsSummary}>");
    expect(routeSource).not.toContain("const tokenCompressionContextBadge");
    expect(routeSource).not.toContain("const tokenCompressionThresholdBadge");
    expect(routeSource).not.toContain("styles.tokenCompressionBadges");
    expect(routeSource).not.toContain("<span className={styles.metricValue}>{compressionCurrentPercent}%</span>");
    expect(tokenCoreStatusPanelSource).toContain("styles.tokenCompressionCard");
    expect(routeAndTokenStatusSource).toContain("tokenStatusMetrics");
    expect(routeAndIndexRailSource).toContain("<LlmPayloadTracePanel");
    expect(routeAndIndexRailSource).toContain("trace={lastLlmPayloadTrace}");
    expect(routeAndIndexRailSource.indexOf("<LlmPayloadTracePanel")).toBeGreaterThan(
      routeAndIndexRailSource.indexOf("styles.currentSessionBlock"),
    );
    expect(tokenCoreStatusPanelSource).toContain("styles.tokenStatusVisualGrid");
    expect(tokenCoreStatusPanelSource).toContain("styles.tokenStatusMetric");
    expect(tokenCoreStatusPanelSource).toContain("styles.tokenStatusRing");
    expect(tokenCoreStatusPanelSource).toContain("styles.tokenStatusRingCore");
    expect(tokenCoreStatusPanelSource).toContain("styles.tokenStatusCopy");
    expect(tokenCoreStatusPanelSource).toContain("styles.tokenStatusBar");
    expect(tokenCoreStatusPanelSource).toContain("aria-labelledby={titleId}");
    expect(tokenCoreStatusPanelSource).toContain("id={titleId}");
    expect(tokenCoreStatusPanelSource).toContain("role=\"list\"");
    expect(tokenCoreStatusPanelSource).toContain("role=\"listitem\"");
    expect(routeSource).not.toContain("styles.tokenCompressionTable");
    expect(routeSource).not.toContain("styles.tokenCompressionDetails");
    expect(routeSource).not.toContain("const tokenCompressionRows");
    expect(routeSource).not.toContain("key: \"llm\"");
    expect(routeSource).not.toContain("key: \"output\"");
    expect(routeAndTokenStatusSource).toContain("key: \"cache\"");
    expect(routeAndTokenStatusSource).toContain("key: \"modelInput\"");
    expect(routeAndTokenStatusSource).toContain("key: \"compression\"");
    expect(routeAndTokenStatusSource).toContain("key: \"speed\"");
    expect(routeSource).not.toContain("key: \"strategy\"");
    expect(routeAndTokenStatusSource).toContain("t(\"previousCacheHit\")");
    expect(routeAndTokenStatusSource).toContain("label: lang === \"zh\" ? \"模型输入\" : \"Model input\"");
    expect(routeSource).not.toContain("label: lang === \"zh\" ? \"本轮上下文\" : \"Current context\"");
    expect(routeAndTokenStatusSource).toContain("label: lang === \"zh\" ? \"压缩状态\" : \"Compression\"");
    expect(routeAndTokenStatusSource).toContain("const tokenStatusCacheTitleLines");
    expect(routeAndTokenStatusSource).toContain("const tokenStatusCacheTitle = tokenStatusCacheTitleLines.join");
    expect(routeSource).not.toContain("const tokenStatusContextTitle = [");
    expect(routeAndTokenStatusSource).toContain("const tokenStatusCompressionTitleLines");
    expect(routeAndTokenStatusSource).toContain("const tokenStatusCompressionTitle = tokenStatusCompressionTitleLines.join");
    expect(tokenCoreStatusPanelSource).toContain("content={tooltipContent}");
    expect(tokenCoreStatusPanelSource).toContain("titleLines");
    expect(tokenCoreStatusPanelSource).toContain("\"--token-status-value\": metric.percent");
    expect(routeSource).toContain("cacheDetailOpenLabel");
    expect(routeSource).toContain("onOpenComposerContextDetail: !verifiedCompanionMode && cacheDetailAvailable ? openCacheDetail : undefined");
    expect(tokenCoreStatusPanelSource).toContain("isDisabled={!cacheDetailAvailable}");
    expect(tokenCoreStatusPanelSource).toContain("onClick={cacheDetailAvailable ? onOpenCacheDetail : undefined}");
    expect(tokenCoreStatusPanelSource).toContain("aria-disabled={!cacheDetailAvailable}");
    expect(tokenCoreStatusPanelSource).toContain("aria-expanded={cacheDetailAvailable ? cacheDetailOpen : undefined}");
    expect(tokenCoreStatusPanelSource).toContain("aria-controls={cacheDetailAvailable ? \"cache-detail-dialog\" : undefined}");
    expect(tokenCoreStatusPanelSource).toContain("role=\"listitem\"");
    expect(tokenCoreStatusPanelSource).toContain("<VButton");
    expect(routeAndTokenStatusSource).toContain("const modelInputTokens = Math.max(");
    expect(routeAndTokenStatusSource).toContain("lastCacheComposition?.calibratedInputTokens");
    expect(routeAndTokenStatusSource).toContain("hasProviderLlmUsage ? sessionLlmUsage.inputTokens : undefined");
    expect(routeAndTokenStatusSource).toContain("modelInputLimitMissing");
    expect(routeAndTokenStatusSource).toContain("modelInputLimitError");
    expect(routeAndTokenStatusSource).toContain("禁止默认兜底");
    expect(routeAndTokenStatusSource).not.toContain("compression?.contextWindowLimit");
    expect(routeAndTokenStatusSource).toContain("modelInputMetaLine");
    expect(routeAndTokenStatusSource).toContain("modelInputTitle");
    expect(routeAndTokenStatusSource).toContain("compressionThresholdValue");
    expect(routeAndTokenStatusSource).toContain("compressionThresholdMeta");
    expect(routeAndTokenStatusSource).toContain("tokenCompressionStrategyTitle");
    expect(routeAndCacheDetailSource).toContain("buildCacheDonutSegments(cachePromptCompositionSegments, cachePromptCompositionTotalTokens)");
    expect(routeAndCacheDetailSource).toContain("lastCacheComposition?.computedSegments");
    expect(routeAndCacheDetailSource).toContain("lastCacheComposition?.calibratedSegments");
    expect(routeAndCacheDetailSource).toContain("calibratedCachedInputTokens");
    expect(routeAndCacheDetailSource).toContain("upperBoundCachedInputTokens");
    expect(routeAndCacheDetailSource).toContain("upperBoundCacheHitRate");
    expect(sessionCacheCompositionSource).toContain("predictedCachedInputTokens");
    expect(sessionCacheCompositionSource).toContain("predictedCacheHitRate");
    expect(routeAndCacheDetailSource).toContain("computedOverestimatedInputTokens");
    expect(routeAndCacheDetailSource).toContain("calibrationReason");
    expect(routeAndCacheDetailSource).toContain("averageCacheHitRate");
    expect(routeAndCacheDetailSource).toContain("averageObservedTurnCount");
    expect(routeAndCacheDetailSource).toContain("setCacheDetailOpen(true)");
    expect(tokenCoreStatusPanelSource).not.toContain("aria-controls={cacheDetailOpen ? \"cache-detail-dialog\" : undefined}");
    expect(routeSource).not.toContain("className={styles.contextCompositionItem} title={cacheCompositionTitle}");
    expect(tokenCoreStatusPanelSource).toContain("content={tooltipContent}");
    expect(routeAndCacheDetailSource).toContain("handleCacheDetailKeyDown");
    expect(routeAndCacheDetailSource).toContain("event.key === \"Escape\"");
    expect(routeAndCacheDetailSource).toContain("setCacheDetailOpen(false)");
    expect(cacheDetailDialogSource).toContain("styles.cacheDonutOuterSegment");
    expect(cacheDetailDialogSource).toContain("styles.cacheDonutInnerSegment");
    expect(cacheDetailDialogSource).toContain("promptSegmentCategory(segment)");
    expect(cacheDetailDialogSource).toContain("cachePromptSegmentClass(segment)");
    expect(cacheDetailDialogSource).toContain("cachePromptLegendSegmentClass(segment)");
    expect(routeAndCacheDetailSource).toContain("promptSegmentDisplayLabel(segment, lang, t)");
    expect(cacheDetailDialogSource).toContain("promptSegmentCategoryLabel(segment, lang)");
    expect(cacheDetailDialogSource).toContain("promptSegmentAccuracyLabel(segment, lang)");
    expect(cacheDetailDialogSource).toContain("cacheDonutSegmentStyle(segment, cachePromptDonutSegments.length > 1 ? 0.18 : 0)");
    expect(cacheDetailDialogSource).toContain("cachePromptSegmentHoverTitle(segment, cachePromptCompositionTotalTokens, numberFormatter, lang, missingSegmentLabel)");
    expect(cacheDetailDialogSource).toContain("cacheDonutSegmentTitle(segment, cachePromptCompositionTotalTokens, numberFormatter, lang)");
    expect(cacheDetailDialogSource).toContain("cacheObservedStatusLabel(segment.observedStatus, lang)");
    expect(cacheDetailDialogSource).toContain("cacheComputedStatusLabel(segment.status, lang)");
    expect(cacheDetailDialogSource).toContain("segment.contentPreview");
    expect(routeSource).not.toContain("{lang === \"zh\" ? \"预测命中\" : \"Predicted hit\"}");
    expect(cacheDetailDialogSource).toContain("{lang === \"zh\" ? \"上轮真实命中\" : \"Last-turn true hit\"}");
    expect(cacheDetailDialogSource).toContain("{lang === \"zh\" ? \"会话平均\" : \"Session average\"}");
    expect(cacheDetailDialogSource).not.toContain("{lang === \"zh\" ? \"读数说明\" : \"How to read\"}");
    expect(cacheDetailDialogSource).toContain("CacheHoverLines");
    expect(cacheDetailDialogSource).toContain("VTooltip");
    expect(cacheDetailDialogSource).toContain("{lang === \"zh\" ? \"上界未兑现\" : \"upper bound gap\"}");
    expect(cacheDetailDialogSource).not.toContain("styles.cacheDonutLegendPreview");
    expect(cacheDetailDialogSource).not.toContain("key={`${segment.key}-${segment.status}-${index}-legend`}");
    expect(routeSource).toContain("<CacheDetailDialog");
    expect(cacheDetailDialogSource).toContain("<VDialog");
    expect(cacheDetailDialogSource).toContain("contentClassName={styles.cacheDetailDialog}");
    expect(cacheDetailDialogSource).toContain("onOpenChange=");
    expect(cacheDetailDialogSource).not.toContain("styles.cacheDetailOverlay");
    expect(cacheDetailDialogSource).not.toContain("createPortal(");
    expect(cacheDetailDialogSource).toContain("styles.cacheDetailSummaryGrid");
    expect(cacheDetailDialogSource).not.toContain("styles.cacheDetailCalibrationNote");
    expect(routeSource).toContain("cacheCalibrationSummaryText={cacheCalibrationSummaryText}");
    expect(cacheDetailDialogSource).not.toContain("styles.cacheDetailDonutLegend");
    expect(cacheDetailDialogSource).toContain("donutLegendHover");
    expect(cacheDetailDialogSource).toContain("styles.cacheDetailSegmentSource");
    expect(cacheDetailDialogSource).toContain("styles.cacheDetailSegmentList");
    expect(cacheDetailDialogSource).toContain("styles.cacheDetailBoundary");
    expect(cacheDetailDialogSource).toContain("styles.cacheDetailBoundaryTrack");
    expect(cacheDetailDialogSource).toContain("styles.cacheDetailBoundaryHit");
    expect(cacheDetailDialogSource).toContain("styles.cacheDetailBoundaryMiss");
    expect(cacheDetailDialogSource).toContain("--cache-boundary-hit-width");
    expect(cacheDetailDialogSource).toContain("--cache-boundary-miss-width");
    expect(cacheDetailDialogSource).toContain("--cache-boundary-unknown-width");
    expect(cacheDetailDialogSource).not.toContain("style={{ width: `${observedCachedPercent}%` }}");
    expect(cacheDetailDialogSource).not.toContain("style={{ width: `${observedMissedPercent}%` }}");
    expect(cacheDetailDialogSource).not.toContain("style={{ width: `${observedUnknownPercent}%` }}");
    expect(cacheDetailDialogSource).toContain("observedCachedPercent");
    expect(cacheDetailDialogSource).toContain("observedMissedPercent");
    expect(cacheDetailDialogSource).toContain("styles.cacheDetailDonutPanel");
    expect(cacheDetailDialogSource).toContain("case \"cache_write\"");
    expect(routeAndCacheDetailSource).toContain("averageCacheObservedTurnCount");
    expect(routeAndCacheDetailSource).toContain("上轮");
    expect(routeAndIndexRailSource).toContain("styles.currentSessionBlock");
    expect(routeAndIndexRailSource).toContain("styles.currentSessionLine");
    expect(routeAndIndexRailSource).toContain("styles.currentSessionMetaList");
    expect(routeAndTokenStatusSource).toContain("· 缓 ${numberFormatter.format(sessionLlmUsage.cachedInputTokens)}");
    expect(routeAndTokenStatusSource).not.toContain("${numberFormatter.format(sessionLlmUsage.inputTokens)} tokens · ${numberFormatter.format(sessionLlmUsage.cachedInputTokens)} cached");
    expect(chatStatusRailSource).not.toContain("styles.runModeBlock");
    expect(chatStatusRailSource).not.toContain("styles.mentalRuntimeBlock");
    expect(routeSource).not.toContain("className={`${styles.leftBlock} ${styles.contextStatusCard}`}");
    expect(routeSource).not.toContain("className={`${styles.leftBlock} ${styles.cacheStatusCard}`}");
    expect(routeSource).not.toContain("className={`${styles.leftBlock} ${styles.resourceBlock} ${styles.compressionStatusCard}`}");
    expect(routeSource).not.toContain("className={`${styles.leftBlock} ${styles.compressionStrategyCard}`}");
    expect(routeAndCacheDetailSource).toContain("lastCacheComposition.source === \"not_called\"");
    expect(routeStyles.leftRail).toContain("[grid-column:5]");
    expect(chatStatusRailSource).not.toContain("tokenStatusMetrics");

    expect(routeStyles.tokenCompressionCard).toBeTypeOf("string");
    expect(routeStyles.tokenStatusVisualGrid).toBeTypeOf("string");
    expect(routeStyles.tokenStatusMetric).toBeTypeOf("string");
    expect(routeStyles.tokenStatusMetricButton).toBeTypeOf("string");
    expect(routeStyles.tokenStatusMetric_cache).toBeTypeOf("string");
    expect(routeStyles.tokenStatusMetric_modelInput).toBeTypeOf("string");
    expect(routeStyles.tokenStatusMetric_compression).toBeTypeOf("string");
    expect(routeStyles.tokenStatusRing).toBeTypeOf("string");
    expect(routeStyles.tokenStatusRingCore).toBeTypeOf("string");
    expect(routeStyles.tokenStatusCopy).toBeTypeOf("string");
    expect(routeStyles.tokenStatusLabel).toBeTypeOf("string");
    expect(routeStyles.tokenStatusMeta).toBeTypeOf("string");
    expect(routeStyles.tokenStatusBar).toBeTypeOf("string");
    expect(routeStyles.currentSessionBlock).toBeTypeOf("string");
    expect(routeStyles.currentSessionLine).toBeTypeOf("string");
    expect(routeStyles.currentSessionMetaList).toBeTypeOf("string");
    expect(routeStyles.cacheDonutShell).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSvg).toBeTypeOf("string");
    expect(routeStyles.cacheDonutTrack).toBeTypeOf("string");
    expect(routeStyles.cacheDonutOuterTrack).toBeTypeOf("string");
    expect(routeStyles.cacheDonutInnerTrack).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegment).toBeTypeOf("string");
    expect(routeStyles.cacheDonutOuterSegment).toBeTypeOf("string");
    expect(routeStyles.cacheDonutInnerSegment).toBeTypeOf("string");
    expect(routeStyles.cacheDonutCenter).toBeTypeOf("string");
    expect(routeStyles.cacheDonutStats).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentCached).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentCacheWrite).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentUncached).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentMissing).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentOther).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentSystem).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentUser).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentHistory).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentTask).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentAgent).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentProjectRules).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentToolDescriptions).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentToolSchema).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentProviderUnmapped).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentGuidance).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentSkill).toBeTypeOf("string");
    expect(routeStyles.cacheDonutSegmentAttachments).toBeTypeOf("string");
    expect(cacheDetailStyles.cacheDetailDialog).toBeTypeOf("string");
    expect(routeStyles.cacheDetailDialog).toBeTypeOf("string");
    expect(routeStyles.cacheDetailSummaryGrid).toBeTypeOf("string");
    expect(routeStyles.cacheDetailCalibrationNote).toBeTypeOf("string");
    expect(routeStyles.cacheDetailBody).toBeTypeOf("string");
    expect(routeStyles.cacheDetailDonutPanel).toBeTypeOf("string");
    expect(routeStyles.cacheDetailDonutShell).toBeTypeOf("string");
    expect(routeStyles.cacheDetailDonutSvg).toBeTypeOf("string");
    expect(routeStyles.cacheDetailDonutCenter).toBeTypeOf("string");
    expect(routeStyles.cacheDetailDonutLegend).toBeTypeOf("string");
    expect(routeStyles.cacheDetailSegmentList).toBeTypeOf("string");
    expect(routeStyles.cacheDetailSegmentGroup).toBeTypeOf("string");
    expect(routeStyles.cacheDetailSegmentHeader).toBeTypeOf("string");
    expect(routeStyles.cacheDetailSegmentRow).toBeTypeOf("string");
    expect(routeStyles.cacheDetailSwatch).toBeTypeOf("string");
    expect(routeStyles.cacheDetailSegmentText).toBeTypeOf("string");
    expect(routeStyles.cacheDetailSegmentSource).toBeTypeOf("string");
    expect(routeStyles.cacheDetailSegmentMeta).toBeTypeOf("string");
    expect(routeStyles.cacheDetailBoundary).toBeTypeOf("string");
    expect(routeStyles.cacheDetailBoundaryLabels).toBeTypeOf("string");
    expect(routeStyles.cacheDetailBoundaryTrack).toBeTypeOf("string");
    expect(routeStyles.cacheDetailBoundaryHit).toBeTypeOf("string");
    expect(routeStyles.cacheDetailBoundaryMiss).toBeTypeOf("string");
    expect(routeStyles.cacheDetailBoundaryUnknown).toBeTypeOf("string");
    expect(routeStyles.cacheDetailEmpty).toBeTypeOf("string");
    expect(routeStyles.cacheDetailDialog).toContain("w-[min(1120px,calc(100vw_-_44px))]");
    // Wave 6H: dialog shells stay viewport-clamped (not workbench height API).
    expect(routeStyles.cacheDetailDialog).toContain("max-h-[min(860px,calc(100dvh_-_52px))]");
    expect(routeStyles.cacheDetailDialog).toContain("100dvh");
    expect(routeStyles.cacheDetailBody).toContain("max-h-[min(620px,calc(100dvh_-_238px))]");
    expect(cacheDetailDialogSource).not.toContain("usePersistedPaneHeight");
    expect(cacheDetailDialogSource).not.toContain("PersistedHeightListShell");
    expect(routeStyles.cacheDetailBody).toContain("[scrollbar-gutter:stable]");
    expect(routeStyles.tokenStatusRing).toContain("relative");
    expect(routeStyles.tokenStatusRing).toContain("conic-gradient");
    expect(routeStyles.tokenStatusBar).toContain("[&>span]:w-[calc(var(--token-status-value)*1%)]");
    expect(routeStyles.cacheDetailBoundaryTrack).toContain("flex");
    expect(routeStyles.cacheDetailBoundaryTrack).toContain("h-2");
    expect(routeStyles.cacheDetailBoundaryHit).toContain("w-[var(--cache-boundary-hit-width)]");
    expect(routeStyles.cacheDetailBoundaryMiss).toContain("w-[var(--cache-boundary-miss-width)]");
    expect(routeStyles.cacheDetailBoundaryUnknown).toContain("w-[var(--cache-boundary-unknown-width)]");
    expect(routeStyles.cacheDetailSegmentHeader).toContain("flex");
    expect(routeStyles.cacheDetailSegmentHeader).toContain("items-baseline");
    expect(routeStyles.cacheDetailSegmentHeader).not.toContain("rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)]");
    expect(routeStyles.cacheDetailSegmentHeader).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(routeStyles.cacheDetailSegmentHeader).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    for (const value of [routeStyles.cacheDonutShell, routeStyles.cacheDetailDonutShell]) {
      expect(value).toContain("grid");
      expect(value).not.toContain("bg-[var(--surface-page)]");
      expect(value).not.toContain("bg-[var(--vui-surface-glass)]");
      expect(value).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    }
    expect(routeStyles.cacheDonutSegmentToolDescriptions).toContain("stroke-[var(--accent-warm)]");
    expect(routeStyles.cacheDonutSegmentToolSchema).toContain("stroke-[var(--accent-warm)]");
    expect(routeStyles.contextCompositionSegmentSystem).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentProjectRules).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentToolDescriptions).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentToolSchema).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentProviderUnmapped).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentCached).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentCacheWrite).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentUncached).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentMissing).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentExact).toBeTypeOf("string");
    expect(routeStyles.contextCompositionSegmentUnused).toBeTypeOf("string");
    expect(llmPayloadTracePanelSource).toContain('import styles from "./LlmPayloadTracePanel.styles"');
    expect(llmPayloadTracePanelSource).toContain("styles.llmPayloadTracePanel");
    expect(llmPayloadTracePanelSource).toContain("styles.llmPayloadTraceGrid");
    expect(llmPayloadTracePanelSource).toContain("styles.llmPayloadTraceItem");
    expect(llmPayloadTracePanelSource).toContain("styles.llmPayloadTraceMuted");
  });

  it("keeps Prompt assembly diagnostics in the status rail instead of the conversation timeline", () => {
    expect(chatSessionWorkspacePanelSource).not.toContain("ChatPromptAssemblyInspector");
    expect(chatSessionWorkspacePanelSource).not.toContain("promptSnapshot");
    expect(chatStatusRailSource).toContain('import { ChatPromptAssemblyInspector }');
    expect(chatStatusRailSource).toContain("promptSnapshot?: SessionAgentPromptSnapshot");
    expect(chatStatusRailSource).toContain("promptAssembly?: SessionPromptAssemblyManifest");
    expect(chatStatusRailSource).toContain("<ChatPromptAssemblyInspector");
    expect(chatStatusRailSource.indexOf("<ChatPromptAssemblyInspector")).toBeGreaterThan(
      chatStatusRailSource.indexOf("styles.currentSessionBlock"),
    );
    expect(routeSource).toContain("promptSnapshot={detail?.agentPromptSnapshot}");
    expect(routeSource).toContain("promptAssembly={detail?.lastPromptAssembly}");
  });

  it("disables the cache metric trigger when cache details are unavailable", () => {
    const unavailableHtml = renderToStaticMarkup(
      createElement(TokenCoreStatusPanel, {
        cacheDetailAvailable: false,
        cacheDetailOpen: true,
        cacheDetailOpenLabel: "查看上一轮缓存命中详情",
        lang: "zh",
        metrics: tokenCoreStatusMetrics,
        onOpenCacheDetail: () => undefined,
      }),
    );
    const availableHtml = renderToStaticMarkup(
      createElement(TokenCoreStatusPanel, {
        cacheDetailAvailable: true,
        cacheDetailOpen: true,
        cacheDetailOpenLabel: "查看上一轮缓存命中详情",
        lang: "zh",
        metrics: tokenCoreStatusMetrics,
        onOpenCacheDetail: () => undefined,
      }),
    );
    const availableClosedHtml = renderToStaticMarkup(
      createElement(TokenCoreStatusPanel, {
        cacheDetailAvailable: true,
        cacheDetailOpen: false,
        cacheDetailOpenLabel: "查看上一轮缓存命中详情",
        lang: "zh",
        metrics: tokenCoreStatusMetrics,
        onOpenCacheDetail: () => undefined,
      }),
    );

    expect(unavailableHtml).toContain("disabled");
    expect(unavailableHtml).toContain("aria-disabled=\"true\"");
    expect(unavailableHtml).not.toContain("aria-expanded");
    expect(unavailableHtml).not.toContain("aria-controls=\"cache-detail-dialog\"");
    // HeroUI omits a false ARIA state for an enabled native button. The
    // accessibility contract is that it must not remain disabled.
    expect(availableHtml).not.toContain("aria-disabled=\"true\"");
    expect(availableHtml).toContain("aria-expanded=\"true\"");
    expect(availableHtml).toContain("aria-controls=\"cache-detail-dialog\"");
    expect(availableClosedHtml).toContain("aria-expanded=\"false\"");
    expect(availableClosedHtml).toContain("aria-controls=\"cache-detail-dialog\"");
  });

  it("keeps compact token metric values inside the narrow status ring", () => {
    const compactMetrics: Array<TokenCoreStatusMetric & { displayValue: string }> = [
      {
        key: "modelInput",
        label: "模型输入",
        value: "128,000",
        displayValue: "128k",
        meta: "128,000 / 200,000 · 64%",
        title: "模型输入 128,000",
        percent: 64,
        tone: "modelInput",
      },
    ];
    const html = renderToStaticMarkup(
      createElement(TokenCoreStatusPanel, {
        cacheDetailAvailable: false,
        cacheDetailOpen: false,
        cacheDetailOpenLabel: "查看上一轮缓存命中详情",
        lang: "zh",
        metrics: compactMetrics,
        onOpenCacheDetail: () => undefined,
      }),
    );

    expect(tokenCoreStatusPanelSource).toContain("metric.displayValue ?? metric.value");
    expect(html).toContain(">128k</span>");
    expect(html).toContain("128,000 / 200,000");
    expect(html).toContain('aria-label="模型输入 128,000. 128,000 / 200,000 · 64%"');
    expect(routeAndPresentationSource).toContain("const compactNumberFormatter = useMemo(");
    expect(routeSource).toContain("useChatLocaleFormatters");
    expect(routeAndTokenStatusSource).toContain("displayValue: modelInputLimitMissing");
    expect(routeAndTokenStatusSource).toContain("formatTokenStatusRingCompact(modelInputTokens, compactNumberFormatter)");
  });

  it("shows the active skill contract before prompt and payload evidence", () => {
    expect(routeAndSessionSurfaceSource).toContain("export type ActiveSkillContract = {");
    expect(routeSource).toContain("type SessionDetailWithActiveSkill = SessionDetail &");
    expect(routeSource).toContain("contract: (detail as SessionDetailWithActiveSkill | undefined)?.activeSkillContract");
    expect(routeAndSessionSurfaceSource).toContain("const activeSkillStatusLabel = activeSkillStatus === \"stale\"");
    expect(routeAndIndexRailSource).toContain("styles.activeSkillStatus_stale");
    expect(routeAndIndexRailSource).toContain("styles.activeSkillStatus_missing");
    expect(routeAndSessionSurfaceSource).toContain("const activeSkillTitle = activeSkillContract");
    expect(routeSource).toContain("const activeSkillStatusStyle = activeSkillStatus === \"stale\"");
    expect(routeAndIndexRailSource).toContain("className={`${styles.activeSkillStatus} ${activeSkillStatusStyle}`}");
    expect(routeAndIndexRailSource).toContain("styles.activeSkillIdentity");
    expect(routeAndIndexRailSource).toContain("styles.activeSkillMeta");
    expect(routeAndHelpersSource).toContain("case \"active_skill\":");
    const renderedActiveSkillIndex = routeAndIndexRailSource.indexOf(
      "className={`${styles.activeSkillStatus} ${activeSkillStatusStyle}`}",
    );
    expect(renderedActiveSkillIndex).toBeGreaterThan(routeAndIndexRailSource.indexOf("sessionCompactRows.map"));
    expect(renderedActiveSkillIndex).toBeLessThan(routeAndIndexRailSource.indexOf("<ChatPromptAssemblyInspector"));
    expect(renderedActiveSkillIndex).toBeLessThan(routeAndIndexRailSource.indexOf("<LlmPayloadTracePanel"));

    expect(routeStyles.activeSkillStatus).toBeTypeOf("string");
    expect(routeStyles.activeSkillStatus_active).toBeTypeOf("string");
    expect(routeStyles.activeSkillStatus_stale).toBeTypeOf("string");
    expect(routeStyles.activeSkillStatus_missing).toBeTypeOf("string");
    expect(routeStyles.activeSkillIdentity).toBeTypeOf("string");
    expect(routeStyles.activeSkillEyebrow).toBeTypeOf("string");
    expect(routeStyles.activeSkillMeta).toBeTypeOf("string");
    expect(routeStyles.activeSkillState).toBeTypeOf("string");
  });

  it("keeps provider-observed LLM usage available in token hover details", () => {
    expect(routeAndTokenStatusSource).toContain("const sessionLlmUsage = detail?.llmUsage ?? null");
    expect(routeAndTokenStatusSource).toContain("sessionLlmUsage?.source === \"provider_usage\"");
    expect(routeAndTokenStatusSource).toContain("sessionLlmUsage?.source === \"not_called\"");
    expect(routeSource).not.toContain("key: \"llm\"");
    expect(routeSource).not.toContain("key: \"output\"");
    expect(routeSource).not.toContain("label: lang === \"zh\" ? \"输入\" : \"Input\"");
    expect(routeSource).not.toContain("label: lang === \"zh\" ? \"输出\" : \"Output\"");
    expect(routeSource).not.toContain("const tokenInputLine = hasProviderLlmUsage");
    expect(routeSource).not.toContain("const tokenOutputLine = hasProviderLlmUsage");
    expect(routeAndTokenStatusSource).toContain("const llmUsageLine = hasProviderLlmUsage");
    expect(routeAndTokenStatusSource).toContain("const llmUsageTitle = hasProviderLlmUsage");
    expect(routeAndTokenStatusSource).toContain("const tokenStatusCacheTitleLines");
    expect(routeAndTokenStatusSource).toContain("numberFormatter.format(sessionLlmUsage.outputTokens)");
    expect(routeAndTokenStatusSource).toContain("t(\"llmUsageNotCalled\")");
    expect(routeAndTokenStatusSource).toContain("t(\"llmUsageMissing\")");
    expect(routeAndTokenStatusSource).toContain("modelInputTitle");
  });

  it("labels runtime compression as a separate estimate from session message history", () => {
    expect(routeSource).not.toContain("const contextSourceLine = lastContextComposition");
    // High-value compression hover (chatTokenStatusModel); no long · soup dump.
    expect(routeAndTokenStatusSource).toContain("const compressionPolicySourceLine = compression");
    expect(routeAndTokenStatusSource).toContain("compression.policySource === \"agent_custom\"");
    expect(routeAndTokenStatusSource).toContain("Agent 自定义策略");
    expect(routeAndTokenStatusSource).toContain("继承全局策略");
    expect(tokenCoreStatusPanelSource).toContain("styles.tokenCompressionCard");
    expect(routeAndTokenStatusSource).toContain("key: \"compression\"");
    expect(routeSource).not.toContain("key: \"strategy\"");
    expect(routeAndTokenStatusSource).toContain("const tokenStatusCompressionTitleLines");
    expect(routeAndTokenStatusSource).toContain("compressionMainLine");
    expect(routeAndTokenStatusSource).toContain("compressionThresholdValue");
    expect(routeAndTokenStatusSource).toContain("compressionThresholdMeta");
  });

  it("keeps the current session status bar keyed to the selected session", () => {
    expect(routeSource).toContain("const rawSessionDetail = resolveActiveSessionDetailForUi");
    expect(routeSource).toContain("const detail = useStableSessionDetailPaint({");
    expect(routeSource).toContain("detail: rawSessionDetail");
    expect(routeSource).toContain("const activeTurnLayer = activeSessionId ? activeTurnLayersBySession[activeSessionId] : undefined");
    expect(routeSource).toContain("const activeTurnSettledByDetail = isActiveTurnSettledByDetail(activeTurnLayer, detail)");
    expect(routeSource).toContain("const activeTurnMessage = useMemo(");
    expect(routeSource).toContain("activeTurnSettledByDetail ? undefined : activeTurnLayerToConversationMessage(activeTurnLayer)");
    expect(routeSource).toContain("setActiveTurnLayerForSession(current, activeSessionId, undefined)");
    expect(routeSource).toContain('eventCode: "browser.session_stream.active_layer_reconciled"');
    expect(routeSource).toContain('source: "session_detail_query"');
    expect(routeSource).toContain("const runtimeMatchesSelectedSession = runtimeMatchesSelectedChatSession({");
    expect(routeSource).toContain("activeRuntimeSessionId: activeSessionBootstrapQuery.data?.activeSessionId");
    expect(routeSource).toContain("activeWorkSessionIds: runtimeActiveChatTurnSessionIds");
    expect(routeSource).toContain("const runtimeMismatchLine = runtimeActiveChatTurnSessionId && !runtimeMatchesSelectedSession");
    expect(routeAndSessionSurfaceSource).toContain("const noActiveDirectSessionTitle =");
    expect(routeAndSessionSurfaceSource).toMatch(/!\s*activeSessionId\s*\?\s*noActiveDirectSessionTitle/);
    expect(routeAndTokenStatusSource).toContain("lastContextComposition?.totalTokens ?? sessionContextUsage?.used ?? 0");
    expect(routeAndTokenStatusSource).toContain("lastContextComposition?.limitTokens ?? sessionContextUsage?.limit ?? 0");
    expect(chatStatusRailSource).not.toContain("contextCompression");
    expect(chatStatusRailSource).not.toContain("TokenCoreStatusPanel");
    expect(routeAndSessionSurfaceSource).toContain("runtimeMatchesSelectedSession && runtimeSessionStateLine");
    expect(routeAndSessionSurfaceSource).toMatch(/!\s*activeSessionId\s*\?\s*noActiveDirectSessionLine/);
    expect(routeAndSessionSurfaceSource).toContain("runtimeMismatchLine || (sessionDetailBlockingError");
    expect(routeAndSessionSurfaceSource).toContain("(runtimeMatchesSelectedSession ? runtimeTaskSummary : \"\")");
    expect(routeAndSessionSurfaceSource).toContain("detail?.defaultFileContext ?? (runtimeMatchesSelectedSession ? runtimeDefaultRoute : undefined) ?? \"workspace\"");
    expect(routeSource).toContain("buildChatSessionStateViewModel");

    expect(routeSource).not.toContain("detail?.title ?? runtime?.sessionTitle");
    expect(routeSource).not.toContain("directSessionActiveSummary?.title ?? t(\"loadingSession\")");
    expect(routeSource).not.toContain("sessionContextUsage?.used ?? runtime?.contextUsage.used");
    expect(routeSource).not.toContain("sessionContextUsage?.limit ?? runtime?.contextUsage.limit");
    expect(routeSource).not.toContain("runtimeMatchesSelectedSession && runtime?.sessionStateLine");
    expect(routeSource).not.toContain("|| (runtimeMatchesSelectedSession ? runtime?.taskSummary : \"\")");
    expect(routeSource).not.toContain("detail?.defaultFileContext ?? runtime?.defaultRoute");
  });

  it("uses the model context window, not the compression threshold, for model input usage", () => {
    expect(routeAndTokenStatusSource).toContain("const modelInputLimitTokens = Math.max(");
    expect(routeAndTokenStatusSource).toContain("lastContextComposition?.limitTokens");
    expect(routeAndTokenStatusSource).toContain("sessionContextUsage?.limit");
    expect(routeAndTokenStatusSource).toContain("modelInputLimitMissing");
    expect(routeAndTokenStatusSource).not.toContain("compression?.contextWindowLimit");
    expect(routeAndTokenStatusSource).not.toContain("compression?.effectiveTokenLimit\n      ?? compression?.contextWindowLimit");
  });

  it("moves recent control signals into the current session status bar", () => {
    expect(routeSource).toContain("const activeControlSignals = useMemo<ChatNextStateSignalSummary[]>");
    expect(routeSource).toContain(
      "shouldShowNextStateSignalInConversation(signal, phase, detail?.messages ?? [])",
    );
    expect(routeSource).toContain("const latestControlSignalKindLabel = (() =>");
    expect(routeSource).toContain("const latestControlSignalLine = latestControlSignal");
    expect(routeSource).toContain("return lang === \"zh\" ? \"工具失败\" : \"Tool failed\"");
    expect(routeSource).toContain("latestControlSignalTitle");
    expect(routeAndSessionSurfaceSource).toContain("label: t(\"nextStateSignalsLabel\")");
    expect(routeAndSessionSurfaceSource).toContain("value: latestControlSignalLine");
    expect(routeAndSessionSurfaceSource).toContain("title: latestControlSignalTitle");
    expect(routeSource).not.toContain("nextStateSignals={detail.nextStateSignals ?? []}");
    expect(routeStyles.inlineMetaPill).toContain("[&_strong]:truncate");
    expect(routeStyles.inlineMetaPill).toContain("[&_span]:text-[var(--fg-tertiary)]");
  });

  it("does not maintain live token-speed UI state after removing rail metrics", () => {
    expect(routeSource).not.toContain("tokenSpeedSampleFromMessages(");
    expect(routeSource).not.toContain("const [tokenSpeedTracker");
    expect(routeSource).not.toContain("buildChatTokenStatusViewModel(");
    expect(chatStatusRailSource).not.toContain("tokenStatusMetrics");
    expect(chatStatusRailSource).not.toContain("TokenCoreStatusPanel");
  });

  it("keeps direct-session mismatch read-only in the rail and moves its action into plus", () => {
    expect(chatStatusRailSource).toContain("agentDirectSessionMismatch");
    expect(chatStatusRailSource).toContain("sessionBindingNotice");
    expect(chatStatusRailSource).toContain("sessionBindingMismatchLine");
    expect(chatStatusRailSource).not.toContain("onOpenDirectSession");
    expect(routeAndSessionSurfaceSource).toContain("label: t(\"sessionBinding\")");
    expect(routeSource).toContain("directSession={agentDirectSessionMismatch && agentPrimaryDirectSessionId ? {");
    expect(routeSource).toContain("onOpen: () => handleOpenDirectSession(agentPrimaryDirectSessionId)");
    expect(chatComposerPlusMenuSource).toContain('id: "open-direct-session"');
    expect(routeSource).not.toContain("label: t(\"currentTask\")");
  });

  it("records direct chat submit lifecycle telemetry before backend acceptance", () => {
    expect(routeAndComposerSource).toContain("postSubmitTelemetry");
    expect(routeAndComposerSource).toContain("browser.chat_submit.requested");
    expect(routeAndComposerSource).toContain("browser.chat_submit.blocked");
    expect(routeAndComposerSource).toContain("browser.chat_submit.upload_started");
    expect(routeAndComposerSource).toContain("browser.chat_submit.upload_failed");
    expect(routeAndComposerSource).toContain("browser.chat_submit.mutate_called");
    expect(routeAndComposerSource).toContain("browser.chat_submit.request_started");
    expect(routeAndComposerSource).toContain("browser.chat_submit.accepted");
    expect(routeAndComposerSource).toContain("browser.chat_submit.request_failed");
    expect(routeAndComposerSource).toContain("contentLength");
    expect(routeAndComposerSource).toContain("guardReason");
    expect(chatSubmitTelemetrySource).toContain("fields.clientSubmissionId = options.clientSubmissionId");
    expect(chatSubmitTelemetrySource).toContain("fields.turnId = options.turnId");
    expect(chatSubmitTelemetrySource).toContain("fields.acceptedAt = options.acceptedAt");
    expect(routeAndComposerSource).toContain("requestStartedAtMs: chatStreamPerformanceNowMs()");
    expect(routeAndComposerSource).toContain("durationMs: Math.max(0, chatStreamPerformanceNowMs() - variables.requestStartedAtMs)");
    expect(routeAndComposerSource).not.toContain("fields: { content,");
  });

  it("clears the direct chat composer immediately after submit and restores only failed text", () => {
    const submitWithAttachmentsStart = routeAndComposerSource.indexOf("const submitTurnWithAttachments = useCallback(async (");
    const optimisticAppend = routeAndComposerSource.indexOf(
      "appendOptimisticUserMessage(detailState, { sessionId, content, references, clientSubmissionId })",
      submitWithAttachmentsStart,
    );
    const immediateDraftClear = routeAndComposerSource.indexOf("clearSessionDraftForSubmittedTurn(current, sessionId)", submitWithAttachmentsStart);
    const uploadFailureDraftRestore = routeAndComposerSource.indexOf(
      "restoreSubmittedDraftIfComposerStillEmpty(current, sessionId, content)",
      submitWithAttachmentsStart,
    );
    expect(submitWithAttachmentsStart).toBeGreaterThan(-1);
    expect(immediateDraftClear).toBeGreaterThan(submitWithAttachmentsStart);
    expect(immediateDraftClear).toBeLessThan(optimisticAppend);
    expect(uploadFailureDraftRestore).toBeGreaterThan(optimisticAppend);
    expect(routeAndComposerSource).toContain("const clientSubmissionId = createClientSubmissionId(activeSessionId)");
    expect(routeAndComposerSource).toContain("clientSubmissionId,");

    const submitMutationStart = routeAndComposerSource.indexOf("const submitTurnMutation = useMutation");
    const submitSuccessStart = routeAndComposerSource.indexOf("onSuccess: (acceptedTurn, variables, context)", submitMutationStart);
    const submitErrorStart = routeAndComposerSource.indexOf("onError: (error, variables, context)", submitSuccessStart);
    const submitSuccessBlock = routeAndComposerSource.slice(submitSuccessStart, submitErrorStart);
    const submitErrorBlock = routeAndComposerSource.slice(submitErrorStart, routeAndComposerSource.indexOf("const editResubmitMutation", submitErrorStart));
    expect(submitSuccessBlock).not.toContain("setSessionDrafts");
    expect(submitErrorBlock).toContain("restoreSubmittedDraftIfComposerStillEmpty(current, variables.sessionId, variables.content)");
  });

  it("keeps mental model next-turn opt-in explicit without gating historical snapshots", () => {
    expect(routeSource).toContain("readStoredMentalModelToggle() ?? false");
    expect(routeSource).not.toContain("const defaultEnabled = String(runtime.mentalState?.source");
    expect(routeSource).toContain("const verifiedCompanionMode = Boolean(activeCompanion);");
    expect(routeSource).toContain("showMentalSnapshots: !verifiedCompanionMode");
    expect(routeSource).not.toContain("showMentalSnapshots: mentalModelEnabledForNextTurn");
    expect(routeAndComposerSource).toContain("mentalModelEnabled: mentalModelEnabledForNextTurn");
    expect(routeAndIndexRailSource).toContain("const memberMental = latestMentalSnapshot(memberDetail?.messages)");
    expect(routeAndIndexRailSource).not.toContain("mentalModelEnabledForNextTurn ? latestMentalSnapshot");
    expect(routeSource).toContain("onMentalModelEnabledChange={handleMentalModelEnabledChange}");
    expect(chatComposerPlusMenuSource).toContain('id: "mental-model"');
    expect(chatComposerPlusMenuSource).toContain("checked: mentalModelEnabled");
  });

  it("exposes dynamic group creation from the unified conversation list", () => {
    expect(routeSource).toContain("handleToggleGroupComposer");
    expect(routeSource).toContain("handleCreateGroupRoom");
    expect(routeSource).toContain("listAgentSummaries()");
    expect(chatApiSource).toContain("body: JSON.stringify({ title, agentIds, mode, purpose })");
    expect(routeAndLifecycleSource).toContain("createChatRoom({ title, agentIds, mode, purpose })");
    expect(routeAndIndexRailSource).toContain("styles.groupComposerPanel");
    expect(routeAndIndexRailSource).toContain("styles.groupAgentPicker");
    expect(routeAndIndexRailSource).toContain("styles.createGroupButton");
    expect(routeAndIndexRailSource).toContain("styles.systemEntryGroup");
    expect(routeAndIndexRailSource).toContain("styles.systemEntryButton");

    expect(routeStyles.sessionActionRow).toBeTypeOf("string");
    expect(routeStyles.newGroupButton).toBeTypeOf("string");
    expect(routeStyles.sessionActionRow).not.toContain("grid-cols-[auto_auto]");
    expect(routeStyles.newSessionButton).toContain("!h-[34px]");
    expect(routeStyles.newSessionButton).toContain("!min-h-[34px]");
    expect(routeStyles.newSessionButton).toContain("!w-full");
    expect(routeStyles.newGroupButton).toContain("!h-[34px]");
    expect(routeStyles.newGroupButton).toContain("!min-h-[34px]");
    expect(routeStyles.newGroupButton).toContain("!w-full");
    expect(routeStyles.systemEntryGroup).toBeTypeOf("string");
    expect(routeStyles.systemEntryButton).toBeTypeOf("string");
    expect(routeStyles.systemEntryIcon).toBeTypeOf("string");
    expect(routeStyles.groupComposerPanel).toBeTypeOf("string");
    expect(routeStyles.groupAgentOption).toBeTypeOf("string");
    expect(routeStyles.createGroupButton).toBeTypeOf("string");
  });

  it("keeps Agent rebinding out of chat while allowing new sessions for the selected Agent", () => {
    expect(routeAndLifecycleSource).toContain("const createSessionMutation");
    expect(chatApiSource).toContain('fetchJson<SessionDetail>("/api/sessions"');
    expect(chatApiSource).toContain('Prefer: "respond-async"');
    expect(routeAndLifecycleSource).toContain("createChatSession({ agentId })");
    expect(routeAndLifecycleSource).toContain("mergeSessionDetailIntoSummaries");
    expect(routeAndLifecycleSource).toContain("updateAgentSessionSummaryCaches");
    expect(routeAndLifecycleSource).toContain("pinSessionCreatePreserve");
    expect(routeAndLifecycleSource).toContain("createTempSessionId()");
    expect(routeAndLifecycleSource).toContain("Seed real id cache BEFORE the route swaps");
    expect(routeAndLifecycleSource).toContain("fetchSessionDetailWindow(nextId");
    expect(routeAndLifecycleSource).toContain("includeSecondary: false");
    // Create must not broad-invalidate ["sessions"] (bootstrap/index race wipes the new tab).
    expect(routeAndLifecycleSource).not.toContain("void chatWorkspaceCache.afterSessionChanged({\n        sessionId: nextId");
    expect(routeSource).toContain("resolveActiveSessionDetailForUi");
    expect(routeSource).toContain("isSessionDetailHardLoading");
    expect(routeSource).toContain("mergePreservedCreatedSessions");
    expect(routeAndActionsSource).toContain("createSessionMutation.mutate({ agentId: selectedChatAgentId })");
    const createMutationSource = routeAndLifecycleSource.slice(
      routeAndLifecycleSource.indexOf("const createSessionMutation"),
      routeAndLifecycleSource.indexOf("const createGroupRoomMutation"),
    );
    expect(createMutationSource).toContain("void queryClient.cancelQueries({ queryKey: [\"sessions\", \"query\"] })");
    expect(createMutationSource).not.toContain("await Promise.all([\n        queryClient.cancelQueries({ queryKey: [\"sessions\", \"query\"] })");
    expect(routeSource).not.toContain("updateSessionAgentMutation");
    expect(routeSource).not.toContain("sessionAgentOptions");
    expect(routeSource).not.toContain("handleAgentTemplateChange");
    expect(routeSource).not.toContain("agentBindingSavePending");
    expect(routeSource).not.toContain("styles.sessionAgentStatusControl");
    expect(routeSource).not.toContain("styles.sessionAgentStatusSelect");
    expect(routeSource).not.toContain("styles.agentTemplatePanel");
    expect(routeSource).not.toContain("fetchJson<SessionAgentTemplate[]>");
    expect(routeSource).not.toContain("body: JSON.stringify({ agentProfileId })");
    expect(routeCssSource).not.toContain(".sessionAgentStatusControl");
    expect(routeCssSource).not.toContain(".sessionAgentStatusSelect");
    expect(routeCssSource).not.toContain(".sessionAgentStatusMeta");
  });

  it("opens group conversations inside the chat page instead of navigating away", () => {
    expect(routeSource).toContain("activeGroupRoomId");
    expect(routeSource).toContain("handleOpenGroupRoom");
    expect(routeSource).toContain('new URLSearchParams(location.search).get("room")');
    expect(routeSource).toContain("chatRouteSelection.kind === \"room\" || chatRouteSelection.kind === \"project_bus\"");
    expect(routeAndActionsSource).toContain("chatRoute.openRoom(roomId)");
    expect(routeAndSelectionSource).toContain("setRightPaneCollapsed(false)");
    expect(routeAndIndexRailSource).toContain("chatRoomModeLabel(mode, lang)");
    expect(routeAndIndexRailSource).toContain("chatRoomPurposeLabel(purpose, lang)");
    expect(routeSource).toContain("queryKeys.chatRoomPurposes()");
    expect(routeSource).toContain("listChatRoomPurposes()");
    expect(chatApiSource).toContain("/api/chat-rooms/purposes");
    expect(routeAndHelpersSource).toContain("抢占式讨论");
    expect(routeAndHelpersSource).toContain("协同问诊会诊");
    expect(routeAndHelpersSource).toContain("医疗分诊建议");
    expect(routeAndHelpersSource).toContain("medical_consultation_panel");
    expect(routeAndHelpersSource).toContain("medical_triage");
    expect(routeAndIndexRailSource).toContain("对话目的");
    expect(routeAndActionsSource).toContain("purpose: groupPurposeDraft || \"discussion\"");
    expect(routeAndActionsSource).toContain("purpose: activeGroupRoom?.purpose || \"discussion\"");
    expect(routeAndActionsSource).toContain("purpose: groupManagePurposeDraft || \"discussion\"");
    expect(routeSource).toContain("fetchChatRoomDetail(activeGroupRoomId)");
    expect(chatApiSource).toContain("`/api/chat-rooms/${encodeURIComponent(roomId)}`");
    expect(routeAndStreamSource).toContain("consumeChatRoomEventStream");
    expect(routeAndStreamSource).toContain("fetchWithControl(chatRoomEventsUrl(options.roomId)");
    expect(routeAndStreamSource).not.toContain("new EventSource(`/api/chat-rooms/");
    expect(routeAndStreamSource).toContain("scheduleChatRoomDetail(payload.detail)");
    expect(routeAndStreamSource).toContain("browser.chat_room_stream.closed");
    expect(routeSource).toContain("useGroupRoomStream");
    expect(routeSource).toContain("handleStartGroupRound");
    expect(routeAndLifecycleSource).toContain("startChatRoomRound(roomId, { topic, mode, purpose }, { preferAsync: true })");
    expect(chatApiSource).toContain("headers.Prefer = \"respond-async\"");
    expect(routeAndLifecycleSource).toContain("chatWorkspaceCache.afterGroupRoundStarted(accepted.roomId)");
    expect(routeSource).toContain("stopGroupRoundMutation");
    expect(routeAndLifecycleSource).toContain("stopChatRoomRound(roomId)");
    expect(chatApiSource).toContain("`/api/chat-rooms/${encodeURIComponent(roomId)}/stop`");
    expect(routeSource).toContain("handleStopGroupRound");
    expect(routeSource).toContain("groupRoundStopping");
    expect(routeSource).toContain("groupRoundActive");
    expect(routeSource).toContain("sendProjectBusMessageMutation");
    expect(routeSource).toContain("updateGroupRoomMutation");
    expect(routeSource).toContain("deleteGroupRoomMutation");
    expect(routeSource).toContain("const activeGroupTeamOwned = Boolean(activeGroupTeam)");
    expect(routeSource).toContain("|| activeGroupTeamOwned");
    expect(routeAndActionsSource).toContain("if (!sessionId || activeGroupTeamOwned || groupRoundActive || updateGroupRoomMutation.isPending)");
    expect(routeSource).toContain("composerLeadingControl={standardGroupRoomActive && activeGroupRoom ? (");
    expect(routeSource).toContain("onManage: () => setGroupManageDialogOpen(true)");
    expect(chatComposerPlusMenuSource).toContain('id: "manage-group"');
    expect(chatComposerPlusMenuSource).toContain('id: "open-team"');
    expect(chatComposerPlusMenuSource).toContain('label: lang === "zh" ? "打开团队" : "Open team"');
    expect(chatGroupManagementDialogSource).toContain("团队关联群聊由团队页维护成员与角色");
    expect(chatGroupManagementDialogSource).toContain("onClick={() => onOpenTeam(activeGroupTeam.teamId)}");
    expect(chatGroupManagementDialogSource).toContain("disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomPending}");
    expect(routeSource).toContain("groupManageTitleDraft");
    expect(routeAndActionsSource).toContain("title: groupManageTitleDraft.trim()");
    expect(routeSource).toContain("groupManagePurposeDraft");
    expect(routeAndLifecycleSource).toContain("participantSessionIds: sessionIds");
    expect(routeAndActionsSource).toContain("groupManageSessionIds");
    expect(routeAndLifecycleSource).toContain("setGroupManageSessionIds((current) => current.filter((sessionId) => sessionId !== variables.sessionId))");
    expect(routeSource).toContain("<ChatGroupManagementDialog");
    expect(chatStatusRailSource).not.toContain("styles.groupManagementPanel");
    expect(routeAndGroupCenterSource).toContain("styles.groupConversationFrame");
    expect(routeSource).toContain("compactAgentRoleLabel");
    expect(routeAndGroupPresentationSource).toContain("shouldCollapseGroupMessage");
    expect(routeAndGroupPresentationSource).toContain("shouldDefaultCollapseGroupMessage");
    expect(routeAndHelpersSource).toContain("message.audience === \"internal\"");
    expect(routeAndGroupPresentationSource).not.toContain("展开讨论");
    expect(routeSource).toContain("expandedGroupMessageIds");
    expect(routeAndGroupPresentationSource).toContain("stripGroupSpeakerPrefix(message, identityName)");
    expect(routeAndGroupCenterSource).toContain("<ChatGroupMessageBody");
    expect(routeAndGroupCenterSource).toContain("identityName={speakerIdentity.name}");
    expect(routeAndGroupCenterSource).toContain("title={speakerIdentity.fullIdentityLabel}");
    expect(routeAndGroupCenterSource).toContain("data-testid=\"group-stream-identity\"");
    expect(routeAndGroupCenterSource).toContain("groupConsecutiveBy");
    expect(routeAndGroupPresentationSource).toContain("展开全文");
    expect(routeAndGroupPresentationSource).toContain("收起");
    expect(routeAndGroupCenterSource).toContain("message.status !== \"completed\" ? <span>{statusLabel(message.status)}</span> : null");
    expect(routeSource).toContain("<ChatGroupCenterSurface");
    expect(routeAndHelpersSource).toContain("numericTail.slice(-2)");
    expect(routeSource).not.toContain("navigate(`/chat-rooms");
    expect(routeStyles.leftRail).toContain("[grid-column:5]");
    expect(chatStatusRailSource).toContain("这里仅展示当前群聊资料");
    expect(routeSource.indexOf("<ChatStatusRail")).toBeGreaterThan(-1);

    expect(routeStyles.groupConversationFrame).toBeTypeOf("string");
    expect(chatGroupManagementDialogStyles.dialogContent).toBeTypeOf("string");
    expect(chatGroupManagementDialogStyles.titleField).toBeTypeOf("string");
    expect(chatGroupManagementDialogStyles.memberPicker).toBeTypeOf("string");
    expect(chatGroupManagementDialogStyles.memberChip).toBeTypeOf("string");
    expect(routeStyles.groupMessageTimeline).toBeTypeOf("string");
    expect(routeStyles.groupRoundBlock).toBeTypeOf("string");
    expect(routeStyles.groupRoundDivider).toBeTypeOf("string");
    expect(routeStyles.groupTopicBubble).toBeTypeOf("string");
    expect(routeStyles.groupBubbleRow).toBeTypeOf("string");
    expect(routeStyles.groupBubbleAvatar).toBeTypeOf("string");
    expect(routeStyles.groupBubble).toBeTypeOf("string");
    expect(routeStyles.groupBubbleBodyCollapsed).toBeTypeOf("string");
    expect(routeStyles.groupBubbleBodyCollapsed).toContain("[-webkit-line-clamp:8]");
    expect(routeStyles.groupBubbleBodyCollapsed).not.toMatch(/(?:^|\s)hidden(?:\s|$)/);
    expect(routeStyles.groupStreamIdentity).toContain("flex");
    expect(routeStyles.groupStreamIdentity).toContain("items-center");
    expect(routeStyles.groupBubbleRow).not.toContain("!bg-vui-surface-row");
    expect(routeStyles.groupBubbleToggle).toBeTypeOf("string");
    expect(routeStyles.groupTypingDots).toBeTypeOf("string");
    expect(routeStyles.groupComposerBar).toBeTypeOf("string");
  });

  it("keeps restored ChatCodingRoute grids from the CSS module migration", () => {
    const restoredGridExpectations: Array<[string, string, boolean?]> = [
      [routeStyles.inlineMetaPill, "grid-cols-[minmax(4.5rem,auto)_minmax(0,1fr)]", false],
      [routeStyles.inlineMetaList, "grid-cols-1", false],
      [routeStyles.sessionBindingNotice, "grid-cols-[minmax(0,1fr)_auto]"],
      [routeStyles.activeSkillStatus, "grid-cols-[minmax(0,1fr)]"],
      [routeStyles.agentIndexHeader, "grid-cols-[18px_minmax(0,1fr)_fit-content(72px)]"],
      [routeStyles.agentIndexOpenButton, "grid-cols-[30px_minmax(0,1fr)]"],
      [routeStyles.resourceSplit, "grid-cols-[repeat(auto-fit,minmax(118px,1fr))]"],
      [routeStyles.inlineStatGrid, "grid-cols-1", false],
      [routeStyles.inlineStat, "grid-cols-[minmax(4.5rem,auto)_minmax(0,1fr)]", false],
      [routeStyles.petShowcaseActions, "grid-cols-3", false],
      [routeStyles.cliAgentTerminalCommand, "grid-cols-[auto_minmax(0,1fr)_auto]"],
      [chatRuntimeNoticeStackStyles.notice, "grid-cols-[16px_minmax(0,1fr)]"],
      [chatToolApprovalDialogStyles.dialog, "grid-cols-[22px_minmax(0,1fr)_auto]"],
      [routeStyles.cacheDetailCalibrationNote, "gap-1"],
      [routeStyles.rightIndexTabs, "grid-cols-[repeat(2,minmax(0,1fr))]"],
      [routeStyles.memberIndexSummary, "grid-cols-[auto_minmax(0,1fr)_auto]"],
      [routeStyles.groupAgentOption, "grid-cols-[auto_28px_minmax(0,1fr)]"],
      [routeStyles.conversationTreeRootHeader, "grid-cols-[minmax(0,1fr)_auto]"],
      [routeStyles.groupManagementActions, "grid-cols-[repeat(2,minmax(0,1fr))]"],
      [routeStyles.groupManagementControls, "grid-cols-[minmax(0,1fr)_auto]"],
      [routeStyles.groupMemberChip, "grid-cols-[18px_26px_minmax(0,1fr)_auto]"],
      [routeStyles.groupComposerBar, "grid-cols-[minmax(0,1fr)_auto_auto]"],
    ];

    for (const [className, gridTemplate, requireImportantGrid = true] of restoredGridExpectations) {
      if (requireImportantGrid) {
        expect(className).toContain("!grid");
      } else {
        expect(className).toMatch(/(?:^|\s)(?:!)?grid(?:\s|$)/);
      }
      expect(className).toContain(gridTemplate);
    }

    expect(routeStyles.systemEntryTitleRow).toContain("!flex");
    expect(routeStyles.systemEntryTitleRow).not.toContain("grid-cols-");
  });

  it("keeps team group chat panels readable after the style-map bake", () => {
    expect(routeStyles.groupConversationFrame).toContain("grid");
    expect(routeStyles.groupConversationFrame).toContain("grid-rows-[auto_minmax(0,1fr)_auto]");
    expect(routeStyles.groupConversationFrame).toContain("h-full");
    expect(routeStyles.groupConversationFrame).toContain("overflow-hidden");
    expect(routeStyles.groupConversationFrame).toContain("rounded-[var(--radius-panel)]");

    expect(routeStyles.groupConversationHeader).toContain("!grid");
    expect(routeStyles.groupConversationHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(routeStyles.groupConversationHeader).toContain("[&_h2]:truncate");

    expect(routeStyles.groupMessageTimeline).toContain("min-h-0");
    expect(routeStyles.groupMessageTimeline).toContain("overflow-auto");
    expect(routeStyles.groupMessageTimeline).toContain("p-2");
    expect(routeStyles.groupEmptyState).toContain("grid");
    expect(routeStyles.groupEmptyState).toContain("place-items-center");
    expect(routeStyles.groupEmptyState).toContain("min-h-[min(220px,calc(100dvh_-_260px))]");
    expect(routeStyles.groupEmptyState).not.toContain("min-h-[min(420px,calc(100dvh_-_220px))]");

    expect(chatGroupManagementDialogStyles.memberPicker).toContain("grid");
    expect(chatGroupManagementDialogStyles.memberPicker).toContain("gap-1.5");
    // Wave 6G: group member picker height is shared PaneHeight, not fixed max-h.
    expect(chatGroupManagementDialogStyles.memberPicker).not.toContain("max-h-[min(40dvh,360px)]");
    expect(chatGroupManagementDialogSource).toContain("PersistedHeightListShell");
    expect(chatGroupManagementDialogSource).toContain("CHAT_GROUP_MEMBER_PICKER_HEIGHT_PANE");
    expect(chatGroupManagementDialogStyles.memberChip).toContain("!w-full");
    expect(chatGroupManagementDialogStyles.memberChip).not.toContain("w-fit");
    expect(chatGroupManagementDialogStyles.memberCopy).toContain("grid");
    expect(chatGroupManagementDialogStyles.memberCopy).toContain("overflow-hidden");
    expect(chatGroupManagementDialogStyles.memberCopy).toContain("[&_strong]:truncate");
    expect(chatGroupManagementDialogStyles.memberCopy).toContain("[&_small]:truncate");

    expect(routeStyles.agentIndexHeader).toContain("grid-cols-[18px_minmax(0,1fr)_fit-content(72px)]");
    expect(routeStyles.agentIndexOpenButton).toContain("!w-full");
    expect(routeStyles.agentIndexOpenButton).not.toContain("w-fit");
    expect(routeStyles.agentIndexOpenButton).toContain("[&_[data-slot=vui-button-content]]:contents");
    expect(routeStyles.agentIndexOpenButton).toContain("[&_[data-slot=vui-button-label]]:contents");
    expect(routeStyles.agentIndexCopy).toContain("grid");
    expect(routeStyles.agentIndexCopy).toContain("overflow-hidden");
    expect(routeStyles.agentIndexNameLine).toContain("!flex");
    expect(routeStyles.agentIndexNameLine).toContain("[&_span]:truncate");
    expect(routeStyles.agentModelLine).toContain("truncate");
    expect(routeStyles.agentIndexStatus).toContain("whitespace-nowrap");
  });

  it("uses the group surface as a project Agent bus observation and @ guidance entry", () => {
    expect(routeSource).toContain("handleOpenProjectAgentBus");
    expect(routeAndActionsSource).toContain("chatRoute.openProjectBus()");
    expect(routeAndActionsSource).not.toContain("setActiveGroupRoomId");
    expect(routeSource).toContain("queryKeys.projectAgentBus()");
    expect(routeSource).toContain("queryFn: ({ signal }) => listProjectAgentBusTimeline(undefined, { signal })");
    expect(routeAndLifecycleSource).toContain("sendProjectAgentBusMessage({ content, interruptTargets })");
    expect(routeAndLifecycleSource).toContain("revokeProjectAgentBusMessage({");
    expect(routeAndGroupCenterSource).toContain("isProjectAgentBusEventRevoked(event)");
    expect(routeAndGroupCenterSource).toContain("kernelTaskCenterHref");
    expect(routeAndGroupCenterSource).toContain("event.kernel?.taskId");
    expect(routeAndGroupCenterSource).toContain("onRevokeProjectBusMessage(event.eventId)");
    expect(routeSource).toContain("projectBusInterruptTargets");
    expect(routeAndGroupCenterSource).toContain("助手通知流");
    expect(routeAndGroupCenterSource).toContain("它不是团队群聊");
    expect(routeAndSessionSurfaceSource).toContain("全局广播/私信投递记录");
    expect(routeAndGroupCenterSource).toContain("不带 @ 默认投递全体");
    expect(routeAndGroupCenterSource).toContain("打断目标助手");
    expect(routeSource).toContain("buildChatMentionTargets(archiveVisibleAgents)");
    expect(routeAndGroupPresentationSource).toContain("tokenizeChatMentions(text, mentionTargets)");
    expect(routeAndGroupPresentationSource).toContain("onOpenMentionTarget(segment.target)");
    expect(routeAndGroupCenterSource).toContain("styles.projectBusEvent");
    expect(routeAndGroupCenterSource).toContain("styles.projectBusEventRevoked");
    expect(routeAndGroupCenterSource).toContain("styles.projectBusEventActions");
    expect(routeAndGroupPresentationSource).toContain("styles.agentMention");
    expect(routeAndGroupCenterSource).toContain("styles.projectBusInterruptToggle");

    expect(routeStyles.projectBusEvent).toBeTypeOf("string");
    expect(routeStyles.projectBusEventRevoked).toBeTypeOf("string");
    expect(routeStyles.projectBusEventHeader).toBeTypeOf("string");
    expect(routeStyles.projectBusEventActions).toBeTypeOf("string");
    expect(routeStyles.projectBusEventBody).toBeTypeOf("string");
    expect(routeStyles.agentMention).toBeTypeOf("string");
    expect(routeStyles.projectBusEventMeta).toBeTypeOf("string");
    expect(routeStyles.kernelTraceLink).toBeTypeOf("string");
    expect(routeStyles.projectBusInterruptToggle).toBeTypeOf("string");
  });

  it("logs direct session stream close events for lifecycle diagnosis", () => {
    expect(routeAndStreamSource).toContain("browser.session_stream.opened");
    expect(routeAndStreamSource).toContain("browser.session_stream.closed");
    expect(routeAndStreamSource).toContain("readyStateBeforeClose");
    expect(routeAndStreamSource).toContain("stream.close()");
  });

  it("coalesces high-frequency direct session stream snapshots before updating UI cache", () => {
    expect(routeAndStreamSource).toContain("const SESSION_STREAM_MIN_APPLY_INTERVAL_MS = 350");
    expect(routeSource).toContain("const nextDetail = mergeSessionDetailMessageWindow(previous, detail)");
    expect(routeSource).toContain("sessionDetailSnapshotKey(previous) === sessionDetailSnapshotKey(nextDetail)");
    // snapshot helper lives in chatSessionDetailHelpers
    expect(routeAndStreamSource).toContain("setActiveTurnLayerForSession(current, streamSessionId, undefined)");
    expect(routeAndStreamSource).toContain("let pendingDetail: SessionDetail | null = null");
    expect(routeAndStreamSource).toContain("let pendingDetailTrace: SessionStreamProtocolTrace | null = null");
    expect(routeAndStreamSource).toContain("function queueSessionDetail(detail: SessionDetail, trace: SessionStreamProtocolTrace)");
    expect(routeAndStreamSource).toContain("browser.session_stream.snapshot_queued");
    expect(routeAndStreamSource).toContain("browser.session_stream.snapshot_applied");
    expect(routeAndStreamSource).toContain("queueSessionDetail(routed.payload.detail, routed.trace)");
    expect(routeAndStreamSource).toContain("sessionStreamProtocolTelemetryFields(trace)");
  });

  it("applies lightweight assistant delta stream events on browser frames without timer coalescing", () => {
    expect(routeAndStreamSource).not.toContain("SESSION_ASSISTANT_DELTA_MIN_APPLY_INTERVAL_MS");
    expect(routeAndStreamSource).not.toContain("SESSION_ASSISTANT_DELTA_IMMEDIATE_FLUSH_CHARS");
    expect(routeSource).toContain("activeTurnLayersBySession");
    expect(routeSource).toContain("activeTurnLayersBySessionRef");
    expect(routeSource).toContain("Record<string, ActiveTurnLayerState>");
    expect(routeAndStreamSource).toContain("planAppliedAssistantDeltaDrain({");
    expect(routeAndStreamSource).toContain("committedLayer: committedAssistantDeltaLayer");
    expect(routeAndStreamSource).toContain("setActiveTurnLayerForSession(current, streamSessionId, decision.nextCommittedLayer)");
    expect(chatStreamApplyControllerSource).toContain("mergeAssistantDeltaIntoActiveTurnLayer(pendingLayer, entry.payload)");
    expect(routeAndStreamSource).toContain("isActiveTurnSettledByDetail(activeLayer, detail)");
    expect(routeSource).toContain("activeTurnMessage,");
    expect(routeAndHelpersSource).toContain("function isStaleLedgerUpdate(currentSeq: unknown, incomingSeq: unknown)");
    expect(routeAndStreamSource).not.toContain("function mergeLiveAssistantMessagesIntoSessionDetail(");
    expect(routeAndStreamSource).not.toContain("kind: \"session_live_overlay\"");
    expect(routeAndStreamSource).toContain("committedAssistantDeltaLayer = decision.nextCommittedLayer");
    expect(routeAndStreamSource).toContain("if (decision.shouldCommitRender)");
    expect(chatStreamApplyControllerSource).toContain("pendingTextLength: activeTurnLayerTextLength(input.pendingLayer)");
    expect(routeAndStreamSource).toContain("createSessionAssistantDeltaScheduler");
    expect(routeAndStreamSource).toContain("const assistantDeltaScheduler = createSessionAssistantDeltaScheduler({");
    expect(routeAndStreamSource).toContain("nowMs: chatStreamPerformanceNowMs");
    expect(routeAndStreamSource).toContain("let frameScheduledAtMs = 0");
    expect(routeAndStreamSource).toContain("let assistantDeltaApplyFrame: number | null = null");
    expect(routeAndStreamSource).toContain("function applyPendingAssistantDeltas(reason: \"frame\" | \"close\" | \"final\")");
    expect(routeAndStreamSource).toContain("assistantDeltaScheduler.drain(reason, { frameScheduledAtMs: scheduledAtMs })");
    expect(chatStreamApplyControllerSource).toContain("for (const entry of input.drain.entries)");
    expect(routeAndStreamSource).toContain("function scheduleAssistantDeltaFrame()");
    expect(routeAndStreamSource).toContain("window.requestAnimationFrame");
    expect(routeAndStreamSource).toContain("window.cancelAnimationFrame");
    expect(routeAndStreamSource).toContain("function queueAssistantDelta(");
    expect(routeAndStreamSource).toContain("assistantDeltaScheduler.enqueue(payload, trace.payloadLength, trace)");
    expect(routeAndStreamSource).toContain("const applyStartedAtMs = chatStreamPerformanceNowMs()");
    expect(routeAndStreamSource).toContain("applyPendingAssistantDeltas(\"final\")");
    expect(routeAndStreamSource).toContain("browser.session_stream.assistant_delta_frame_scheduled");
    expect(routeAndStreamSource).toContain("browser.session_stream.initial_received");
    expect(routeAndStreamSource).toContain("stream.addEventListener(\"session_initial\", handleSessionInitial as EventListener)");
    expect(routeAndStreamSource).toContain("stream.addEventListener(\"assistant_delta\", handleAssistantDelta as EventListener)");
    expect(routeAndStreamSource).toContain("stream.removeEventListener(\"session_initial\", handleSessionInitial as EventListener)");
    expect(routeAndStreamSource).toContain("stream.removeEventListener(\"assistant_delta\", handleAssistantDelta as EventListener)");
    expect(routeAndStreamSource).toContain("queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId) })");
    expect(routeAndStreamSource).toContain("const stream = new EventSource(`/api/sessions/${streamSessionId}/events?initial=none`)");
    expect(routeAndStreamSource).not.toContain("/events?initial=light");
    expect(routeAndStreamSource).not.toContain("let pendingAssistantDeltaDetail: SessionDetail | undefined");
    expect(routeAndStreamSource).not.toContain("pendingAssistantDeltaDetail = mergeAssistantDeltaIntoSessionDetail");
    expect(routeAndStreamSource).not.toContain("queryClient.setQueryData<SessionDetail>(queryKeys.session(streamSessionId)");
    expect(routeAndStreamSource).toContain("queueAssistantDelta(routed.payload, routed.trace)");
    expect(routeAndStreamSource).toContain("applyPendingAssistantDeltas(\"close\")");
    expect(routeAndStreamSource).toContain("browser.session_stream.assistant_delta_applied");
    expect(routeAndStreamSource).toContain("pendingTextLength");
    expect(chatStreamApplyControllerSource).toContain("turnRenderProtocol: input.drain.telemetry.turnRenderProtocol ?? \"\"");
    expect(routeAndStreamSource).toContain("routeSessionStreamEvent({");
    expect(routeAndStreamSource).toContain("sessionStreamProtocolTelemetryFields(routed.trace)");
    expect(routeAndStreamSource).toContain("batchSize");
    expect(chatStreamApplyControllerSource).toContain("drainMode: input.drain.mode");
    expect(chatStreamApplyControllerSource).toContain("pendingBefore: input.drain.pendingBefore");
    expect(chatStreamApplyControllerSource).toContain("pendingAfter: input.drain.pendingAfter");
    expect(chatStreamApplyControllerSource).toContain("oldestQueuedAgeMs");
    expect(chatStreamApplyControllerSource).toContain("oldestReceivedAtMs");
    expect(chatStreamApplyControllerSource).toContain("newestReceivedAtMs");
    expect(chatStreamApplyControllerSource).toContain("receivedToApplyMs");
    expect(chatStreamApplyControllerSource).toContain("queuedForMs");
    expect(chatStreamApplyControllerSource).toContain("frameLagMs");
    expect(chatStreamApplyControllerSource).toContain("applyElapsedMs");
    expect(routeAndStreamSource).not.toContain("pendingTextLength: String(projectedLayer?.content ?? \"\").length + String(projectedLayer?.thought ?? \"\").length");
    const queueAssistantDeltaStart = routeAndStreamSource.indexOf("function queueAssistantDelta(");
    const handleSessionInitialStart = routeAndStreamSource.indexOf("function handleSessionInitial", queueAssistantDeltaStart);
    const queueAssistantDeltaBody = routeAndStreamSource.slice(queueAssistantDeltaStart, handleSessionInitialStart);
    expect(queueAssistantDeltaBody).not.toContain("mergeAssistantDeltaIntoActiveTurnLayer");
    expect(queueAssistantDeltaBody).not.toContain("activeTurnLayerTextLength");
    expect(queueAssistantDeltaBody).not.toContain("pendingAssistantDeltaPayloads");
  });

  it("wires completed session stream events into the desktop notification helper", () => {
    const handleAssistantDeltaSection = sliceRequiredSection(
      routeAndStreamSource,
      "function handleAssistantDelta(event: MessageEvent<string>) {",
      "stream.addEventListener(\"session_initial\", handleSessionInitial as EventListener);",
    );
    expectOrderedFragments(handleAssistantDeltaSection, [
      "const routed = routeSessionStreamEvent({",
      "expectedType: \"assistant_delta\"",
      "if (!routed.accepted) {",
      "desktopConversationNotifierRef.current.handleAssistantDelta(routed.payload, {",
      "sessionTitle: sessionTitleForNotificationsRef.current || streamSessionId",
      "viewedSessionId: viewedSessionIdRef.current",
      "queueAssistantDelta(routed.payload, routed.trace);",
    ]);

    const applyPendingDetailSection = sliceRequiredSection(
      routeAndStreamSource,
      "function applyPendingDetail(reason: \"timer\" | \"close\" | \"final\") {",
      "function queueSessionDetail(detail: SessionDetail, trace: SessionStreamProtocolTrace) {",
    );
    expectOrderedFragments(applyPendingDetailSection, [
      "syncSessionDetail(detail);",
      "desktopConversationNotifierRef.current.handleSessionDetail(detail, {",
      "viewedSessionId: viewedSessionIdRef.current",
    ]);
    expect(routeSource).toContain("useDesktopConversationAttention({");
    expect(routeSource).toContain("sessions: allVisibleSessions");
    expect(routeSource).toContain("onOpenSession: handleOpenDirectSession");
  });

  it("records stream render-frame telemetry after ConversationView commits live text", () => {
    expect(routeSource).toContain("lastConversationStreamingFrameTelemetryAtRef");
    expect(routeSource).toContain("lastAssistantDeltaAppliedAtRef");
    expect(routeSource).toContain("const handleConversationStreamingFramePaint = useCallback");
    expect(routeSource).toContain("browser.conversation_stream.frame_painted");
    expect(routeSource).toContain("activeTurnLayersBySessionRef.current = activeTurnLayersBySession;");
    expect(routeSource).not.toContain([
      "useEffect(() => {",
      "    activeTurnLayersBySessionRef.current = activeTurnLayersBySession;",
      "  }, [activeTurnLayersBySession]);",
    ].join("\n"));
    expect(routeSource).toContain("const paintedActiveTurn = activeTurnLayersBySessionRef.current[sessionId]");
    expect(routeSource).toContain("turnId: paintedActiveTurn?.turnId ?? \"\"");
    expect(routeSource).toContain("paintedAtMs");
    expect(routeSource).toContain("lastAssistantDeltaAppliedAtMs");
    expect(routeSource).toContain("applyToPaintMs");
    expect(routeSource).toContain("selectFirstUnpaintedRunningTool");
    expect(routeSource).toContain("paintedRunningToolIdsBySessionRef");
    expect(routeSource).toContain("firstPaintedRunningToolAtBySessionRef");
    expect(routeSource).toContain("toolStartToFirstPaintMs");
    expect(routeSource).toContain("runningToolPaintKeys");
    expect(routeSource).toContain("newlyPaintedFallbackKeys");
    expect(routeSource).toContain("renderedTextLength");
    expect(routeSource).toContain("onStreamingFramePaint: handleConversationStreamingFramePaint");
  });

  it("refreshes directory projections once after an active turn reaches terminal state", () => {
    expect(routeSource).toContain("activeTurnTerminalRefreshKey");
    expect(routeSource).toContain("terminalIndexRefreshKeysBySessionRef");
    expect(routeSource).toContain("queryKeys.sessions()");
    expect(routeSource).toContain("queryKeys.conversations()");
    expect(routeSource).toContain("queryKeys.runtimeSummary()");
    expect(routeSource).toContain("queryClient.refetchQueries({");
    expect(routeSource).toContain("queryKey: queryKeys.session(activeSessionId)");
    expect(routeSource).toContain("const canonicalDetail = queryClient.getQueryData<SessionDetail>");
    expect(routeSource).toContain("mergeSessionDetailIntoSummaries(sessions, canonicalDetail)");
    expect(routeSource).toContain("reconcileAgentSessionDetailCache(queryClient, canonicalDetail)");
  });

  it("backs off index polling when detail streams own live queries", () => {
    expect(routeSource).toContain("const directSessionPanelActive = Boolean(activeSessionId) && !groupPanelActive");
    expect(routeSource).toContain("const sessionStreamAvailable = typeof EventSource !== \"undefined\"");
    expect(routeSource).toContain("resolveChatLiveQueryPolicy");
    expect(routeSource).toContain("const chatLiveQueryPolicyInput = {");
    expect(routeSource).toContain("sessionStreamShouldConnect,");
    expect(routeSource).toContain("directSessionPanelActive,");
    expect(routeSource).toContain("groupStreamShouldConnect,");
    expect(routeSource).toContain("standardGroupRoomActive,");
    expect(routeSource).not.toContain("legacyGroupRoomActive");
    expect(routeSource).toContain("const chatLiveQueryPolicy = resolveChatLiveQueryPolicy(chatLiveQueryPolicyInput)");
    expect(routeSource).toContain("const { groupStreamOwnsLiveQueries } = chatLiveQueryPolicy");
    expect(routeSource).toContain("refetchInterval: chatLiveQueryPolicy.sessionsRefetchInterval");
    expect(routeSource).toContain("refetchInterval: chatLiveQueryPolicy.conversationsRefetchInterval");
    expect(routeSource).toContain("? chatLiveQueryPolicy.sessionDetailRefetchInterval");
    expect(routeSource).toContain("startupDetailSettledSessionId === activeSessionId");
    expect(routeSource).toContain("refetchInterval: childSessionLiveQueryPolicy.childSessionsRefetchInterval");
    expect(routeSource).toContain("mergeSessionDetailIntoConversations(conversations, detail)");
  });

  it("does not refetch chat indexes or detail immediately after an accepted direct turn", () => {
    const submitMutationStart = routeAndComposerSource.indexOf("const submitTurnMutation = useMutation");
    const submitSuccessStart = routeAndComposerSource.indexOf("onSuccess: (acceptedTurn, variables, context)", submitMutationStart);
    const submitErrorStart = routeAndComposerSource.indexOf("onError: (error, variables, context)", submitSuccessStart);
    const submitSuccessBlock = routeAndComposerSource.slice(submitSuccessStart, submitErrorStart);

    expect(submitSuccessBlock).toContain("markOptimisticUserMessageAccepted");
    expect(submitSuccessBlock).not.toContain("invalidateQueries");
    expect(submitSuccessBlock).not.toContain("chatWorkspaceCache.refreshConversationIndex()");
    expect(submitSuccessBlock).not.toContain("chatWorkspaceCache.afterDirectTurnAccepted");
  });

  it("keeps active chat streams stable during direct session route switches", () => {
    const sessionStreamEffectSource = routeAndStreamSource.slice(
      routeAndStreamSource.indexOf("const stream = new EventSource(`/api/sessions/${streamSessionId}/events?initial=none`);"),
      routeAndStreamSource.length,
    );

    expect(routeAndStreamSource).toContain("const SESSION_STREAM_ROUTE_SWITCH_GRACE_MS = 4_000");
    expect(routeSource).toContain("directSessionBackgroundSyncActive");
    expect(routeSource).toContain("groupBackgroundSyncActive");
    expect(routeSource).toContain("sessionStreamRouteTargetMatches");
    expect(routeSource).toContain("sessionStreamRouteSettling");
    expect(routeSource).toContain("sessionStreamRouteSwitchGraceActive");
    expect(routeAndStreamSource).toContain("requestedSessionId !== activeSessionId");
    expect(routeSource).toContain("sessionStreamRouteTargetMatches");
    expect(routeSource).toContain("const chatStartupWarmupActive = useStartupWarmup(chatStartupDataReady)");
    expect(routeSource).toContain("const chatPollingVisible = pageVisible || chatStartupWarmupActive");
    expect(routeAndStreamSource).toContain("chatPollingVisible || options.routeSwitchGraceActive");
    expect(routeSource).not.toContain("pageVisible || directSessionBackgroundSyncActive || sessionStreamRouteSwitchGraceActive");
    expect(routeSource).toContain("&& (chatPollingVisible || groupBackgroundSyncActive)");
    expect(routeAndStreamSource).toContain("const shouldConnect = sessionStreamDecisionSnapshotRef.current.shouldConnect");
    expect(routeAndStreamSource).toContain("if (!shouldConnect || typeof EventSource === \"undefined\")");
    expect(routeSource).toContain("sessionStreamDecisionSnapshotRef");
    expect(sessionStreamEffectSource).not.toContain("sessionStreamShouldConnect,");
    expect(sessionStreamEffectSource).not.toContain("sessionStreamRouteSwitchGraceActive,");
    expect(sessionStreamEffectSource).not.toContain("chatStartupWarmupActive,");
    expect(sessionStreamEffectSource).not.toContain("directSessionBackgroundSyncActive,");
    expect(sessionStreamEffectSource).not.toContain("pageVisible,");
    expect(routeAndStreamSource).toContain("forceCloseStreamRef.current = forceCloseStream");
    expect(routeAndStreamSource).toContain("SESSION_STREAM_ROUTE_SWITCH_GRACE_MS");
    expect(routeAndStreamSource).toContain("if (!groupStreamShouldConnect || typeof AbortController === \"undefined\")");
    expect(routeSource).toContain("refetchIntervalInBackground: chatLiveQueryPolicy.directRefetchIntervalInBackground");
    expect(routeSource).toContain("refetchIntervalInBackground: chatLiveQueryPolicy.sharedRefetchIntervalInBackground");
    expect(routeSource).toContain("refetchIntervalInBackground: childSessionLiveQueryPolicy.directRefetchIntervalInBackground");
  });

  it("defers neighbor session prefetch until the visible active detail is ready and runs it serially", () => {
    const prefetchStart = routeSource.indexOf("// C: idle-prefetch a few neighbor session detail windows");
    const prefetchEffectStart = routeSource.indexOf("useEffect(() => {", prefetchStart);
    const prefetchEnd = routeSource.indexOf("\n  useEffect(() => {", prefetchEffectStart + 1);
    const prefetchSource = routeSource.slice(prefetchStart, prefetchEnd);

    expect(prefetchStart).toBeGreaterThanOrEqual(0);
    expect(prefetchEffectStart).toBeGreaterThan(prefetchStart);
    expect(prefetchSource).toContain("!secondaryChatDataEnabled");
    expect(prefetchSource).toContain("!pageVisible");
    expect(prefetchSource).toContain("const run = async () =>");
    expect(prefetchSource).toContain("await prefetchSessionDetailWindow(queryClient, sessionId)");
    expect(prefetchSource).not.toContain("void prefetchSessionDetailWindow(queryClient, sessionId)");
    expect(prefetchSource).toContain(
      "[activeSessionId, groupPanelActive, pageVisible, queryClient, secondaryChatDataEnabled, sessionsQuery.data]",
    );
  });

  it("opens direct sessions through the sole route controller with prefetch first", () => {
    const openDirectSessionSource = routeAndActionsSource.slice(
      routeAndActionsSource.indexOf("const handleOpenDirectSession = useCallback"),
      routeAndActionsSource.indexOf("const handleOpenAgent = useCallback"),
    );

    expect(openDirectSessionSource).toContain("prefetchSessionDetailWindow(queryClient, normalizedSessionId)");
    expect(openDirectSessionSource).toContain("chatRoute.openSession(normalizedSessionId, {");
    expect(openDirectSessionSource).not.toContain("setActiveSession");
    expect(openDirectSessionSource).not.toContain("navigate(`/chat?session=");
    // Prefetch happens before the route transition.
    expect(openDirectSessionSource.indexOf("prefetchSessionDetailWindow(queryClient, normalizedSessionId)"))
      .toBeLessThan(openDirectSessionSource.indexOf("chatRoute.openSession(normalizedSessionId, {"));
    expect(routeSource).toContain("resolveStickySessionDetailPaint");
    expect(routeSource).toContain("shouldShowStickyTranscriptPending");
  });

  it("logs direct session stream connect decisions with visibility inputs", () => {
    expect(routeAndStreamSource).toContain("browser.session_stream.effect_started");
    expect(routeAndStreamSource).toContain("browser.session_stream.skipped");
    expect(routeSource).toContain("chatStartupWarmupActive");
    expect(routeSource).toContain("chatPollingVisible");
    expect(routeSource).toContain("routeTargetMatches");
    expect(routeSource).toContain("routeSettling");
    expect(routeSource).toContain("routeSwitchGraceActive");
    expect(routeAndStreamSource).toContain("visibilityState: typeof document === \"undefined\" ? \"unknown\" : document.visibilityState");
  });

  it("logs chat route shell and startup readiness for switch-latency diagnosis", () => {
    expect(routeSource).toContain("chatRouteMountStartedAtRef");
    expect(routeSource).toContain("chatRouteShellMountedLoggedRef");
    expect(routeSource).toContain("chatRouteStartupReadyLoggedRef");
    expect(routeSource).toContain("chatRouteLongTaskCountRef");
    expect(routeSource).toContain("browser.chat_route.shell_mounted");
    expect(routeSource).toContain("browser.chat_route.startup_data_ready");
    expect(routeSource).toContain("browser.chat_route.long_task");
    expect(routeSource).toContain("chatRouteLongTaskCountRef.current >= 8");
    expect(routeSource).toContain("runtimeReady: Boolean(runtimeQuery.data)");
    expect(routeSource).toContain("sessionDetailReady: Boolean(activeSessionId ? sessionDetailQuery.data : true)");
    expect(chatWorkbenchCatalogQueriesSource).toContain("shareRuntimeSummaryIfOnlyVolatileChanged");
    expect(chatWorkbenchCatalogQueriesSource).toContain("structuralSharing: shareRuntimeSummaryIfOnlyVolatileChanged");
  });

  it("does not block chat startup readiness on secondary dashboard data", () => {
    expect(routeSource).toContain("if (sessionsQuery.data && directReady && groupReady)");
    expect(routeSource).not.toContain(
      "if (runtimeQuery.data && sessionsQuery.data && conversationsQuery.data && teamsQuery.data && directReady && groupReady)",
    );
  });

  it("defers secondary chat dashboard queries until the shell is ready", () => {
    expect(routeSource).toContain("const secondaryChatDataEnabled = chatStartupDataReady && (");
    expect(routeSource).toContain("startupDetailSettledSessionId === activeSessionId");
    expect(routeSource).toContain("sessionDetailQuery.isFetching");
    expect(routeSource).toContain("sessionDetailQuery.data.id !== activeSessionId");
    expect(routeSource).toContain("enabled: secondaryChatDataEnabled");
    expect(chatWorkbenchCatalogQueriesSource).toContain("bootstrapSettled &&");
    expect(chatWorkbenchCatalogQueriesSource).toContain(
      "(secondaryChatDataEnabled || sessionIndexQueryEnabled || groupComposerOpen || standardGroupRoomActive)",
    );
    expect(routeSource).not.toContain("enabled: groupComposerOpen || Boolean(activeSessionId)");
  });

  it("visually distinguishes direct sessions from group chats in the conversation list", () => {
    expect(routeSource).toContain("avatarInitials");
    expect(directSessionIndexItemSource).toContain("styles.conversationAvatarDirect");
    expect(groupSessionIndexItemsSource).toContain("styles.conversationAvatarGroup");
    expect(directSessionIndexItemSource).toContain("styles.directSessionItem");
    expect(groupSessionIndexItemsSource).toContain("styles.groupSessionItem");
    expect(routeAndActionsSource).toContain("chatRoute.openSession(normalizedSessionId, {");
    expect(directSessionIndexItemSource).not.toContain("styles.conversationKindBadgeDirect");
    expect(directSessionIndexItemSource).toContain("styles.conversationKindBadgeChild");
    expect(groupSessionIndexItemsStyles.conversationKindBadgeGroup).toBeTypeOf("string");
    expect(groupSessionIndexItemsSource).toContain("styles.teamConversationMetaRow");

    expect(routeStyles.conversationAvatar).toBeTypeOf("string");
    expect(routeStyles.conversationAvatarDirect).toBeTypeOf("string");
    expect(routeStyles.conversationAvatarGroup).toBeTypeOf("string");
    expect(routeStyles.conversationTitleRow).toBeTypeOf("string");
    expect(routeStyles.conversationMetaRow).toBeTypeOf("string");
    expect(routeStyles.conversationMetaMain).toBeTypeOf("string");
    expect(routeStyles.conversationMetaTime).toBeTypeOf("string");
    expect(routeStyles.directSessionItem).toBeTypeOf("string");
    expect(routeStyles.groupSessionItem).toBeTypeOf("string");
    expect(routeStyles.sessionStatusCluster).toBeTypeOf("string");
    expect(routeStyles.sessionCurrentBadge).toBeTypeOf("string");
    expect(routeStyles.sessionRunningBadge).toBeTypeOf("string");
    expect(routeStyles.sessionUnreadBadge).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadge).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadgeDirect).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadgeChild).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadgeGroup).toBeTypeOf("string");
  });

  it("keeps direct session model metadata and timestamps from clipping each other", () => {
    expect(directSessionIndexItemSource).toContain("styles.conversationMetaMain");
    expect(directSessionIndexItemSource).toContain("styles.conversationMetaTime");
    expect(directSessionIndexItemSource).toContain("styles.sessionStatusCluster");
    expect(directSessionIndexItemSource).toContain("styles.sessionActivityRunning");
    expect(directSessionIndexItemSource).toContain("styles.sessionActivityCompleted");
    expect(routeStyles.conversationTitleRow).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(routeStyles.conversationTitleRow).toContain("max-w-full");
    expect(routeStyles.conversationMetaRow).toContain("grid-cols-[minmax(0,1fr)_max-content]");
    expect(routeStyles.conversationMetaTime).toContain("max-w-[112px]");
    expect(routeStyles.conversationMetaTime).toContain("[&_time]:flex-none");
    expect(routeStyles.conversationMetaTime).toContain("[&_time]:overflow-visible");
    expect(routeStyles.conversationMetaTime).toContain("[&_time]:text-clip");
    expect(routeCssSource).not.toContain("max-width: 104px");
    expect(directSessionIndexItemSource).not.toContain("styles.sessionCurrentIndicator");
  });

  it("keeps conversation index item skeletons compact instead of nested row cards", () => {
    for (const skeletonClass of [
      routeStyles.sessionItemMain,
      routeStyles.conversationTitleRow,
      routeStyles.conversationMetaRow,
    ]) {
      expect(skeletonClass).not.toMatch(/bg-vui-surface-row|bg-\[var\(--vui-surface-row\)\]/);
      expect(skeletonClass).not.toMatch(/border border-vui-border-subtle|border border-\[var\(--vui-border-subtle\)\]/);
      expect(skeletonClass).not.toContain("rounded-[var(--radius-control)]");
    }

    expect(routeStyles.sessionItem).toContain("grid-cols-[minmax(0,1fr)]");
    expect(routeStyles.sessionItem).toContain("overflow-hidden");
    // Wave 8D: avatar column is 32px on DirectSessionIndexItem map.
    expect(routeStyles.sessionItemMain).toContain("grid-cols-[32px_minmax(0,1fr)]");
    expect(routeStyles.sessionItemMain).not.toContain("data-slot=vui-button-content");
    expect(routeStyles.sessionItemMain).not.toContain("data-slot=vui-button-label");
    expect(routeStyles.conversationGroupHeader).not.toContain("data-slot=vui-button-content");
    expect(routeStyles.conversationGroupHeader).not.toContain("data-slot=vui-button-label");
    expect(routeStyles.conversationCopy).toContain("overflow-hidden");
    expect(routeStyles.conversationTitleMain).toContain("overflow-hidden");
    expect(routeStyles.sessionItemTitle).toContain("truncate");
    expect(routeStyles.sessionStatusCluster).not.toContain("rounded-full");
    expect(routeStyles.sessionStatusCluster).toContain("justify-end");
    expect(routeStyles.agentModelTag).toContain("max-w-[96px]");
    expect(routeStyles.agentModelTag).toContain("[&_span]:truncate");
  });

  it("renders structural index and workspace shells while conversation data loads", () => {
    expect(routeAndIndexRailSource).toContain("ConversationIndexLoadingShell");
    expect(routeSource).toContain("const conversationIndexLoading = shouldShowConversationIndexLoading");
    expect(routeSource).toContain("bootstrapIsLoading: activeSessionBootstrapQuery.isLoading");
    expect(routeSource).toContain("conversationsIsLoading: conversationsQuery.isLoading");
    expect(routeSource).toContain("sessionsIsLoading: sessionsQuery.isLoading");
    expect(routeSource).toContain("ChatConversationIndexPanelContent");
    expect(routeSource).toContain("conversationIndexLoading={conversationIndexLoading}");
    expect(chatConversationIndexPanelContentSource).toContain(
      "<ConversationIndexLoadingShell label={loadingLabel} />",
    );
    expect(chatSessionWorkspacePanelSource).toContain("ConversationWorkspaceLoadingShell");
    expect(chatSessionWorkspacePanelSource).not.toContain("skeletonLines={2}");
  });

  it("renders the conversation index as one soft panel with flat rows and compact actions", () => {
    expect(routeStyles.rightPane).toContain("rounded-none");
    expect(routeStyles.rightPane).toContain("border-r");
    expect(routeStyles.rightPane).toMatch(/bg-vui-surface-rail|bg-\[var\(--vui-surface-rail\)\]/);
    expect(routeStyles.rightPane).toContain("shadow-none");
    expect(routeStyles.panelState).toContain("!content-center");
    expect(routeStyles.panelState).toContain("!text-center");
    expect(routeStyles.panelState).not.toContain("border");
    expect(routeStyles.panelState).not.toContain("bg-");
    expect(routeStyles.panelState).not.toContain("shadow");
    expect(routeStyles.sessionActionRow).toContain("grid-cols-2");
    expect(routeStyles.newSessionButton).toContain("!w-full");
    expect(routeStyles.panelSearchInput).toContain("w-full");
    expect(directSessionIndexItemStyles.sessionItem).not.toContain("shadow-[var(--vui-elevation-panel)]");
  });

  it("moves direct session actions into a right-click context menu", () => {
    expect(routeAndRenameMenuSource).toContain("type SessionContextMenuState");
    expect(routeSource).toContain("const [sessionContextMenu, setSessionContextMenu]");
    expect(routeSource).toContain("const contextMenuSessionId = sessionContextMenu?.sessionId ?? \"\"");
    expect(routeAndRenameMenuSource).toContain("const openSessionContextMenu = useCallback");
    expect(routeSource).toContain("onContextMenu={openSessionContextMenu}");
    expect(routeSource).toContain("contextMenuSessionId={contextMenuSessionId}");
    expect(conversationIndexTreeSource).toContain("contextMenuSessionId");
    expect(directSessionIndexListSource).toContain("contextMenuActive={contextMenuSessionId === session.id}");
    expect(directSessionIndexItemSource).toContain("styles.sessionItemContextTarget");
    expect(agentSessionTabStripSource).toContain("contextMenuSessionId");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabContextTarget");
    expect(agentSessionTabStripSource).toContain("onContextMenu={(event) => onContextMenu(event, session)}");
    expect(routeSource).toContain("contextMenuSession");
    expect(routeSource).toContain("agentCenterConfigRoute");
    expect(routeAndRenameMenuSource).toContain("const openSessionAgentConfig = useCallback");
    expect(routeAndRenameMenuSource).toContain("returnLabel: \"chat\"");
    expect(routeAndRenameMenuSource).toContain("returnTo: `/chat?session=${encodeURIComponent(session.id)}`");
    expect(routeSource).toContain('import("../SessionContextMenu")');
    expect(routeSource).toContain("<SessionContextMenu");
    expect(routeSource).toContain("onAddToReview={handleAddSessionToReview}");
    expect(routeSource).toContain("onOpenAgentConfig={openSessionAgentConfig}");
    expect(routeSource).toContain("onRename={beginRenameSession}");
    expect(routeSource).toContain("onDelete={handleDeleteSession}");
    expect(routeSource).toContain("event.key === \"Escape\"");
    expect(routeSource).not.toContain("const sessionContextMenuStyle: CSSProperties | undefined");
    expect(routeSource).not.toContain("onClick={() => handleAddSessionToReview(session)}");
    expect(routeSource).not.toContain("onClick={() => beginRenameSession(session)}");
    expect(routeSource).not.toContain("onClick={() => handleDeleteSession(session)}");
    expect(sessionContextMenuSource).toContain("styles.sessionContextMenu");
    expect(sessionContextMenuSource).toContain("styles.sessionContextMenuItem");
    expect(sessionContextMenuSource).toContain("styles.sessionContextMenuDanger");
    expect(sessionContextMenuSource).toContain("<VDropdownMenu");
    expect(sessionContextMenuSource).toContain("position={position}");
    expect(sessionContextMenuStyles.sessionContextMenu).toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
    expect(sessionContextMenuStyles.sessionContextMenu).toContain("shadow-none");
    expect(sessionContextMenuStyles.sessionContextMenu).not.toContain("vui-surface-glass");
    expect(sessionContextMenuStyles.sessionContextMenu).not.toContain("vui-shadow-hairline");
    expect(directSessionIndexItemSource).toContain("styles.sessionItemNotice");
    expect(directSessionIndexItemStyles.sessionItemNotice).toContain("border-l-2");
    expect(directSessionIndexItemStyles.sessionItemNotice).toContain("mx-2.5");
    expect(directSessionIndexItemStyles.sessionItemNotice).not.toContain("vui-surface-glass");
    expect(directSessionIndexItemStyles.sessionItemNotice).not.toContain("vui-shadow-hairline");
    expect(sessionContextMenuSource).toContain("sessionContextMenuStyle");

    expect(routeStyles.sessionContextMenu).toBeTypeOf("string");
    expect(routeStyles.sessionContextMenuItem).toBeTypeOf("string");
    expect(routeStyles.sessionContextMenuDanger).toBeTypeOf("string");
    expect(routeStyles.sessionItemContextTarget).toContain("!bg-[var(--vui-surface-card)]");
    expect(routeStyles.sessionItemContextTarget).toContain("shadow-[var(--vui-shadow-inset-accent)]");
    // Wave 8D: tab context target is a thin modifier on AgentSessionTabStrip map.
    expect(routeStyles.agentSessionTabContextTarget).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabContextTarget).toContain("agentSessionTabContextTarget");
  });

  it("opens an Agent-scoped right-click menu from Agent directory rows", () => {
    expect(routeSource).toContain("const [agentContextMenu, setAgentContextMenu]");
    // Directory context actions live in useChatAgentDirectoryActions; route owns mutations + menu mount.
    expect(agentDirectoryActionsSource).toContain("const openAgentContextMenu = useCallback");
    expect(agentDirectoryActionsSource).toContain("event.preventDefault()");
    expect(agentDirectoryActionsSource).toContain("setAgentContextMenu({");
    expect(agentDirectoryActionsSource).toContain("const handleRenameAgent = useCallback");
    expect(agentDirectoryActionsSource).toContain("const handleArchiveAgent = useCallback");
    expect(agentDirectoryActionsSource).toContain("window.confirm(message)");
    expect(agentDirectoryActionsSource).toContain("renameAgent({ agentId: agentRenameDraft.agentId, displayName: title })");
    expect(agentDirectoryActionsSource).not.toMatch(/window\.prompt\s*\(/);
    expect(routeSource).toContain("AgentRenameDialog");
    expect(agentDirectoryActionsSource).toContain("archiveAgent({ agentId })");
    expect(routeSource).toContain("onContextMenu={openAgentContextMenu}");
    expect(routeSource).toContain('import("../AgentContextMenu")');
    expect(routeSource).toContain("<AgentContextMenu");
    expect(routeSource).toContain("useChatAgentArchiveQueue");
    expect(routeSource).toContain("enqueueArchive: enqueueAgentArchive");
    expect(routeSource).toContain("pendingAgentIds: pendingArchiveAgentIds");
    expect(agentsApiSource).toContain('method: "DELETE"');
    expect(routeSource).toContain("void queryClient.cancelQueries({ queryKey: queryKeys.agents() })");
    expect(routeSource).toContain("queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), remainingAgents)");
    expect(routeSource).toContain("useChatArchivedAgentRetirement");
    expect(routeSource).toContain("resolveAuthoritativeArchivedSessionIds");
    expect(routeSource).toContain("archiveSummary: agent.archiveSummary");
    expect(chatArchivedAgentRetirementSource).toContain("Removes an archived Agent's sessions from the normal Chat selection surface");
    expect(chatArchivedAgentRetirementSource).toContain("replaceIfStillViewing");
    expect(chatArchivedAgentRetirementSource).not.toContain("if (!archivedSessionIds.length)");
    expect(routeSource).toContain("retiredDirectSessionIdsRef");
    expect(routeSource).toContain("updateSessionSummaryCaches(queryClient");
    expect(chatArchivedAgentRetirementSource).toContain("resolveArchivedSessionRouteTransition");
    expect(routeSource).not.toContain("previousActiveSessionId");
    expect(routeSource).not.toContain("previousSelectedAgentId");
    expect(routeSource).toContain("onQueueDrained: async () => {");
    expect(routeSource).toContain("await chatWorkspaceCache.afterAgentArchived()");
    expect(routeSource).toContain("isAgentArchivePending(agentContextMenu.agent.agentId)");
    expect(routeSource).not.toContain("archiveAgentMutation.isPending");
    expect(routeSource).toContain("onArchive={handleArchiveAgent}");
    expect(routeSource).toContain("onRename={handleRenameAgent}");
    expect(routeSource).toContain("onCreateSession={handleCreateAgentSession}");
    expect(routeSource).toContain("onOpenConfig={handleOpenAgentConfig}");
    expect(routeSource).toContain("onOpenLatest={handleOpenAgentLatestSession}");
    expect(routeSource).not.toContain("renameSessionMutation.mutate({ sessionId: directSessionId, title })");
    expect(agentConversationDirectorySource).toContain(
      "onContextMenu={(event) => onContextMenu(event, agent, latestSession ?? null)}",
    );
    expect(agentConversationDirectorySource).toContain(
      "onPress={() => onOpenAgent(agent, latestSession ?? null)}",
    );
    expect(agentContextMenuSource).toContain('aria-label={lang === "zh" ? "Agent 操作" : "Agent actions"}');
    expect(agentContextMenuSource).toContain("<VDropdownMenu");
    expect(agentContextMenuSource).toContain("打开最近会话");
    expect(agentContextMenuSource).toContain("新建会话");
    expect(agentContextMenuSource).toContain("重命名 Agent");
    expect(agentContextMenuSource).toContain("打开 Agent 设置");
    expect(agentContextMenuSource).toContain("安全归档");
    expect(agentContextMenuSource).toContain("agentCanArchiveFromContextMenu");
    expect(agentContextMenuSource).toContain("sessionContextMenuDanger");
    expect(agentContextMenuSource).toContain("onDismiss");
    expect(agentContextMenuSource).not.toContain("Trash2");
    expect(agentContextMenuSource).not.toContain("Eraser");
  });

  it("shows each visible agent with a functional role label, not only a person name", () => {
    expect(routeSource).toContain("fetchPublicConfig()");
    expect(routeSource).toContain("queryKeys.configPublic()");
    expect(routeSource).toContain("const modelLabelsById = useMemo");
    expect(routeSource).toContain("const resolveModelLabel = useCallback");
    expect(routeAndIndexRailSource).toContain("agentDisplayInfo(agent, lang, { resolveModelLabel })");
    expect(agentSessionTabStripSource).toContain("sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel)");
    expect(routeSource).toContain("participantAgentDisplayInfo(participantLike, participantAgent, lang, resolveModelLabel)");
    expect(conversationIndexModelSource).toContain("dialogueModelId: session.dialogueModelId");
    expect(agentSessionTabStripSource).toContain("sessionDisplay.modelLabel");
    expect(routeAndIndexRailSource).toContain("participantDisplay.modelLabel");
    expect(routeSource).toContain("display.modelLabel");
    expect(agentSessionTabStripSource).toContain("const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined");
    expect(agentSessionTabStripSource).toContain("const sessionDisplay = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel)");
    expect(routeAndIndexRailSource).toContain("const participantDisplay = groupParticipantIdentity(participant)");
    expect(routeSource).toContain("identityLabel: formatAgentIdentityWithRole");
    expect(chatGroupManagementDialogSource).toContain("styles.memberCopy");
    expect(chatGroupManagementDialogSource).toContain("styles.agentRoleTag");
    expect(routeAndIndexRailSource).toMatch(/styles\.agentRoleTag|routeStyles\.agentRoleTag/);
    expect(routeAndIndexRailSource).toMatch(/styles\.agentModelTag|routeStyles\.agentModelTag/);
    expect(routeAndIndexRailSource).toMatch(/styles\.agentModelLine|routeStyles\.agentModelLine/);

    expect(chatGroupManagementDialogStyles.memberCopy).toBeTypeOf("string");
    expect(chatGroupManagementDialogStyles.agentRoleTag).toBeTypeOf("string");
    expect(routeStyles.agentRoleTag).toBeTypeOf("string");
    expect(routeStyles.agentModelTag).toBeTypeOf("string");
    expect(routeStyles.agentModelLine).toBeTypeOf("string");
  });

  it("hides direct sessions whose Agent is no longer active in Agent Center", () => {
    expect(conversationIndexModelSource).toContain("export function isVisibleDirectSession");
    expect(conversationIndexModelSource).toContain("if (session.agentMissing)");
    expect(conversationIndexModelSource).toContain("return false;");
    expect(conversationIndexModelSource.indexOf("if (session.agentMissing)")).toBeLessThan(
      conversationIndexModelSource.indexOf("if (!String(session.agentId ?? \"\").trim())"),
    );
    expect(conversationIndexModelSource).toContain("export function isVisibleConversation");
    expect(conversationIndexModelSource).toContain("if (conversation.agentMissing)");
    expect(conversationIndexModelSource.indexOf("if (conversation.agentMissing)")).toBeLessThan(
      conversationIndexModelSource.indexOf("if (!String(conversation.agentId ?? \"\").trim())"),
    );
    expect(routeSource).toContain("const rawSessionsQuery = useSessionIndexQuery");
    expect(routeSource).toContain("const visibleSessionsData = useMemo");
    expect(routeSource).toContain("data: visibleSessionsData");
    expect(conversationIndexModelSource).toContain("const rawSessionsById = new Map");
    expect(conversationIndexModelSource).toContain("if (!isVisibleConversation(conversation, rawSessionsById))");
    expect(conversationIndexModelSource).toContain("if (rawSession && !session)");
    expect(routeSource).toContain("mergeAllVisibleSessions");
    expect(routeSource).toContain("const rightIndexSessions = useMemo");
    expect(conversationIndexModelSource).toContain("mergeVisibleSessionsIntoConversations(conversations, rightIndexSessions)");
    expect(conversationIndexModelSource).toContain("conversation.type !== \"group_room\"");
    expect(conversationIndexModelSource).toContain("if (!isVisibleConversation(conversation, rawSessionsById))");
  });

  it("renders selected Agent sessions in the top Agent session strip instead of the right conversation index", () => {
    expect(directSessionIndexItemSource).toContain("export function isChildSession");
    expect(conversationIndexModelSource).toContain("export function rootSessionIdFor");
    expect(conversationIndexModelSource).toContain("export function isRepresentedInAgentSessionTabs");
    expect(conversationIndexModelSource).toContain(
      'return Boolean(String(session?.agentId || "").trim())',
    );
    expect(conversationIndexModelSource).toContain("export function hasInvalidChildSessionLink");
    expect(conversationIndexModelSource).toContain("export function mergeVisibleSessionsIntoConversations");
    expect(routeSource).toContain("queryKeys.sessionChildSessions(activeRootSessionId || \"none\")");
    expect(routeSource).toContain("listSessionChildSessions(activeRootSessionId)");
    expect(routeSource).toContain("const activeRootSessionId = rootSessionIdFor(sessionDetailQuery.data ?? directSessionActiveSummary)");
    expect(routeSource).toContain("queryKeys.sessionChildSessions(detailRootSessionId)");
    expect(routeSource).toContain("const merged = [...(sessions ?? []), ...(childSessions ?? [])]");
    expect(routeSource).toContain("const rightIndexSessions = useMemo");
    expect(routeSource).toContain("allVisibleSessions.filter((session) => !isRepresentedInAgentSessionTabs(session))");
    expect(routeSource).toContain("const selectedAgentVisibleSessions = useMemo");
    expect(routeSource).toContain("const agentSessionTabs = useMemo");
    expect(routeSource).toContain("sessions: [...(selectedAgentSessionsQuery.data?.items ?? []), ...selectedAgentVisibleSessions]");
    expect(routeAndSessionSurfaceSource).toContain("compareAgentSessionTabOrder");
    expect(routeAndSessionSurfaceSource).toContain("leftCreated.localeCompare(rightCreated)");
    expect(routeAndSessionSurfaceSource).not.toContain('String(right.updatedAt || right.lastActive || "")');
    expect(routeAndSessionSurfaceSource).not.toContain("isChildSession(left) ? 2 : 1");
    expect(routeSource).toContain("buildAgentSessionTabs");
    expect(conversationIndexModelSource).toContain("mergeVisibleSessionsIntoConversations(conversations, rightIndexSessions)");
    expect(conversationIndexModelSource).toContain("if (isRepresentedInAgentSessionTabs(session))");
    expect(routeSource).toContain("const invalidChildSessionLinkMessage = hasInvalidChildSessionLink(sessionDetailQuery.data ?? directSessionActiveSummary)");
    expect(routeSource).toContain("child_session_link_invalid");
    expect(routeSource).toContain("子对话缺少 parentSessionId/rootSessionId");
    expect(routeSource).not.toContain("rootSessionId || session.parentSessionId || session.id");
    expect(routeSource).not.toContain("const childSessionsByRootId = useMemo");
    expect(routeSource).not.toContain("function renderChildSessionItems");
    expect(routeSource).not.toContain("styles.childSessionList");
    expect(routeSource).toContain("<AgentSessionTabStrip");
    expect(routeSource).toContain("sessions={agentSessionTabs}");
    // Session tabs must precede overlayPaneControls; first-child ml-auto was pushing tabs right.
    expect(chatCenterTabStripSource.indexOf("{sessionTabs}")).toBeLessThan(
      chatCenterTabStripSource.indexOf("styles.overlayPaneControls"),
    );
    expect(routeSource).toContain("ChatCenterTabStrip");
    expect(routeAndCenterPackSource).toContain("!leftOverlayVisible || !rightOverlayVisible");
    expect(routeSource).toContain("leftOverlayVisible={responsiveLayout.leftVisible}");
    expect(routeSource).toContain("rightOverlayVisible={responsiveLayout.rightVisible}");
    expect(routeSource).toContain("onContextMenu={openSessionContextMenu}");
    expect(routeSource).toContain("onOpenDirectSession={handleOpenDirectSession}");
    expect(routeSource).toContain("onPrefetchDirectSession={handlePrefetchDirectSession}");
    expect(routeSource).toContain("handlePrefetchDirectSession");
    expect(routeSource).toContain("prefetchSessionDetailWindow");
    expect(conversationIndexTreeSource).toContain("onPrefetch={onPrefetchDirectSession}");
    expect(directSessionIndexListSource).toContain("onPrefetch={onPrefetch}");
    expect(routeSource).toContain("onSubmitRename={submitRenameSession}");
    expect(routeSource).toContain("onCancelRename={cancelRenameSession}");
    expect(routeSource).toContain("onCreateSession={handleCreateSession}");
    expect(routeSource).toContain("onDeleteSession={handleDeleteSession}");
    expect(routeSource).toContain("deletePendingSessionId={");
    expect(routeSource).toContain("deleteSessionMutation.isPending");
    expect(agentSessionTabStripSource).toContain("className={styles.agentSessionTabCreateButton}");
    expect(agentSessionTabStripSource).toContain("className={styles.agentSessionTabCloseButton}");
    expect(agentSessionTabStripSource).not.toContain("styles.agentSessionTabCurrentBadge");
    expect(agentSessionTabStripSource).not.toContain("styles.agentSessionTabStatusText");
    expect(agentSessionTabStripSource).toContain('role="presentation"');
    expect(agentSessionTabStripSource).toContain("data-agent-session-tab-container");
    expect(agentSessionTabStripSource).toContain('closest("[data-agent-session-tab-container]")?.contains(nextFocus)');
    expect(agentSessionTabStripSource).toContain('role="tab"');
    expect(agentSessionTabStripSource).toContain('event.key === "ArrowRight"');
    expect(agentSessionTabStripSource).toContain('event.key === "ArrowLeft"');
    expect(agentSessionTabStripSource).toContain('event.key === "Home"');
    expect(agentSessionTabStripSource).toContain('event.key === "End"');
    expect(agentSessionTabStripSource).toContain("deletePendingSessionId");
    expect(agentSessionTabStripSource).toContain("sessionDeletePending");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabGroup");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabRail");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabActive");
    expect(agentSessionTabStripSource).not.toContain("styles.agentSessionTabChild");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabRoot");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabEditing");
    expect(agentSessionTabStripSource).toContain("onContextMenu={(event) => onContextMenu(event, session)}");
    expect(agentSessionTabStripSource).toContain("<Bot size={14} />");
    expect(agentSessionTabStripSource).not.toContain("MessageCircleHeart");
    expect(agentSessionTabStripSource).not.toContain("sessionIsChild");
    expect(agentSessionTabStripSource).toContain("session.title");
    expect(agentSessionTabStripSource).toContain("session.taskSummary");
    expect(agentSessionTabStripSource).toContain("onOpenDirectSession(session.id)");
    expect(agentSessionTabStripSource).toContain("const tabEditing = editingSessionId === session.id");
    expect(agentSessionTabStripSource).toContain("className={styles.agentSessionTabTitleInput}");
    expect(agentSessionTabStripSource).toContain("<VNativeInput");
    expect(agentSessionTabStripSource).not.toMatch(/<input\b/);
    expect(directSessionIndexItemSource).toContain("<VNativeInput");
    expect(directSessionIndexItemSource).not.toMatch(/<input\b/);
    expect(agentSessionTabStripSource).toContain("onSubmitRename(session, { reason:");
    expect(agentSessionTabStripSource).toContain("onCancelRename");

    expect(routeStyles.agentSessionTabGroup).toBeTypeOf("string");
    expect(routeStyles.agentSessionTab).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabActive).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabChild).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabRoot).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabEditing).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabIcon).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabTitle).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabTitleInput).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabEditActions).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabEditButton).toBeTypeOf("string");
    expect(routeStyles.conversationKindBadgeChild).toBeTypeOf("string");
  });

  it("moves file workspace tabs and preview display into chat file components while keeping route query ownership", () => {
    expect(routeSource).toContain('import { ChatSessionWorkspacePanel } from "./ChatSessionWorkspacePanel"');
    expect(routeSource).not.toContain('import { ChatFilePreviewPanel } from "./ChatFilePreviewPanel"');
    expect(routeSource).toContain("const ChatFileWorkspaceTabs = lazy(() =>");
    expect(routeSource).toContain('import("./ChatFileWorkspaceTabs")');
    expect(routeSource).toContain('const activeFilePath = workspace.activeTab !== "agent" && !activeCliAgentRunId ? workspace.activeTab : null;');
    expect(routeSource).toContain("const fileContentQuery = useQuery({");
    expect(routeSource).toContain("queryKeys.fileContent(activeFilePath ?? \"\")");
    expect(routeSource).toContain("fetchFileContent(activeFilePath ?? \"\")");
    expect(filesApiSource).toContain("export function fetchFileContent");
    expect(routeSource).toContain("<ChatFileWorkspaceTabs");
    expect(routeSource).toContain("openTabs={workspace.openTabs}");
    expect(routeSource).toContain("activeTab={workspace.activeTab}");
    expect(routeSource).toContain("closePreviewTab(activeSessionId, tabPath)");
    expect(routeSource).toContain("setActiveTab(activeSessionId, tabPath)");
    expect(routeSource).toContain("filePreview={{");
    expect(routeSource).toContain("changed: fileContentQuery.data ? changedFiles.has(fileContentQuery.data.path) : false");
    expect(routeSource).toContain("errorMessage: fileContentQuery.isError ? describeError(fileContentQuery.error, t(\"loadFailed\")) : \"\"");
    expect(routeSource).toContain("file: fileContentQuery.data");
    expect(routeSource).toContain("loadingLabel: t(\"loadingFilePreview\")");
    expect(chatSessionWorkspacePanelSource).toContain("<ChatFilePreviewPanel");
    expect(routeSource).not.toContain("<LazyFilePreview");
    expect(routeSource).not.toContain("styles.fileTab");
    expect(routeStylesModuleSource).not.toContain("fileTab:");
    expect(routeStylesModuleSource).not.toContain("fileTabButton:");
    expect(routeStylesModuleSource).not.toContain("fileTabClose:");

    expect(chatFileWorkspaceTabsSource).toContain("export function ChatFileWorkspaceTabs");
    expect(chatFileWorkspaceTabsSource).toContain('from "./ChatFileWorkspaceTabs.styles"');
    expect(chatFileWorkspaceTabsSource).toContain("styles.fileTab");
    expect(chatFileWorkspaceTabsSource).toContain("styles.fileTabActive");
    expect(chatFileWorkspaceTabsSource).toContain("styles.fileTabButton");
    expect(chatFileWorkspaceTabsSource).toContain("styles.fileTabClose");
    expect(chatFileWorkspaceTabsSource).toContain('role="tab"');
    expect(chatFileWorkspaceTabsSource).toContain("aria-selected={selected}");
    expect(chatFileWorkspaceTabsSource).toContain("aria-current={selected ? \"page\" : undefined}");
    expect(chatFileWorkspaceTabsSource).toContain("<X size={14} aria-hidden=\"true\" />");
    expect(chatFileWorkspaceTabsSource).toContain("fileTabName(tabPath)");
    expect(chatFileWorkspaceTabsStyles.fileTab).toBeTypeOf("string");
    expect(chatFileWorkspaceTabsStyles.fileTab).toContain("overflow-hidden");
    expect(chatFileWorkspaceTabsStyles.fileTab).toContain("max-w-[min(100%,18rem)]");
    expect(chatFileWorkspaceTabsStyles.fileTabActive).toBeTypeOf("string");
    expect(chatFileWorkspaceTabsStyles.fileTabButton).toBeTypeOf("string");
    expect(chatFileWorkspaceTabsStyles.fileTabButton).toContain("truncate");
    expect(chatFileWorkspaceTabsStyles.fileTabClose).toBeTypeOf("string");
    expect(chatFileWorkspaceTabsStyles.fileTabClose).toContain("size-[var(--vui-control-height-xs)]");

    expect(chatFilePreviewPanelSource).toContain("export function ChatFilePreviewPanel");
    expect(chatFilePreviewPanelSource).toContain('from "./ChatFilePreviewPanel.styles"');
    expect(chatFilePreviewPanelSource).toContain("<LazyFilePreview");
    expect(chatFilePreviewPanelSource).toContain('role="alert"');
    expect(chatFilePreviewPanelSource).toContain('role="status"');
    expect(chatFilePreviewPanelSource).toContain('aria-live="polite"');
    expect(chatFilePreviewPanelStyles.emptySurface).toContain("min-h-[96px]");
    expect(chatFilePreviewPanelStyles.emptySurface).not.toContain("h-full");
    expect(chatFilePreviewPanelStyles.emptySurface).not.toContain("min-h-[min(420px,calc(100dvh_-_190px))]");
    expect(chatFilePreviewPanelStyles.emptySurface).toMatch(/!bg-vui-surface-panel|!bg-\[var\(--vui-surface-panel\)\]/);
    expect(chatFilePreviewPanelStyles.emptySurface).toContain("shadow-none");
    expect(chatFilePreviewPanelStyles.emptySurface).toContain("break-words");
    expect(chatFilePreviewPanelStyles.emptySurface).toContain("[overflow-wrap:anywhere]");
    expect(chatFilePreviewPanelStyles.emptySurface).not.toContain("vui-surface-glass");
    expect(chatFilePreviewPanelStyles.emptySurface).not.toContain("vui-shadow-hairline");
  });

  it("renders cli agent tool calls as persistent terminal tabs beside child sessions", () => {
    expect(cliAgentRunModelSource).toContain('const CLI_AGENT_TOOL_NAME = "cli_agent_run_tool"');
    expect(cliAgentRunModelSource).toContain('const CLI_AGENT_RUN_TAB_PREFIX = "cli-agent-run:"');
    expect(cliAgentRunModelSource).toContain("function cliAgentRunTabId");
    expect(cliAgentRunModelSource).toContain("function cliAgentRunIdFromTabId");
    expect(cliAgentRunModelSource).toContain('return "Claude Code"');
    expect(cliAgentRunModelSource).toContain("function buildCliAgentRunViews");
    expect(cliAgentRunModelSource).toContain("function parseCliAgentResultText");
    expect(cliAgentRunModelSource).toContain("for (const candidate of [toolCall.resultPreview, toolCall.summary])");
    expect(cliAgentRunModelSource).toContain("function cliAgentRunIdForSource");
    expect(cliAgentRunModelSource).toContain("function cliAgentCanonicalKey");
    expect(cliAgentRunModelSource).toContain("[\"cli-run-v3\", agentType.trim(), normalizedCwd, normalizedMode].join(\"\\n\")");
    expect(cliAgentRunModelSource).toContain("closedCliAgentRunIdFromMessage");
    expect(cliAgentRunModelSource).toContain("cliAgentLifecyclePatchFromMessage");
    expect(cliAgentRunModelSource).toContain("applyCliAgentLifecyclePatchToRuns");
    expect(cliAgentRunModelSource).toContain("function cliAgentRunCloseToken");
    expect(cliAgentRunModelSource).toContain("return run.id || run.sourceRunId");
    expect(cliAgentRunModelSource).toContain("function shouldRenderCliAgentRunTab");
    expect(cliAgentRunModelSource).toContain('code === "CLI_AGENT_TERMINAL_ACTIVE"');
    expect(cliAgentRunModelSource).toContain("if (!result) {");
    expect(cliAgentRunModelSource).toContain('["error", "failed", "failure", "timeout", "timed_out"].includes(normalizedStatus)');
    expect(cliAgentRunModelSource).toContain("const runsById = new Map<string, CliAgentRunView>()");
    expect(cliAgentRunModelSource).toContain("const runsByCanonicalKey = new Map<string, CliAgentRunView>()");
    expect(cliAgentRunModelSource).toContain("const lifecycleByRunId = new Map<string, CliAgentLifecyclePatch>()");
    expect(cliAgentRunModelSource).toContain("const lifecycleByCanonicalKey = new Map<string, CliAgentLifecyclePatch>()");
    expect(cliAgentRunModelSource).toContain("function buildCliAgentLifecycleRunView");
    expect(cliAgentRunModelSource).toContain("const normalizedMode = (mode.trim().toLowerCase() || \"readonly\")");
    expect(cliAgentRunModelSource).toContain("closedRunIds.add(closedRunId)");
    expect(cliAgentRunModelSource).toContain("closedCanonicalKeys.add(lifecycleCanonicalKey)");
    expect(cliAgentRunModelSource).toContain("runsByCanonicalKey.set(canonicalKey, run)");
    expect(cliAgentRunModelSource).toContain("!(run.canonicalKey && closedCanonicalKeys.has(run.canonicalKey))");
    expect(cliAgentRunModelSource).not.toContain("closedRunIds.delete(cliRunId)");
    expect(cliAgentRunModelSource).toContain("toolCall.name !== CLI_AGENT_TOOL_NAME");
    expect(cliAgentRunModelSource).toContain("function isCliAgentRunActiveForClose");
    expect(routeAndCliTerminalSource).toContain('from "./cliAgentRunModel"');
    expect(routeSource).toContain('from "./useChatCliAgentTerminal"');
    expect(routeSource).toContain('from "./useDesktopConversationAttention"');
    expect(routeAndCliTerminalSource).toContain("closeCliAgentRun");
    expect(routeAndCliTerminalSource).toContain("stopCliAgentTerminalSession");
    expect(cliAgentsApiSource).toContain("/api/cli-agents/terminal-sessions/");
    expect(routeAndCliTerminalSource).toContain("const [closedCliAgentRunTokensBySession");
    expect(routeAndCliTerminalSource).toContain("const [cliAgentTerminalSessions");
    expect(routeAndCliTerminalSource).toContain("const [mountedCliAgentRunIdsBySession");
    expect(routeAndCliTerminalSource).toContain("const mountedCliAgentRuns = useMemo");
    expect(routeSource).toContain('const activeFilePath = workspace.activeTab !== "agent" && !activeCliAgentRunId ? workspace.activeTab : null;');
    expect(routeSource).toContain("cliAgentRuns={cliAgentRunTabs}");
    expect(routeSource).toContain("onOpenCliAgentRun={(runId) =>");
    expect(routeSource).toContain("onCloseCliAgentRun={(runId) =>");
    expect(routeSource).toContain("setActiveTab(activeSessionId, cliAgentRunTabId(runId));");
    expect(routeAndCliTerminalSource).toContain("window.confirm(");
    expect(routeAndCliTerminalSource).toContain("const terminalSessionId = String(terminalSession?.terminalSessionId || run.terminalSessionId || run.result?.terminalSessionId || \"\").trim()");
    expect(routeAndCliTerminalSource).toContain("stopCliAgentTerminalSession<CliAgentTerminalSession>");
    expect(routeSource).toContain("const CliAgentRunTerminalPanel = lazy(() =>");
    expect(routeSource).toContain('import("./CliAgentRunTerminalPanel")');
    expect(routeSource).toContain("<ChatCliAgentTerminalStack");
    expect(routeAndCliStackSource).toContain("runs.map((run) =>");
    expect(routeAndCliStackSource).toContain("!groupPanelActive && activeCliAgentRunId === run.id");
    expect(routeAndCliStackSource).toContain("aria-hidden={!active}");
    expect(terminalPanelSource).toContain("aria-hidden={!active}");
    expect(routeAndCliStackSource).toContain("data-cli-agent-run-id={run.id}");
    expect(terminalPanelSource).toContain("data-cli-agent-run-id={run.id}");
    expect(routeSource).toContain("onTerminalSessionChange={handleCliAgentTerminalSessionChange}");
    expect(cliAgentRunTerminalPanelStyles.cliAgentRunPanel).toContain("shadow-none");
    expect(cliAgentRunTerminalPanelStyles.cliAgentRunPanel).not.toContain("vui-surface-glass");
    expect(cliAgentRunTerminalPanelStyles.cliAgentRunPanel).not.toContain("vui-shadow-hairline");
    expect(cliAgentRunTerminalPanelStyles.cliAgentRunPanelHidden).toContain("hidden");
    expect(cliAgentRunTerminalPanelStyles.cliAgentRunPanelHidden).not.toContain("vui-surface-glass");
    expect(routeSource).not.toContain(") : activeCliAgentRun ? (");
    expect(routeSource).not.toContain('import { Terminal } from "@xterm/xterm"');
    expect(routeSource).not.toContain('import "@xterm/xterm/css/xterm.css"');
    expect(terminalPanelSource).toContain('import { Terminal } from "@xterm/xterm"');
    expect(terminalPanelSource).toContain('import "@xterm/xterm/css/xterm.css"');
    expect(cliAgentsApiSource).toContain('"/api/cli-agents/terminal-sessions/ensure"');
    expect(terminalPanelSource).toContain("ensureCliAgentTerminalSession");
    expect(terminalPanelSource).toContain('intent,');
    expect(terminalPanelSource).toContain('fetchTerminalSession("view", controller.signal)');
    expect(terminalPanelSource).toContain('requestTerminalSession(terminalCanResume ? "resume" : "start")');
    expect(cliAgentRunModelSource).toContain("function canInputTerminal");
    expect(terminalPanelSource).toContain("terminalCanInputRef.current");
    expect(terminalPanelSource).toContain("const terminalSizeForRequest = useCallback");
    expect(terminalPanelSource).toContain("const terminalSize = terminalSizeForRequest()");
    expect(terminalPanelSource).toContain("rows: terminalSize.rows");
    expect(terminalPanelSource).toContain("cols: terminalSize.cols");
    expect(terminalPanelSource).toContain('if (intent === "view" || !canInputTerminal(session))');
    expect(terminalPanelSource).toContain('if (payload.type === "terminal_snapshot" && !canInputTerminal(payload.session))');
    expect(terminalPanelSource).toContain("终端未运行，请先恢复会话。");
    expect(terminalPanelSource).toContain("已恢复，等待终端输出。");
    expect(terminalPanelSource).toContain("sourceRunId: run.sourceRunId");
    expect(terminalPanelSource).toContain('cliSessionId: intent === "start" ? "" : terminalCliSessionIdRef.current');
    expect(routeAndCliTerminalSource).toContain("void refetchSessionDetail()");
    expect(routeSource).toContain("refetchSessionDetail: () => sessionDetailQuery.refetch()");
    expect(terminalPanelSource).toContain("new EventSource(`/api/cli-agents/terminal-sessions/${encodeURIComponent(terminalSessionId)}/events`)");
    expect(terminalPanelSource).toContain("terminal_output");
    expect(terminalPanelSource).toContain("transcriptTailReplayable");
    expect(terminalPanelSource).toContain("screenReplay");
    expect(terminalPanelSource).toContain("screenText");
    expect(terminalPanelSource).toContain("const replayTerminalSnapshot");
    expect(terminalPanelSource).toContain("历史 TUI 画面无法安全重放");
    expect(terminalPanelSource).toContain("type CliAgentTerminalAck");
    expect(terminalPanelSource).toContain("sendCliAgentTerminalInput<CliAgentTerminalAck>");
    expect(cliAgentsApiSource).toContain("/input");
    expect(terminalPanelSource).toContain("CLI_AGENT_TASK_LOCKED");
    expect(terminalPanelSource).toContain("指令未发送：当前 CLI Agent 终端已有任务在运行。");
    expect(terminalPanelSource).not.toContain(".then((session) => setTerminalSession(session))");
    expect(terminalPanelSource.indexOf('if (payload.type === "terminal_output" && payload.chunk)')).toBeLessThan(
      terminalPanelSource.indexOf("if (payload.session)"),
    );
    expect(terminalPanelSource).toContain("terminal.write(");
    expect(routeSource).not.toContain("terminalTextForDisplay");
    expect(routeSource).not.toContain("<pre ref={outputRef}");
    expect(routeSource).not.toContain("sendTerminalInput");
    expect(routeSource).not.toContain("terminalInput");
    expect(routeSource).not.toContain("输入命令或回复");
    expect(routeSource).not.toContain("Type input");
    expect(cliAgentsApiSource).toContain("/input");
    expect(cliAgentsApiSource).toContain("/stop");
    expect(routeSource).not.toContain("const [activeCliAgentRunId, setActiveCliAgentRunId] = useState");
    expect(routeStyles.cliAgentRunPanel).toBeTypeOf("string");
    expect(routeStyles.cliAgentRunPanelHidden).toContain("hidden");
    expect(routeStyles.cliAgentTerminalFrame).toBeTypeOf("string");
    expect(routeStyles.cliAgentTerminalOutputShell).toContain("bg-[var(--bg-canvas)]");
    expect(routeStyles.cliAgentTerminalOutput).toBeTypeOf("string");
    expect(routeStyles.cliAgentTerminalStatus).toBeTypeOf("string");
    expect(routeCssSource).not.toContain(".cliAgentTerminalInputRow");
    expect(routeStyles.agentSessionTabCli).toBeTypeOf("string");
    expect(routeStyles.agentSessionTabCloseButton).toBeTypeOf("string");
    expect(routeCssSource).not.toContain(".cliAgentRunIconButton");
    expect(routeCssSource).not.toContain(".cliAgentRunMetaBar");
    expect(conversationViewSource).toContain("isCliAgentLifecycleMessage");
    expect(conversationViewSource).toContain("cliAgentLifecycleLabel");
    expect(conversationViewSource).toContain("styles.cliAgentLifecycleTurn");
    expect(conversationStyles.cliAgentLifecycleTurn).toBeTypeOf("string");
    expect(conversationStyles.cliAgentLifecycleMeta).toBeTypeOf("string");
    expect(agentSessionTabStripSource).toContain("export type CliAgentRunTab");
    expect(agentSessionTabStripSource).toContain("cliAgentRuns.map");
    expect(agentSessionTabStripSource).toContain("SquareTerminal");
    expect(agentSessionTabStripSource).toContain("onCloseCliAgentRun?:");
    expect(agentSessionTabStripSource).toContain("styles.agentSessionTabCloseButton");
    expect(agentSessionTabStripSource).not.toContain("run.mode ? ` · ${run.mode}` : \"\"");
  });

  it("renders a compact QQ-style tree with direct sessions separate from Team-owned rooms", () => {
    expect(routeSource).toContain("listTeams()");
    expect(routeSource).toContain("queryKeys.teams()");
    // Directory partition needs teams without opening the group picker.
    expect(routeSource).toContain("Must load whenever the left-rail agent directory is active");
    expect(routeSource).not.toContain("enabled: secondaryChatDataEnabled && teamsPickerNeeded");
    expect(routeSource).toContain("linkedTeamRoomIds");
    expect(routeSource).toContain("filteredTeams");
    expect(routeSource).toContain("filteredStandaloneGroupConversations");
    expect(conversationIndexTreeSource).toContain("TeamConversationIndexItem");
    expect(conversationIndexTreeSource).toContain("GroupConversationIndexItem");
    expect(chatWorkbenchFormatSource).toContain("export function formatChatConversationIndexTime");
    expect(routeAndPresentationSource).toContain("formatChatConversationIndexTime");
    expect(routeSource).toContain("formatTime={formatConversationIndexTime}");
    expect(groupSessionIndexItemsSource).toContain("export function teamStatusLabel");
    expect(groupSessionIndexItemsSource).toContain("teamStatusLabel(team.status, lang, statusLabel)");
    expect(groupSessionIndexItemsSource).toContain("VStatusChip");
    expect(groupSessionIndexItemsSource).toContain("sessionStatusChip");
    expect(groupSessionIndexItemsSource).not.toContain("sessionStatusDot");
    expect(groupSessionIndexItemsSource).not.toContain("Clock3");
    expect(groupSessionIndexItemsSource).not.toContain("CircleDot");
    expect(groupSessionIndexItemsSource).toContain("teamMemberPreview(team, lang)");
    expect(groupSessionIndexItemsSource).not.toContain("team.linkedChatRoom?.title");
    expect(groupSessionIndexItemsSource).not.toContain("team.members ?? []");
    expect(groupSessionIndexItemsSource).toContain("team.teamCategory");
    expect(groupSessionIndexItemsSource).toContain("team.teamKind");
    expect(conversationIndexModelSource).toContain("team.teamSource");
    expect(conversationIndexModelSource).toContain("team.teamTemplateId");
    expect(conversationIndexModelSource).toContain("isDiscussionTeam");
    expect(conversationIndexModelSource).toContain("buildConversationTeamLookup");
    expect(conversationIndexModelSource).toContain("conversationTeamFor");
    expect(conversationIndexModelSource).toContain("conversationTeamGroupKey(teamId)");
    expect(conversationIndexModelSource).toContain("groupKind: \"team\"");
    expect(conversationIndexModelSource).toContain("conversationTeamSearchValues");
    expect(conversationIndexModelSource).toContain("lookup.byAgentId.set(agentId, team)");
    expect(conversationIndexModelSource).toContain("lookup.byAgentCode.set(agentCode, team)");
    expect(conversationIndexModelSource).toContain("NON_DISCUSSION_TEAM_IDS");
    expect(conversationIndexModelSource).toContain("supervised-evolution-team");
    expect(groupSessionIndexItemsSource).toContain("成员：");
    expect(groupSessionIndexItemsSource).not.toContain("群成员");
    expect(groupSessionIndexItemsSource).not.toContain("团队分类");
    expect(groupSessionIndexItemsSource).toContain("团队群聊");
    expect(groupSessionIndexItemsSource).toContain("团队群聊待同步");
    expect(groupSessionIndexItemsSource).not.toContain("styles.teamTreeLabelRow");
    expect(conversationIndexTreeSource).toContain("teamWorkspaceRoute(team.teamId)");
    expect(conversationIndexTreeSource).toContain("未绑定团队的群聊");
    expect(conversationIndexTreeSource).toContain("onToggleConversationGroup(\"setupTeams\")");
    expect(conversationIndexTreeSource).toContain("onToggleConversationGroup(\"standaloneGroups\")");
    expect(conversationIndexTreeSource).toContain("expanded={searchHasTerm || !collapsedConversationGroups.setupTeams}");
    expect(conversationIndexTreeSource).toContain("expanded={searchHasTerm || !collapsedConversationGroups.standaloneGroups}");
    expect(conversationIndexTreeSource).toContain("conversationGroupLabel(\"setupTeams\"");
    expect(conversationIndexTreeSource).toContain("conversationGroupLabel(\"standaloneGroups\"");
    expect(conversationIndexTreeSource).toContain("className={styles.teamTreeGroup}");
    expect(groupSessionIndexItemsSource).not.toContain("styles.teamTreeChildren");
    expect(groupSessionIndexItemsSource).not.toContain("styles.teamTreeChild");

    expect(routeStyles.conversationGroupHeader).toBeTypeOf("string");
    expect(routeStyles.teamTreeGroup).toBeTypeOf("string");
    expect(routeStyles.teamTreeItem).toBeTypeOf("string");
    expect(routeStyles.teamTreeLabelRow).toBeTypeOf("string");
    expect(routeStyles.teamTreeChildren).toBeTypeOf("string");
    expect(routeStyles.teamTreeChild).toBeTypeOf("string");
  });

  it("groups the unified conversation list like expandable contact folders", () => {
    expect(conversationIndexModelSource).toContain("DEFAULT_COLLAPSED_CONVERSATION_GROUPS");
    expect(conversationIndexModelSource).toContain("teams: true");
    expect(conversationIndexModelSource).toContain("defaultConversationGroupCollapsed");
    expect(conversationIndexModelSource).toContain('String(groupKey).startsWith("team:")');
    expect(conversationIndexModelSource).toContain("CONVERSATION_GROUP_ORDER");
    expect(conversationIndexModelSource).toContain("classifyConversation");
    expect(conversationIndexModelSource).toContain("conversationGroupLabel");
    expect(conversationIndexModelSource).toContain("agentToConversationSummary");
    expect(conversationIndexModelSource).toContain("mergeVisibleAgentsIntoConversations");
    expect(conversationIndexModelSource).toContain("export type ConversationIndexDynamicGroupKey");
    expect(conversationIndexModelSource).toContain("const leadingGroupKeys: ConversationIndexGroupKey[] = [\"user\", \"group\"]");
    expect(conversationIndexModelSource).toContain("const teamConversationGroups: ConversationIndexGroup[] = []");
    expect(conversationIndexModelSource).toContain("...teamConversationGroups");
    expect(conversationIndexModelSource).toContain("...trailingGroupKeys");
    expect(routeSource).toContain("useConversationIndexModel");
    expect(routeSource).toContain("agents: agentsQuery.data");
    expect(routeSource).toContain("useState<Record<string, boolean>>");
    expect(conversationIndexTreeSource).toContain("groupedConversations.map");
    expect(conversationIndexTreeSource).toContain("onToggleConversationGroup: (groupKey: ConversationIndexDynamicGroupKey) => void");
    expect(routeSource).toContain("toggleConversationGroup");
    expect(routeSource).toContain("defaultConversationGroupCollapsed(groupKey)");
    expect(routeSource).toContain("ConversationIndexTree");
    expect(routeSource).toContain("<ConversationIndexTree");
    expect(routeAndIndexRailSource.indexOf("<ConversationIndexTree")).toBeLessThan(
      routeAndIndexRailSource.indexOf("styles.systemEntryGroup"),
    );
    expect(conversationIndexTreeSource).toContain("ConversationIndexSection");
    expect(conversationIndexTreeSource).toContain("defaultConversationGroupCollapsed(group.groupKey, group.groupKind)");
    expect(conversationIndexTreeSource).toContain("expanded={!collapsed}");
    expect(conversationIndexSectionSource).toContain("styles.conversationGroupHeader");
    expect(conversationIndexSectionSource).toContain("styles.conversationGroupList");
    expect(conversationIndexSectionSource).toContain("aria-expanded={expanded}");
    expect(conversationIndexSectionSource).toContain("<ChevronRight size={14} aria-hidden=\"true\" />");
    expect(routeSource).toContain("searchHasTerm");

    expect(routeStyles.conversationGroup).toBeTypeOf("string");
    expect(routeStyles.conversationGroupHeader).toBeTypeOf("string");
    expect(routeStyles.conversationGroupList).toBeTypeOf("string");
    expect(routeStyles.conversationGroupHeader).toContain("min-h-[34px]");
    expect(routeStyles.conversationGroupHeader).toContain("grid-cols-[14px_minmax(0,1fr)_auto]");
    expect(routeStyles.conversationGroupHeader).toContain("bg-transparent");
    expect(routeStyles.conversationGroupList).toContain("gap-1");
  });

  it("loads session index pages through the paginated query endpoint", () => {
    expect(routeSource).toContain("useSessionIndexQuery");
    expect(routeSource).toContain("queryText: sessionQueryText");
    expect(routeSource).toContain("enabled: sessionIndexQueryEnabled");
    expect(routeSource).toContain("const sessionIndexQueryEnabled =");
    expect(routeSource).toContain("Boolean(input.requestedSessionId || input.requestedRoomId)");
    expect(routeSource).toContain("shouldEnableSessionIndexQuery");
    expect(routeSource).toContain("bootstrapIsFetched: activeSessionBootstrapQuery.isFetched");
    expect(routeSource).toContain("bootstrapIsError: activeSessionBootstrapQuery.isError");
    expect(routeSource).toContain("bootstrapFetchStatus: activeSessionBootstrapQuery.fetchStatus");
    expect(routeSource).toContain("sessionIndexHasMore");
    expect(chatSessionIndexRailPresentationSource).toContain("加载更多会话");
    expect(chatSessionIndexRailPresentationSource).toContain("已加载全部会话");
    expect(routeSource).toContain("sessionIndexProgressVisible");
    expect(routeSource).toContain("rawSessionsQuery.loadMore()");
    expect(routeSource).toContain("styles.sessionLoadMoreButton");
    expect(routeSource).toContain("styles.sessionLoadMoreStatus");
    expect(routeStyles.sessionLoadMoreButton).toBeTypeOf("string");
    expect(routeStyles.sessionLoadMoreStatus).toBeTypeOf("string");
  });

  it("keeps the conversation index toolbar buttons slot-aligned and the search field un-nested", () => {
    const actionRowSource = routeAndIndexRailSource.slice(
      routeAndIndexRailSource.indexOf("<div className={styles.sessionActionRow}>"),
      routeAndIndexRailSource.indexOf("{conversationIndexPanel}", routeAndIndexRailSource.indexOf("<div className={styles.sessionActionRow}>")),
    );

    expect(actionRowSource).toContain("icon={<Plus size={15} />}");
    expect(actionRowSource).toContain("icon={<UsersRound size={15} />}");
    expect(routeAndIndexRailSource).toContain("<VInput");
    expect(routeAndIndexRailSource).toContain("<Search size={15} aria-hidden=\"true\" />");
    expect(routeStyles.newSessionButton).toContain("border");
    expect(routeStyles.newGroupButton).toContain("bg-[var(--vui-control-muted)]");
    expect(routeStyles.panelSearch).toContain("min-h-9");
    expect(routeStyles.panelSearch).toMatch(/border-vui-border-subtle|border-\[var\(--vui-border-subtle\)\]/);
    expect(routeStyles.panelSearch).toContain("focus-within:border-");
    expect(routeStyles.panelSearchInput).toContain("[&_[data-slot=input-wrapper]]:min-h-8");
    expect(routeStyles.panelSearchInput).toContain("[&_[data-slot=input-wrapper]]:shadow-none");
    expect(routeStyles.panelSearchInput).toContain("[&_[data-slot=input-wrapper]]:!border-0");
    expect(routeStyles.panelSearchInput).toContain("[&_[data-slot=input]]:[font-size:var(--vui-font-sm)]");
    expect(routeStyles.sessionActionRow).toContain("grid-cols-2");
    expect(routeStyles.sessionActionRow).toContain("gap-2");
    expect(routeStyles.newSessionButton).toContain("!min-w-0");
    expect(routeStyles.newSessionButton).toContain("!w-full");
    expect(routeStyles.newSessionButton).toContain("[&_[data-slot=vui-button-content]]:min-w-0");
    expect(routeStyles.newGroupButton).toContain("!min-w-0");
    expect(routeStyles.newGroupButton).toContain("!w-full");
    expect(routeStyles.newGroupButton).toContain("[&_[data-slot=vui-button-content]]:min-w-0");
    expect(routeStyles.panelSearchInput).not.toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.panelSearchInput).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(routeStyles.panelSearchInput).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(routeStyles.conversationIndexPanelBody).toContain("!overflow-hidden");
    expect(routeStyles.conversationIndexLayout).toContain("grid-rows-[auto_minmax(0,1fr)_auto]");
    expect(routeStyles.conversationIndexScrollRegion).toContain("overflow-y-auto");
    expect(routeAndIndexRailSource).toContain("styles.conversationIndexPanelBody");
    expect(routeAndIndexRailSource).toContain("styles.conversationIndexLayout");
    expect(routeAndIndexRailSource).toContain("styles.conversationIndexScrollRegion");
    expect(routeStyles.systemEntryGroup).toContain("border-t");
    expect(routeStyles.systemEntryButton).toContain("grid-cols-[28px_minmax(0,1fr)]");
    expect(routeStyles.systemEntryButton).toContain("border-transparent");
    expect(routeStyles.systemEntryButtonActive).toContain("before:absolute");
  });

  it("uses one lightweight Tailwind grammar for conversation index sections and rows", () => {
    expect(conversationIndexSectionStyles.conversationGroupHeader).toContain("[&_svg]:transition-transform");
    expect(conversationIndexSectionStyles.conversationGroupHeader).toContain("aria-expanded=true");
    expect(conversationIndexSectionStyles.conversationGroupHeader).toContain("min-h-[34px]");
    expect(conversationIndexSectionStyles.conversationGroupHeader).toContain("[&_strong]:tabular-nums");
    expect(conversationIndexSectionStyles.conversationGroupHeader).toContain("[border:0]");
    expect(conversationIndexSectionStyles.conversationGroupHeader).not.toContain("[&_strong]:rounded-full");
    expect(conversationIndexSectionStyles.conversationGroupList).toContain("pl-1");

    expect(directSessionIndexItemStyles.sessionItem).toContain("overflow-hidden");
    expect(directSessionIndexItemStyles.sessionItem).toMatch(/border border-vui-border-subtle|border border-\[var\(--vui-border-subtle\)\]/);
    expect(directSessionIndexItemStyles.sessionItem).toMatch(/!bg-vui-surface-row|!bg-\[var\(--vui-surface-row\)\]/);
    expect(directSessionIndexItemStyles.sessionItemActive).toContain("!bg-[color-mix(in_srgb,var(--accent-cool)_10%");
    expect(directSessionIndexItemStyles.sessionItemActive).not.toContain("shadow-[var(--vui-shadow-inset-accent)]");
    expect(directSessionIndexItemStyles.conversationAvatar).toContain("h-8");
    expect(directSessionIndexItemStyles.sessionItemMain).toContain("min-h-[60px]");
    expect(directSessionIndexItemStyles.sessionItemMain).toContain("grid-cols-[32px_minmax(0,1fr)]");
    expect(directSessionIndexItemStyles.sessionItemMain).toContain("[border:0]");
    expect(directSessionIndexItemStyles.sessionItemMain).toContain("appearance-none");
    expect(directSessionIndexItemStyles.sessionItem).toContain("rounded-[var(--radius-control)]");
    expect(directSessionIndexItemSource).not.toContain("VChip tone=\"accent\"");
    expect(directSessionIndexItemSource).not.toContain("Clock3");
    expect(directSessionIndexItemSource).not.toContain("VChip tone=\"success\"");
    expect(directSessionIndexItemSource).not.toContain("VChip tone=\"warning\"");
    expect(directSessionIndexItemSource).toContain("styles.sessionActivityRunning");
    expect(directSessionIndexItemSource).toContain("styles.sessionActivityApproval");
    expect(directSessionIndexItemStyles).not.toHaveProperty("sessionCurrentBadge");
    expect(directSessionIndexItemStyles.sessionActivityRunning).toContain("h-4");
    expect(directSessionIndexItemStyles.sessionActivityRunning).toContain("state-success");
    expect(directSessionIndexItemStyles.sessionActivityApproval).toContain("state-warning");

    expect(groupSessionIndexItemsStyles.sessionItem).toContain("overflow-hidden");
    expect(groupSessionIndexItemsStyles.sessionItem).toMatch(/border border-vui-border-subtle|border border-\[var\(--vui-border-subtle\)\]/);
    expect(groupSessionIndexItemsStyles.conversationAvatar).toContain("h-8");
    expect(groupSessionIndexItemsStyles.sessionItemMain).toContain("min-h-[60px]");
    expect(groupSessionIndexItemsStyles.sessionItemMain).toContain("grid-cols-[32px_minmax(0,1fr)]");
    expect(groupSessionIndexItemsStyles.sessionItemMain).toContain("[border:0]");
    expect(groupSessionIndexItemsStyles.teamSessionItemMain).toContain("min-h-[3.25rem]");
    expect(groupSessionIndexItemsSource).toContain("VStatusChip");
    expect(groupSessionIndexItemsSource).toContain("sessionStatusChip");
    expect(groupSessionIndexItemsSource).not.toContain("sessionStatusDot");
    expect(groupSessionIndexItemsStyles.sessionStatusChip).toContain("sessionStatusChip");
    expect(groupSessionIndexItemsStyles.teamTreeItem).toContain("overflow-hidden");
    expect(groupSessionIndexItemsStyles.teamTreeItem).toContain("!bg-transparent");
    expect(groupSessionIndexItemsStyles.groupSessionItem).toContain("!bg-transparent");
  });

  it("selects requested direct sessions without waiting for the session index", () => {
    expect(routeSource).toContain("activeSessionIdFromRouteSelection(chatRouteSelection)");
    expect(routeSource).toContain("queryFn: ({ signal }) => fetchSessionDetailWindow(activeSessionId, {");
    expect(routeSource).toContain("enabled: Boolean(activeSessionId) && !isTempSessionId(activeSessionId)");
    // The explicit URL target drives detail loading immediately; no list data is required.
    expect(routeSource).not.toContain("setActiveSession(requestedSessionId)");
    expect(routeSource).not.toContain("useChatWorkbenchStore((state) => state.activeSessionId)");
  });

  it("bootstraps the first-paint catalog once before fallback catalog queries", () => {
    expect(routeSource).toContain('queryKey: ["sessions", "active-bootstrap"]');
    expect(chatApiSource).toContain('fetchJson<ChatWorkbenchBootstrap>("/api/sessions/bootstrap?limit=50"');
    expect(routeSource).toContain("fetchChatWorkbenchBootstrap({ signal })");
    expect(routeSource).toContain("queryClient.setQueryData(queryKeys.agents(), payload.agents)");
    expect(routeSource).toContain("queryClient.setQueryData(queryKeys.conversations(), payload.conversations)");
    expect(routeSource).toContain('queryKeys.sessionQuery("", 50)');
    expect(routeSource).toContain("mergePreservedCreatedSessions");
    expect(routeSource).toContain("Never hard-replace the session index page");
    expect(routeSource).toContain("mergePreservedCreatedSessions");
    expect(routeSource).toContain("Never hard-replace the session index page");
    expect(routeSource).toContain(
      "const bootstrapSettled = activeSessionBootstrapQuery.isFetched || activeSessionBootstrapQuery.isError",
    );
    expect(routeSource).toContain("enabled: secondaryChatDataEnabled && bootstrapSettled");
    expect(routeSource).toContain("bootstrapSettled &&");
    const bootstrapQueryStart = routeSource.indexOf('queryKey: ["sessions", "active-bootstrap"]');
    const sessionIndexCallStart = routeSource.indexOf("const rawSessionsQuery = useSessionIndexQuery");
    expect(bootstrapQueryStart).toBeGreaterThan(0);
    expect(sessionIndexCallStart).toBeGreaterThan(bootstrapQueryStart);
    expect(routeSource).toContain("const sessionIndexQueryEnabled =");
    expect(routeSource).toContain("shouldEnableSessionIndexQuery");
    expect(routeSource).toContain("bootstrapFetchStatus: activeSessionBootstrapQuery.fetchStatus");
    expect(routeSource).toContain("enabled: sessionIndexQueryEnabled");
    // Bare route canonicalization is one-shot, gated on the authoritative directory.
    const canonicalizeEffectStart = routeSource.indexOf(
      "// Bare `/chat` canonicalizes once per location key",
    );
    expect(canonicalizeEffectStart).toBeGreaterThan(0);
    const canonicalizeEffect = routeSource.slice(
      canonicalizeEffectStart,
      routeSource.indexOf("}, [bareRouteBootstrapTarget, canonicalizeBareRoute", canonicalizeEffectStart) + 80,
    );
    expect(canonicalizeEffect).toContain("chatRouteSelection.kind !== \"bare\"");
    expect(canonicalizeEffect).toContain("canonicalizeBareRoute(bareRouteBootstrapTarget)");
    expect(canonicalizeEffect).toContain("if (!routeVisibleSessions)");
  });

  it("loads direct session details as a window and wires top-edge history paging", () => {
    expect(routeAndHelpersSource).toContain("const SESSION_DETAIL_INITIAL_MESSAGE_LIMIT = 40");
    expect(routeAndHelpersSource).toContain("function fetchSessionDetailWindow(");
    expect(routeAndHelpersSource).toContain("fetchSessionDetail(normalizedSessionId, {");
    expect(chatApiSource).toContain("search.set(\"messageLimit\", String(options.messageLimit))");
    expect(chatApiSource).toContain("search.set(\"transcriptScope\", options.transcriptScope)");
    expect(routeSource).toContain("structuralSharing: sessionDetailStructuralSharing");
    expect(routeSource).toContain("export function sessionDetailStructuralSharing(");
    expect(routeAndDetailMutationsSource).toContain("mergeSessionDetailMessageWindow(current, page)");
    expect(routeSource).toContain("const nextDetail = mergeSessionDetailMessageWindow(previous, detail)");
    expect(routeSource).toContain("hasEarlierMessages: Boolean(detail.messageWindow?.hasEarlier)");
    expect(routeSource).toContain("earlierMessagesLoading: loadEarlierSessionMessagesMutation.isPending");
    expect(routeSource).toContain("onLoadEarlierMessages: handleLoadEarlierSessionMessages");
  });

  it("keeps paginated session query caches synchronized with optimistic list mutations", () => {
    expect(routeSource).toContain("updateSessionSummaryCaches(queryClient");
    expect(routeAndLifecycleSource).toContain("captureSessionIndexCacheSnapshots(queryClient)");
    expect(routeAndLifecycleSource).toContain("restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches)");
  });

  it("asks for confirmation before deleting conversations", () => {
    expect(routeAndActionsSource).toContain("openDeleteSessionConfirm(session)");
    expect(routeAndActionsSource).not.toContain("window.confirm(sessionConfirmMessage)");
    expect(routeAndActionsSource).toContain("openClearSessionHistoryConfirm(session)");
    expect(routeAndActionsSource).not.toContain("window.confirm(confirmMessage)");
    expect(routeAndActionsSource).toContain("openDeleteGroupConfirm()");
    expect(routeAndActionsSource).toContain("openResetGroupConfirm()");
    expect(routeAndActionsSource).not.toContain("window.confirm(groupConfirmMessage)");
    expect(chatCodingRouteWorkbenchSource).toContain("ChatDangerConfirmDialog");
    expect(chatCodingRouteWorkbenchSource).toContain("confirmPendingWorkbenchAction");
    expect(chatCodingRouteWorkbenchSource).toContain("useChatWorkbenchConfirmDialog");
    expect(chatWorkbenchConfirmDialogSource).toContain("deleteSessionConfirm");
    expect(chatWorkbenchConfirmDialogSource).toContain("clearSessionHistoryConfirm");
    expect(routeAndActionsSource).toContain("[session.id]: t(\"deleteSessionBusy\")");
    expect(routeAndActionsSource).toContain("alreadyDeletingThisSession");
    expect(routeAndActionsSource).toContain("deleteSessionMutation.variables?.sessionId === session.id");
    expect(routeAndActionsSource).toContain("isBusyPhase(session.currentPhase || session.status)");
    expect(routeSource).toContain('deleteBusyLabel={t("deleteSessionBusy")}');
    expect(directSessionIndexListSource).toContain("deleteBusyLabel");
    expect(directSessionIndexItemSource).toContain("const deleteBusyReason = sessionBusy ? deleteBusyLabel : \"\"");
    expect(chatWorkbenchConfirmDialogSource.indexOf("confirmPendingWorkbenchAction")).toBeLessThan(
      chatWorkbenchConfirmDialogSource.indexOf("deleteSessionMutation.mutate({ sessionId"),
    );
  });

  it("supports bulk session selection and remove in the conversation index rail", () => {
    expect(chatCodingRouteWorkbenchSource).toContain("selectedBulkSessionIds");
    expect(chatCodingRouteWorkbenchSource).toContain("SessionBulkOperationsPanel");
    expect(chatCodingRouteWorkbenchSource).toContain("useChatSessionBulkSelection");
    expect(chatCodingRouteWorkbenchSource).toContain("useChatVisibleSessionCatalog");
    expect(chatCodingRouteWorkbenchSource).toContain("useChatAgentSessionTabs");
    expect(chatCodingRouteWorkbenchSource).toContain("useChatSessionIndexRailModel");
    expect(chatCodingRouteWorkbenchSource).toContain("useChatAgentDirectoryMaps");
    expect(chatCodingRouteWorkbenchSource).toContain("useChatIndexDerivedState");
    expect(chatGroupRoomChromeModelSource).toContain("linkedTeamRoomIds");
    expect(chatGroupRoomChromeModelSource).toContain("activeGroupTeamOwned");
    expect(chatGroupRoomChromeModelSource).toContain("buildChatGroupRoomActionDisabledFlags");
    expect(chatVisibleSessionCatalogSource).toContain("mergeAllVisibleSessions");
    expect(chatVisibleSessionCatalogModelSource).toContain("isVisibleDirectSession");
    expect(chatAgentSessionTabsSource).toContain("buildAgentSessionTabs");
    expect(chatSessionIndexRailPresentationSource).toContain("加载更多会话");
    expect(chatCodingRouteWorkbenchSource).toContain("bulkRemoveSessions");
    expect(chatSessionBulkSelectionSource).toContain("bulkDeleteSessionsMutation");
    expect(chatSessionBulkSelectionSource).toContain('t("bulkRemoveSessionsConfirm")');
    expect(chatSessionBulkSelectionSource).toContain('t("bulkSelectVisibleSessions")');
    expect(sessionBulkOperationsPanelSource).toContain("VConfirmDialog");
    expect(sessionBulkOperationsPanelSource).toContain("AgentBulkActionBar");
    expect(sessionBulkOperationsPanelSource).toContain("if (!hasSelection)");
    expect(sessionBulkOperationsPanelSource).toContain("return null");
    expect(sessionBulkOperationsPanelSource).not.toContain("window.confirm");
    expect(conversationIndexRailSource).toContain("sessionBulkSelectVisibleVisible");
    expect(conversationIndexRailSource).toContain("onSessionBulkSelectVisible");
    expect(conversationIndexRailSource).toContain("panelSearchBulkSelect");
    expect(directSessionIndexItemSource).toContain("bulkSelectionEnabled");
    expect(directSessionIndexItemSource).toContain("onToggleBulk");
    expect(conversationIndexTreeSource).toContain("selectedBulkSessionIds");
    expect(chatSessionBulkModelSource).toContain("sessionBulkDeletable");
    expect(chatApiSource).toContain("bulkDeleteChatSessions");
    expect(chatApiSource).toContain("/api/sessions/bulk-delete");
    const bulkDeleteMutationSource = routeAndLifecycleSource.slice(
      routeAndLifecycleSource.indexOf("const bulkDeleteSessionsMutation"),
    );
    expect(bulkDeleteMutationSource).toContain("bulkDeleteChatSessions");
    expect(bulkDeleteMutationSource).toContain("onMutate: async (variables)");
    expect(bulkDeleteMutationSource).toContain("removeDeletedSessionFromConversations");
  });

  it("reuses the Agent direct-session reset contract for quick history clearing", () => {
    const clearMutationSource = routeAndLifecycleSource.slice(
      routeAndLifecycleSource.indexOf("const clearSessionHistoryMutation"),
      routeAndLifecycleSource.indexOf("const renameSessionMutation"),
    );
    expect(clearMutationSource).toContain("resetAgentDirectSession(agentId, sessionId)");
    expect(clearMutationSource).toContain("removeSessionWorkspace(previousDirectSessionId)");
    expect(clearMutationSource).toContain("replaceIfStillViewing(");
    expect(clearMutationSource).toContain("previousDirectSessionId");
    expect(clearMutationSource).toContain("replacementDirectSessionId");
    expect(clearMutationSource).not.toContain("setActiveSession");
    expect(clearMutationSource).toContain("cancelQueries({ queryKey: queryKeys.session(previousDirectSessionId) })");
    expect(clearMutationSource).toContain("queryKeys.sessionLlmOptions(previousDirectSessionId)");
    expect(clearMutationSource).toContain("afterSessionDeleted");
    expect(clearMutationSource).toContain("chatWorkspaceCache.afterChatWorkspaceReset()");
    expect(routeAndActionsSource).toContain("openClearSessionHistoryConfirm(session)");
    expect(chatWorkbenchConfirmDialogSource).toContain("clearSessionHistoryMutation.mutate({ sessionId: session.id, agentId })");
    expect(chatWorkbenchConfirmDialogSource).toContain('const agentId = String(session.agentId || "").trim()');
    expect(routeSource).toContain("contextMenuSession?.agentId");
    expect(routeSource).toContain("isAgentRootSession(contextMenuSession)");
  });

  it("removes deleted direct sessions from cached lists before refetch", () => {
    const deleteMutationSource = routeAndLifecycleSource.slice(
      routeAndLifecycleSource.indexOf("const deleteSessionMutation"),
    );
    expect(routeSource).toContain("removeDeletedSessionFromConversations");
    expect(deleteMutationSource).toContain("updateSessionSummaryCaches(queryClient");
    expect(deleteMutationSource).toContain("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()");
    expect(routeAndHelpersSource).toContain("conversation.type !== \"direct_agent\"");
    expect(routeAndHelpersSource).toContain("conversation.directSessionId !== deletedSessionId && conversation.conversationId !== deletedSessionId");
    expect(deleteMutationSource.indexOf("updateSessionSummaryCaches(queryClient")).toBeLessThan(
      deleteMutationSource.indexOf("void chatWorkspaceCache.afterSessionDeleted({"),
    );
    expect(deleteMutationSource.indexOf("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()")).toBeLessThan(
      deleteMutationSource.indexOf("void chatWorkspaceCache.afterSessionDeleted({"),
    );
    expect(deleteMutationSource).toContain("deleteChatSession(sessionId)");
    expect(chatApiSource).toContain('method: "DELETE"');
    expect(chatApiSource).toContain('Prefer: "respond-async"');
    expect(deleteMutationSource).toContain("onMutate: async (variables)");
    // cancelQueries must not be awaited — that froze tab switching during delete.
    expect(deleteMutationSource).toContain("void queryClient.cancelQueries({ queryKey: queryKeys.sessions() })");
    expect(deleteMutationSource).not.toContain("await Promise.all([\n        queryClient.cancelQueries({ queryKey: queryKeys.sessions() })");
    expect(deleteMutationSource).toContain("optimisticNextActiveSessionId");
    expect(deleteMutationSource).toContain("replaceIfStillViewing(");
    expect(deleteMutationSource).toContain("requestSessionComposerFocus(optimisticNextActiveSessionId)");
    expect(deleteMutationSource).toContain("requestSessionComposerFocus(nextActiveSessionId)");
    expect(deleteMutationSource).toContain("previousRouteSessionId === variables.sessionId");
    expect(deleteMutationSource).not.toContain("setActiveSession");
    expect(deleteMutationSource).toContain("captureSessionIndexCacheSnapshots(queryClient)");
    expect(deleteMutationSource).toContain("previousConversations");
    expect(deleteMutationSource).toContain("previousAgents");
    expect(deleteMutationSource).toContain("agent.directSessionId === variables.sessionId");
    expect(deleteMutationSource).toContain("queryClient.setQueryData(queryKeys.agents(), context.previousAgents)");
    expect(deleteMutationSource).toContain("restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches)");
    expect(deleteMutationSource).toContain("queryClient.setQueryData(queryKeys.conversations(), context.previousConversations)");
    expect(deleteMutationSource).toContain("chatWorkspaceCache.afterSessionDeleted({");
    expect(deleteMutationSource).not.toContain("void chatWorkspaceCache.afterChatRoomsChanged()");
    expect(deleteMutationSource).not.toContain("void chatWorkspaceCache.afterSessionChanged()");
    expect(chatCodingRouteWorkbenchSource).toContain("composerFocusRequest");
    expect(chatCodingRouteWorkbenchSource).toContain("composerFocusSignal:");
    expect(chatCodingRouteWorkbenchSource).toContain("onComposerFocusRequestSettled:");
    expect(conversationViewSource).toContain("scheduleComposerFocusAttempts");
    expect(conversationViewSource).not.toContain("onComposerFocusRequestSettled?.(focusSignal);\n        return;\n      }\n      if (!shouldApplyComposerFocusRequest");
  });

  it("keeps the active direct session selected when the list is temporarily stale", () => {
    const selectionEffectSource = routeAndSelectionSource.slice(
      routeAndSelectionSource.indexOf("const normalizedSessionId = String(routeSessionId || \"\").trim()"),
      routeAndSelectionSource.length,
    );
    expect(selectionEffectSource).toContain("if (!normalizedSessionId || isTempSessionId(normalizedSessionId))");
    expect(selectionEffectSource).toContain("latestDirectSessionSelectionRef.current = normalizedSessionId");
    expect(selectionEffectSource).not.toContain("setActiveSession(");
    expect(selectionEffectSource).not.toContain("!sessionsQuery.data.some((session) => session.id === activeSessionId)");
    expect(selectionEffectSource).not.toContain("!sessions.some((session) => session.id === activeSessionId)");
  });

  it("keeps explicit missing sessions on their URL with an unavailable surface instead of reconciling away", () => {
    expect(chatApiSource).toContain("function isSessionNotFoundError");
    expect(routeAndHelpersSource).toContain("isSessionNotFoundError");
    expect(chatSessionSelectionSource).toContain("evictUnopenableSessionFromCaches");
    expect(chatSessionDetailHelpersSource).toContain("evictUnopenableSessionFromCaches");
    expect(routeSource).toContain("sessionDetailQuery.isError");
    expect(routeSource).toContain(
      "// Explicit missing/archived session keeps its URL and renders the blocking",
    );
    expect(routeSource).toContain("unavailable surface");
    expect(routeSource).not.toContain("isSessionNotFoundError(sessionDetailQuery.error)");
    expect(routeSource).not.toContain("removeSessionWorkspace(activeSessionId, nextActiveSessionId || null)");
    expect(routeSource).not.toContain("setActiveSession(nextActiveSessionId)");
    expect(routeSource).not.toContain("navigate(`${location.pathname}${nextSearch ? `?${nextSearch}` : \"\"}`, { replace: true })");
    expect(routeSource).toContain("hasBlockingError={sessionDetailErrorState.blockingError}");
  });

  it("keeps renamed direct session titles visible before conversation refetch finishes", () => {
    const renameStart = routeAndLifecycleSource.indexOf("const renameSessionMutation");
    const renameEnd = routeAndLifecycleSource.indexOf("const addSessionToReviewMutation", renameStart);
    const renameMutationSource = routeAndLifecycleSource.slice(renameStart, renameEnd);
    const titleHelperStart = directSessionIndexItemSource.indexOf("export function sessionListTitle");
    const titleHelperEnd = directSessionIndexItemSource.indexOf("function compactAgentIdentifier", titleHelperStart);
    const titleHelperSource = directSessionIndexItemSource.slice(titleHelperStart, titleHelperEnd);
    const titleHelperChildEnd = titleHelperSource.indexOf(").trim();", titleHelperSource.indexOf('if (sessionKind === "child")'));
    const titleHelperRootSource = titleHelperSource.slice(titleHelperChildEnd + 1);
    expect(routeSource).toContain("mergeSessionDetailIntoConversations");
    expect(routeAndLifecycleSource).toContain("renameSessionInSummaries");
    expect(routeAndLifecycleSource).toContain("renameSessionInConversations");
    expect(routeAndLifecycleSource).toContain("renameSessionDetail");
    expect(conversationIndexTreeSource).toContain("DirectSessionIndexList");
    expect(conversationIndexTreeSource).toContain("<DirectSessionIndexList");
    expect(directSessionIndexItemSource).toContain('export function sessionListTitle(');
    expect(directSessionIndexItemSource).toContain('"id" | "title" | "agentDisplayName" | "taskTitle" | "resultCard" | "sessionKind"');
    expect(titleHelperSource).toContain('if (sessionKind === "child")');
    expect(titleHelperSource).toContain("session.taskTitle");
    expect(titleHelperSource).toContain("session.resultCard?.title");
    expect(titleHelperRootSource).toContain("session.title");
    expect(titleHelperRootSource).toContain("session.agentDisplayName");
    expect(titleHelperRootSource).not.toContain("session.taskTitle");
    expect(titleHelperRootSource.indexOf("session.title")).toBeLessThan(titleHelperRootSource.indexOf("session.agentDisplayName"));
    expect(directSessionIndexListSource).toContain("title: conversation.title");
    expect(directSessionIndexListSource).toContain("agentDisplayName: conversation.agentDisplayName");
    expect(directSessionIndexListSource).toContain("buildDirectSessionIndexViewModel");
    expect(directSessionIndexListSource).toContain("const sessionView = buildDirectSessionIndexViewModel");
    expect(directSessionIndexListSource).toContain("conversationToSessionSummary");
    expect(directSessionIndexListSource).toContain("sessionComposerErrors[session.id]");
    expect(directSessionIndexItemSource).toContain("const sessionAgentMeta = sessionAgentMetaLabel(session)");
    expect(directSessionIndexItemSource).toContain("export function sessionAgentMetaLabel");
    expect(directSessionIndexItemSource).toContain("return \"\";");
    expect(directSessionIndexItemSource).toContain("export function showSessionFunctionLabel");
    expect(directSessionIndexItemSource).toContain("sessionModelTooltip");
    expect(directSessionIndexItemSource).toContain("sessionModelBadgeLabel");
    expect(directSessionIndexItemSource).toContain("showSessionSummaryInline");
    expect(directSessionIndexItemSource).not.toContain('label === "会话入口"');
    expect(directSessionIndexItemSource).toContain("const sessionTitle = sessionListTitle(session) || sessionDisplay.name");
    expect(routeAndHelpersSource).toContain("agentDisplayName: title");
    expect(routeAndLifecycleSource).toContain("targetSession");
    expect(directSessionIndexItemSource).toContain("{sessionTitle}");
    expect(renameMutationSource).toContain("onMutate: (variables) =>");
    expect(renameMutationSource).toContain("setEditingSessionId(null)");
    expect(renameMutationSource).toContain("updateSessionSummaryCaches(queryClient");
    expect(renameMutationSource).toContain("captureSessionIndexCacheSnapshots(queryClient)");
    expect(renameMutationSource).toContain("restoreSessionIndexCacheSnapshots(queryClient, context?.previousSessionIndexCaches)");
    expect(renameMutationSource).toContain("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()");
    expect(renameMutationSource).toContain("queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId)");
    expect(renameMutationSource).toContain("setEditingSessionId(variables.sessionId)");
    expect(renameMutationSource).toContain("setEditingSessionTitle(variables.title)");
    expect(renameMutationSource.indexOf("updateSessionSummaryCaches(queryClient")).toBeLessThan(
      renameMutationSource.indexOf("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()"),
    );
    expect(renameMutationSource.indexOf("queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations()")).toBeLessThan(
      renameMutationSource.indexOf("onError:"),
    );
    expect(renameMutationSource).toContain("const confirmedTitle =");
    expect(renameMutationSource).toContain("const confirmedUpdatedAt =");
    expect(renameMutationSource).not.toContain("mergeSessionDetailIntoSummaries(sessions, nextDetail)");
    expect(renameMutationSource).not.toContain("mergeSessionDetailIntoConversations(conversations, nextDetail)");
    expect(renameMutationSource).not.toContain("syncSessionDetail(nextDetail)");
    expect(renameMutationSource).not.toContain("void chatWorkspaceCache.afterSessionChanged({ sessionId: variables.sessionId })");
    expect(renameMutationSource).not.toContain("void chatWorkspaceCache.refreshSessionRuntime(variables.sessionId)");
  });

  it("classifies direct conversations from explicit conversation index metadata", () => {
    expect(conversationIndexModelSource).toContain("agentPrimaryMode: session.agentPrimaryMode");
    expect(conversationIndexModelSource).toContain("agentRoleKey: session.agentRoleKey");
    expect(conversationIndexModelSource).toContain("agentPromptTemplateId: session.agentPromptTemplateId");
    expect(conversationIndexModelSource).toContain("conversationIndexKind: session.conversationIndexKind");
    expect(conversationIndexModelSource).toContain("conversationIndexKind: classification.kind");
    expect(conversationIndexModelSource).toContain("const kind = normalizeConversationIndexKind(conversation.conversationIndexKind)");
    expect(conversationIndexModelSource).toContain("kind === CONVERSATION_INDEX_KIND_PERSONAL_AGENT");
    expect(conversationIndexModelSource).toContain("kind === CONVERSATION_INDEX_KIND_TEAM_AGENT");
    expect(conversationIndexModelSource).not.toContain("primaryMode === \"research\"");
    expect(conversationIndexModelSource).not.toContain("roleKey.startsWith(\"research_\")");
    expect(conversationIndexModelSource).not.toContain("promptTemplateId.startsWith(\"prompt-research-\")");
  });

  it("routes ChatCoding route controls through VUI primitives", () => {
    expect(routeSource).toContain('from "../../components/vui"');
    expect(routeAndIndexRailSource).toContain("<VButton");
    expect(routeAndIndexRailSource).toContain("<VNativeInput");
    expect(routeAndIndexRailSource).toContain("<VStringSelect");
    expect(routeAndIndexRailSource).not.toContain("<VNativeSelect");
    expect(routeSource).not.toMatch(/<button\b/);
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
  });

  it("keeps the Agent model fixed while mutating only Session reasoning effort", () => {
    expect(routeAndDetailMutationsSource).toContain("const sessionReasoningEffortMutation = useMutation");
    expect(routeAndDetailMutationsSource).toContain("updateSessionReasoningEffort(variables.sessionId, variables.reasoningEffort)");
    expect(chatApiSource).toContain("/reasoning-effort");
    expect(chatApiSource).toContain("JSON.stringify({ reasoningEffort })");
    expect(routeSource).toContain("model: sessionLlmOptions.model");
    expect(routeSource).toContain("onReasoningEffortChange");
    expect(routeSource).not.toContain("/llm-selection");
    expect(routeSource).not.toContain("onSelectionChange");
  });

  it("requests authoritative session refresh when the session stream errors", () => {
    const sessionStreamStart = routeAndStreamSource.indexOf(
      "const stream = new EventSource(`/api/sessions/${streamSessionId}/events?initial=none`)",
    );
    const onErrorStart = routeAndStreamSource.indexOf("stream.onerror = () => {", sessionStreamStart);
    const onErrorEnd = routeAndStreamSource.indexOf("function handleSessionDetail", onErrorStart);
    const onErrorSource = routeAndStreamSource.slice(onErrorStart, onErrorEnd);

    expect(onErrorSource).toContain("if (!disposed)");
    expect(onErrorSource).toContain('applyPendingAssistantDeltas("close")');
    expect(onErrorSource).toContain("assistantDeltaScheduler.pendingCount");
    expect(onErrorSource).toContain("queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId) })");
    expect(onErrorSource).toContain('eventCode: "browser.session_stream.authoritative_refresh_requested"');
    expect(onErrorSource).toContain("sessionId: streamSessionId");
    expect(onErrorSource).toContain("readyState: stream.readyState");
    expect(onErrorSource).toContain("pendingAssistantDeltaCount");
    expect(onErrorSource.indexOf('applyPendingAssistantDeltas("close")')).toBeLessThan(
      onErrorSource.indexOf("queryClient.invalidateQueries"),
    );
    expect(onErrorSource).not.toContain("setTimeout");
    expect(onErrorSource).not.toMatch(/setActiveTurnLayersBySession[\s\S]*failed/);
  });
});
it("defers secondary direct-session queries until startup detail is ready", () => {
  expect(chatWorkbenchCatalogQueriesSource).toContain("bootstrapSettled &&");
  expect(chatWorkbenchCatalogQueriesSource).toContain(
    "(secondaryChatDataEnabled || sessionIndexQueryEnabled || groupComposerOpen || standardGroupRoomActive),",
  );
  expect(routeSource).toContain("enabled: secondaryChatDataEnabled && Boolean(activeSessionId),");
  expect(routeSource).toContain(
    "enabled: secondaryChatDataEnabled && Boolean(activeRootSessionId) && directSessionPanelActive,",
  );
});
