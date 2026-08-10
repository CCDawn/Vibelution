import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ChatNextStateSignalSummary, ConversationMessage, SessionTurnError } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread";
import { dictionary } from "../../i18n/dictionary";
import { AgentContextSectionsView } from "./AgentContextSectionsView";
import { buildAgentMessageRenderState } from "./agentMessageRenderState";
import styles from "./ConversationView.styles";
import agentMessageRenderStateSource from "./agentMessageRenderState.ts?raw";
import conversationViewStylesModuleSource from "./ConversationView.styles.ts?raw";
import conversationOperationDetailsSource from "./ConversationOperationDetails.tsx?raw";
import conversationStreamingResponseContentSource from "./ConversationStreamingResponseContent.tsx?raw";
import conversationTurnAvatarContentSource from "./ConversationTurnAvatarContent.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
import conversationInlineMarkdownSource from "./conversationInlineMarkdown.tsx?raw";
import { ConversationView } from "./ConversationView";
import type { ConversationProcessDisplayMode } from "./conversationViewTypes";
import { shouldShowNextStateSignalInConversation } from "./conversationNextStateSignal";
import { isAgentInboxMessage } from "./conversationMessagePredicates";

// Server-rendered integration tests must exercise the loaded Markdown renderer.
// Production keeps it lazy so the initial ConversationView chunk stays small.
vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

const conversationViewStylesSource = [
  conversationViewStylesModuleSource,
  ...Object.keys(styles).map((key) => `.${key}`),
  ...Object.values(styles),
].join("\n");

function semanticArticleClassCount(html: string, className: string) {
  const escaped = className.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return html.match(new RegExp(`<article class="[^"]*(?:\\s|^)${escaped}(?:\\s|")`, "g"))?.length ?? 0;
}

function renderConversation(
  messages: ConversationMessage[],
  options: {
    editingMessageId?: string;
    editUserMessageDisabled?: boolean;
    composerValue?: string;
    density?: "default" | "compact";
    nextStateSignals?: ChatNextStateSignalSummary[];
    userAvatarPreset?: string;
    userAvatarImageUrl?: string;
    userDisplayName?: string;
    assistantDisplayName?: string;
    assistantAvatarImageUrl?: string;
    assistantAvatarFallback?: string;
    resolveTurnAvatar?: (message: ConversationMessage) => { imageUrl?: string; fallback: string } | undefined;
    composerAttachments?: Array<{
      id: string;
      filename: string;
      previewUrl: string;
      sizeBytes: number;
      contentType: string;
    }>;
    onRemoveComposerAttachment?: (id: string) => void;
    composerReferences?: Array<{
      referenceId: string;
      kind: string;
      sessionId: string;
      title?: string;
      agentDisplayName?: string;
    }>;
    composerDisabled?: boolean;
    composerActionMode?: "send" | "stop";
    composerActionDisabled?: boolean;
    submitLabel?: string;
    composerError?: string;
    composerGuidance?: string;
    composerModeNotice?: string;
    composerModeTargetPreview?: string;
    cancelComposerModeLabel?: string;
    turnError?: SessionTurnError | null;
    onSafeGuidance?: () => void;
    onInterruptGuidance?: () => void;
    onCancelComposerMode?: () => void;
    showMentalSnapshots?: boolean;
    showComposer?: boolean;
    processDisplayMode?: ConversationProcessDisplayMode;
    useDefaultProcessDisplayMode?: boolean;
    activeTurnMessage?: ConversationMessage;
    slashCommandSuggestions?: Array<{
      directoryName: string;
      name?: string;
      command: string;
      description?: string;
    }>;
  } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
  const processDisplayProps = options.useDefaultProcessDisplayMode
    ? {}
    : { processDisplayMode: options.processDisplayMode ?? ("trace" as ConversationProcessDisplayMode) };
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ConversationView
        sessionId="session-1"
        title="Session"
        phase="ready"
        messages={messages}
        activeTurnMessage={options.activeTurnMessage}
        density={options.density}
        showHeader={false}
        showSessionOverview={false}
        showMentalSnapshots={options.showMentalSnapshots}
        showComposer={options.showComposer}
        {...processDisplayProps}
        composerValue={options.composerValue ?? ""}
        composerPlaceholder="Type"
        composerDisabled={options.composerDisabled ?? false}
        composerActionMode={options.composerActionMode}
        composerActionDisabled={options.composerActionDisabled}
        composerPending={false}
        submitLabel={options.submitLabel}
        composerError={options.composerError}
        composerGuidance={options.composerGuidance}
        composerModeNotice={options.composerModeNotice}
        composerModeTargetPreview={options.composerModeTargetPreview}
        cancelComposerModeLabel={options.cancelComposerModeLabel}
        turnError={options.turnError}
        composerAttachments={options.composerAttachments}
        onRemoveComposerAttachment={options.onRemoveComposerAttachment}
        composerReferences={options.composerReferences}
        slashCommandSuggestions={options.slashCommandSuggestions}
        nextStateSignals={options.nextStateSignals}
        userAvatarPreset={options.userAvatarPreset}
        userAvatarImageUrl={options.userAvatarImageUrl}
        userDisplayName={options.userDisplayName}
        assistantDisplayName={options.assistantDisplayName}
        assistantAvatarImageUrl={options.assistantAvatarImageUrl}
        assistantAvatarFallback={options.assistantAvatarFallback}
        resolveTurnAvatar={options.resolveTurnAvatar}
        editingMessageId={options.editingMessageId}
        editUserMessageDisabled={options.editUserMessageDisabled}
        editUserMessageLabel="Edit and resend"
        defaultFileContext="workspace"
        onComposerChange={() => undefined}
        onSubmit={() => undefined}
        onSafeGuidance={options.onSafeGuidance}
        onInterruptGuidance={options.onInterruptGuidance}
        onCancelComposerMode={options.onCancelComposerMode}
        onEditUserMessage={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationView VUI control contract", () => {
  it("routes conversation controls through VUI primitives", () => {
    expect(conversationViewSource).toContain('from "../vui"');
    expect(conversationViewSource).toContain("<VButton");
    expect(conversationViewSource).toContain("<VNativeInput");
    expect(conversationViewSource).toContain("<VNativeTextarea");
    expect(conversationViewSource).not.toMatch(/<button\b/);
    expect(conversationViewSource).not.toMatch(/<input\b/);
    expect(conversationViewSource).not.toMatch(/<select\b/);
    expect(conversationViewSource).not.toMatch(/<textarea\b/);
  });
});

describe("ConversationView Codex-like transcript adapter integration", () => {
  it("builds codex transcript cells from the AgentMessage projection before rendering turns", () => {
    expect(conversationViewSource).toContain('from "./codexTranscriptCells"');
    expect(conversationViewSource).toContain("buildCodexTranscriptCells(");
    expect(conversationViewSource).toContain("agentCodexSurfacesByMessageId");
    expect(conversationViewSource).toContain("data-codex-transcript-cell-count");
  });});

describe("ConversationView edit resend affordance", () => {
  it("does not force-collapse thinking sections when streaming settles", () => {
    expect(conversationViewSource).not.toContain("previousStreamingRef");
    expect(conversationViewSource).not.toContain("thought: false,\n          mental: false,\n          tools: false");
  });

  it("freezes first-seen expansion defaults so SSE status changes do not fight the UI", () => {
    expect(conversationViewSource).toContain("defaultExpansionRef");
    expect(conversationViewSource).toContain("messageDefaults[section] === undefined");
    expect(conversationViewSource).toContain("return messageDefaults[section]");
  });
  it("does not reintroduce a fixed-rate typewriter buffer for live assistant deltas", () => {
    expect(conversationViewSource).not.toContain("STREAMING_REVEAL_INTERVAL_MS");
    expect(conversationViewSource).not.toContain("STREAMING_REVEAL_FAST_FORWARD_BACKLOG_CHARS");
    expect(conversationViewSource).not.toContain("setTimeout(pump");
    expect(conversationViewSource).not.toContain("advanceStreamingRevealText");
    expect(conversationViewSource).not.toContain("setInterval");
  });

  it("keeps answer and process toggles as borderless text controls", () => {
    expect(styles.responseToggle).toContain("border-0");
    expect(styles.responseToggle).toContain("bg-transparent");
    expect(styles.responseToggle).toContain("p-0");
    expect(styles.answerOnlyProcessToggle).toContain("border-0");
    expect(styles.answerOnlyProcessToggle).toContain("bg-transparent");
    expect(styles.answerOnlyProcessToggle).toContain("p-0");
  });

  it("keeps VUI button slot wrappers transparent for process and answer text controls", () => {
    expect(styles.answerOnlyProcessToggle).toContain("[&_[data-slot=vui-button-content]]:contents");
    expect(styles.answerOnlyProcessToggle).toContain("[&_[data-slot=vui-button-label]]:inline-grid");
    expect(styles.answerOnlyProcessToggle).toContain("grid-cols-[14px_auto_auto_minmax(0,1fr)_14px]");
    expect(styles.answerOnlyProcessToggle).toContain("max-w-full");
    expect(styles.answerOnlyProcessStatic).toContain("grid-cols-[14px_auto_auto]");
    expect(styles.responseToggle).toContain("!grid");
    expect(styles.responseToggle).toContain("!w-full");
    expect(styles.responseToggle).toContain("!justify-start");
    expect(styles.responseToggle).toContain("!text-left");
    expect(styles.responseToggle).toContain("[&_[data-slot=vui-button-content]]:contents");
    expect(styles.responseToggle).toContain("[&_[data-slot=vui-button-label]]:contents");
  });

  it("lays out static request status icon and text on one row", () => {
    expect(styles.answerOnlyProcessStatic).toContain(" grid-cols-[14px_auto_auto]");
    expect(styles.answerOnlyProcessStatic).toContain(" items-center");
    expect(styles.answerOnlyProcessStatic).toContain(" gap-1.5");
    expect(styles.answerOnlyProcessStatic).not.toContain("[&_[data-slot=vui-button-label]]");
  });

  it("keeps the latest compact process prompt on one visual line", () => {
    expect(styles.answerOnlyProcessTitle).toContain("truncate");
    expect(styles.answerOnlyProcessTitle).toContain("whitespace-nowrap");
    expect(styles.answerOnlyProcessMeta).toContain("truncate");
    expect(styles.answerOnlyProcessMeta).toContain("whitespace-nowrap");
    expect(styles.answerOnlyProcessPreview).toContain("truncate");
    expect(styles.answerOnlyProcessPreview).toContain("whitespace-nowrap");
    expect(styles.answerOnlyProcessPreview).not.toContain("whitespace-normal");
    expect(styles.answerOnlyProcessPreview).not.toContain("[overflow-wrap:anywhere]");
  });

  it("keeps the back-to-bottom control floating and content-sized", () => {
    expect(styles.surface).toContain("relative");
    expect(styles.backToBottomButton).toContain("absolute");
    expect(styles.backToBottomButton).toContain("bottom-[calc(var(--vui-control-height-md)_+_18px)]");
    expect(styles.backToBottomButton).toContain("left-1/2");
    expect(styles.backToBottomButton).toContain("-translate-x-1/2");
    expect(styles.backToBottomButton).toContain("z-20");
    expect(styles.backToBottomButton).toContain("!inline-flex");
    expect(styles.backToBottomButton).toContain("!w-fit");
    expect(styles.backToBottomButton).toContain("max-w-[calc(100%_-_24px)]");
    expect(styles.backToBottomButton).toContain("[&_[data-slot=vui-button-content]]:!inline-flex");
    expect(styles.backToBottomButton).toContain("[&_[data-slot=vui-button-label]]:!inline-flex");
    expect(styles.backToBottomButton).not.toContain("!w-full");
  });

  it("keeps conversation timeline previews wrapped and button slots flat", () => {
    expect(styles.timeline).toContain("overflow-y-auto");
    expect(styles.timeline).toContain("overflow-x-hidden");
    expect(styles.timeline).not.toContain("overflow-auto");
    expect(styles.timelineCellHeader).toContain("!items-start");
    expect(styles.timelineCellHeader).not.toContain("!items-center");
    expect(styles.timelineCellHeader).toContain("!grid");
    expect(styles.timelineCellHeader).toContain("!w-full");
    expect(styles.timelineCellHeader).toContain("grid-cols-[20px_minmax(0,1fr)]");
    expect(styles.timelineCellHeader).not.toContain("grid-cols-[20px_minmax(0,1fr)_24px]");
    expect(styles.timelineCellHeader).not.toContain("_max-content_");
    expect(styles.timelineCellHeader).toContain("gap-x-2");
    expect(styles.timelineCellHeader).toContain("border-0");
    expect(styles.timelineCellHeader).toContain("bg-transparent");
    expect(styles.timelineCellHeader).toContain("p-0");
    expect(styles.timelineCellHeader).toContain("justify-start");
    expect(styles.timelineCellHeader).toContain("text-left");
    expect(styles.timelineCellHeader).toContain("shadow-none");
    expect(styles.timelineCellHeader).toContain("hover:!bg-transparent");
    expect(styles.timelineCellHeader).toContain("[&_[data-slot=vui-button-content]]:contents");
    expect(styles.timelineCellHeader).toContain("[&_[data-slot=vui-button-label]]:contents");
    expect(styles.timelineCellPreview).toContain("whitespace-normal");
    expect(styles.timelineCellPreview).toContain("[overflow-wrap:anywhere]");
    expect(styles.timelineCellPreview).toContain("line-clamp-2");
    expect(styles.timelineCellPreview).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.timelineCellPreview).not.toContain("[font-size:var(--vui-font-xs)]");
    // Codex-aligned tool chrome keeps titles muted/small; pills own the primary action label.
    expect(styles.timelineCellTitle).toContain("[font-size:var(--vui-font-xs)]");
    expect(styles.timelineCellTitle).toContain("font-normal");
    expect(styles.operationItem).not.toContain("860px");
    expect(styles.operationItem).toContain("w-[min(100%,72ch)]");
    expect(styles.operationItem).toContain("!rounded-none");
    expect(styles.operationItem).toContain("!border-0");
    expect(styles.operationItem).not.toContain("border-b ");
    expect(styles.operationItem).toContain("!bg-transparent");
    expect(styles.operationItem).toContain("!text-[var(--fg-secondary)]");
    expect(styles.operationItem).toContain("!p-0");
    expect(styles.operationItem).toContain("pb-1");
    expect(styles.operationStatus).toContain("justify-self-start");
  });

  it("top-aligns process disclosure rows while answer toggles keep centered labels", () => {
    expect(styles.timelineCellHeader).toContain("!items-start");
    expect(styles.answerOnlyProcessToggle).toContain("[&_[data-slot=vui-button-label]]:items-center");
    expect(styles.responseToggle).toContain("!items-center");
  });

  it("keeps timeline status meta aligned to the top of multi-line operation rows", () => {
    expect(styles.timelineCellHeader).toContain("!items-start");
    expect(styles.timelineCellTitleRow).toContain("inline-flex");
    expect(styles.timelineCellTitleRow).toContain("items-baseline");
    expect(styles.timelineCellTitleRow).toContain("gap-2");
    expect(styles.timelineCellMeta).toContain("inline-flex");
    expect(styles.timelineCellMeta).toContain("align-baseline");
    expect(styles.timelineCellMeta).toContain("whitespace-nowrap");
    expect(styles.timelineCellMeta).not.toContain("justify-self-end");
    expect(styles.timelineCellMeta).not.toContain("text-right");
    expect(styles.timelineCellMeta).not.toContain("max-w-[min(30ch,34vw)]");
    expect(styles.timelineCellMeta).toContain("text-[var(--fg-tertiary)]");
    expect(styles.timelineCellDetailButton).toContain("self-start");
  });
  it("keeps expanded process details out of nested card chrome", () => {
    expect(styles.answerOnlyProcessGroup).toContain("w-full");
    expect(styles.answerOnlyProcessGroup).toContain("max-w-full");
    expect(styles.answerOnlyProcessGroup).toContain("bg-transparent");
    expect(styles.answerOnlyProcessGroup).toContain("shadow-none");
    expect(styles.answerOnlyProcessGroup).not.toContain("rounded-[var(--radius-control)]");
    expect(styles.answerOnlyProcessGroup).not.toContain("bg-[color-mix(in_srgb,var(--surface-panel)_58%,transparent)]");
  });

  it("keeps the session summary as a single-layer metrics grid", () => {
    const summaryGridTokens = styles.summaryGrid.split(/\s+/);
    const summaryCardTokens = styles.summaryCard.split(/\s+/);
    const summaryLabelTokens = styles.summaryLabel.split(/\s+/);
    const summaryValueTokens = styles.summaryValue.split(/\s+/);

    expect(styles.summaryGrid).toContain("grid-cols-[repeat(auto-fit,minmax(min(100%,9rem),1fr))]");
    expect(summaryGridTokens).not.toContain("border");
    expect(styles.summaryGrid).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(styles.summaryGrid).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(summaryGridTokens).not.toContain("p-2");
    expect(styles.summaryCard).toContain("rounded-[var(--radius-panel)]");
    expect(styles.summaryCard).toContain("border border-[color-mix(in_srgb,var(--vui-border-strong)_68%,transparent)]");
    expect(styles.summaryCard).toContain("bg-[var(--vui-surface-raised)]");
    expect(styles.summaryCard).not.toContain("white)");
    expect(styles.summaryCard).toContain("shadow-none");
    expect(summaryCardTokens).toEqual(expect.arrayContaining(["flex", "flex-col", "gap-1"]));
    expect(summaryLabelTokens).not.toContain("border");
    expect(summaryLabelTokens).not.toContain("p-2");
    expect(styles.summaryValue).toContain("whitespace-normal");
    expect(styles.summaryValue).toContain("break-words");
    expect(styles.summaryValue).toContain("[overflow-wrap:anywhere]");
    expect(summaryValueTokens).not.toContain("border");
    expect(summaryValueTokens).not.toContain("p-2");
  });

  it("renders live process previews as inline log text instead of white nested cards", () => {
    const inlinePreviewRules = [
      styles.answerOnlyProcessPreview,
      styles.operationItemWrap,
      styles.operationSummaryPreview,
      styles.operationSummaryText,
      styles.timelineCellPreview,
    ];

    for (const className of inlinePreviewRules) {
      expect(className).toContain("bg-transparent");
      expect(className).toContain("border-0");
      expect(className).toContain("shadow-none");
      expect(className).not.toContain("bg-[var(--vui-surface-glass)]");
      expect(className).not.toMatch(/bg-vui-surface-row|bg-\[var\(--vui-surface-row\)\]/);
      expect(className).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    }

    expect(styles.answerOnlyProcessGroup_running).toContain("text-[var(--fg-secondary)]");
    expect(styles.answerOnlyProcessGroup_running).not.toContain("text-[var(--state-success)]");
    expect(styles.timelineCellPreview).toContain("line-clamp-2");
    expect(styles.operationSummaryText).toContain("line-clamp-1");
  });

  it("uses readable contrast for compact conversation metadata and toggles", () => {
    const readableRules = [
      ".turnMeta",
      ".turnMetaActions",
      ".turnIconButton",
      ".operationSummaryPreview",
      ".operationSummaryCount",
      ".answerOnlyProcessToggle",
      ".answerOnlyProcessTitle",
      ".answerOnlyProcessMeta",
      ".answerOnlyProcessPreview",
      ".timelineCellHeader",
      ".timelineCellPreview",
      ".timelineCellMeta",
      ".responseToggle",
    ];

    for (const selector of readableRules) {
      const key = selector.slice(1);
      expect(styles[key]).toBeTypeOf("string");
    }

    expect(styles.responseToggle).toContain("text-[var(--fg-secondary)]");
    expect(styles.answerOnlyProcessToggle).toContain("text-[var(--fg-secondary)]");
  });

  it("keeps message turn skeletons structural instead of nested row cards", () => {
    for (const skeletonClass of [
      styles.assistantTurn,
      styles.agentInboxTurn,
      styles.groupTranscriptTurn,
      styles.userTurn,
      styles.assistantTurnContinuation,
      styles.turnContent,
      styles.turnMeta,
      styles.turnMetaIdentity,
      styles.turnMetaActions,
      styles.turnSpeaker,
      styles.turnAvatar,
      styles.turnAvatarImage,
    ]) {
      expect(skeletonClass).not.toMatch(/bg-vui-surface-row|bg-\[var\(--vui-surface-row\)\]/);
      expect(skeletonClass).not.toContain("border border-[var(--vui-border-subtle)]");
      expect(skeletonClass).not.toMatch(/(?:^|\s)p-2(?:\s|$)/);
    }

    expect(styles.timeline).toContain("px-[clamp(1rem,3vw,3rem)]");
    expect(styles.timeline).not.toContain("px-3");
    expect(styles.surfaceCompact).not.toContain("[&_.timeline]:px-3");
    expect(styles.assistantTurn).toContain("w-full max-w-[830px]");
    expect(styles.assistantTurn).toContain("justify-self-center");
    expect(styles.assistantTurn).toContain("grid-cols-[2rem_minmax(0,1fr)]");
    expect(styles.assistantTurn).not.toContain("[&_.turnAvatar]:hidden");
    expect(styles.assistantTurn).not.toContain("[&_.turnMeta]:hidden");
    expect(styles.agentInboxTurn).toContain("w-full max-w-[830px]");
    expect(styles.agentInboxTurn).toContain("justify-self-center");
    expect(styles.groupTranscriptTurn).toContain("w-full max-w-[830px]");
    expect(styles.groupTranscriptTurn).toContain("justify-self-center");
    expect(styles.userTurn).toContain("w-full max-w-[830px]");
    expect(styles.userTurn).toContain("justify-self-center");
    expect(styles.userTurn).toContain("grid-cols-[minmax(0,1fr)_2rem]");
    expect(styles.userTurn).not.toContain("[&_.turnAvatar]:hidden");
    expect(styles.userTurn).not.toContain("[&_.turnSpeaker]:hidden");
    expect(styles.userTurn).toContain("[&_.turnContent]:w-fit");
    expect(styles.userTurn).toContain("[&_.turnContent]:max-w-[min(76%,640px)]");
    expect(styles.userTurn).toContain("max-[719px]:[&_.turnContent]:max-w-[min(88%,36rem)]");
    expect(styles.assistantTurnContinuation).toContain("[&_.turnContent]:w-full");
    expect(styles.assistantTurnContinuation).not.toContain("[&_.turnAvatar]:hidden");
    expect(styles.assistantTurnContinuation).not.toContain("[&_.turnMeta]:hidden");
    expect(conversationViewSource).toContain("compactHeader={false}");
    expect(conversationViewSource).not.toContain("compactTurnHeader\n                    ? null");
    expect(styles.turnContent).toContain("gap-[5px]");
    expect(styles.turnMeta).toContain("inline-flex");
    expect(styles.turnSpeaker).toContain("truncate");
    expect(styles.turnAvatarImage).toContain("object-cover");
    expect(styles.responseSegment_answer).toContain("[&_.responseSegmentHeader]:hidden");
  });

  it("restores chat message affordances inside semantic message bodies", () => {
    expect(styles.userMessageBody).toContain("justify-self-end");
    expect(styles.userMessageBody).toContain("w-fit");
    expect(styles.userMessageBody).toContain("max-w-full");
    expect(styles.userMessageBody).toContain("rounded-[16px]");
    expect(styles.userMessageBody).toContain("border-0");
    expect(styles.userMessageBody).toContain("bg-[var(--vui-control-muted)]");
    expect(styles.userMessageBody).toContain("px-3");
    expect(styles.userMessageBody).toContain("py-2");
    expect(styles.userMessageBody).toContain("shadow-none");
    expect(styles.userMessageBody).toContain("text-left");

    expect(styles.responseSection).toContain("w-full");
    expect(styles.responseSection).toContain("max-w-full");
    expect(styles.responseSection).not.toContain("justify-self-stretch");
    expect(styles.responseSection).toContain("border-l");
    expect(styles.responseSection).toContain("bg-transparent");
    expect(styles.responseSection).not.toContain("bg-[var(--vui-surface-chat-panel)]");
    expect(styles.responseSection).not.toContain("rounded-[var(--radius-panel)]");
    expect(styles.responseSection).not.toContain("white)");
    expect(styles.responseSection).toContain("pl-2.5");
    expect(styles.responseSection).toContain("shadow-none");
    expect(styles.responseBody).toContain("border-0");
    expect(styles.responseBody).toContain("bg-transparent");
    expect(styles.responseBody).toContain("pl-5");
    expect(styles.responseBody).toContain("shadow-none");
    expect(styles.responseBody).not.toContain("bg-[color-mix(in_srgb,var(--surface-panel)_66%,transparent)]");

    expect(styles.answerOnlyProcessGroup).toContain("w-full");
    expect(styles.answerOnlyProcessGroup).toContain("max-w-full");
    expect(styles.answerOnlyProcessGroup).toContain("bg-transparent");
    expect(styles.answerOnlyProcessGroup).toContain("shadow-none");
    expect(styles.answerOnlyProcessGroup).toContain("p-0");
  });

  it("keeps visible message shell styles as named Tailwind slices", () => {
    expect(conversationViewStylesModuleSource).toContain("const conversationViewScope");
    expect(conversationViewStylesModuleSource).toContain("const readableMessageText");
    expect(conversationViewStylesModuleSource).toContain("const assistantResponseSection");
    expect(conversationViewStylesModuleSource).toContain("const assistantResponseBody");
    expect(conversationViewStylesModuleSource).toContain("const answerOnlyProcessShell");
    expect(conversationViewStylesModuleSource).toContain("const userMessageBubble");
    expect(conversationViewStylesModuleSource).toContain("responseSection: assistantResponseSection");
    expect(conversationViewStylesModuleSource).toContain("responseBody: assistantResponseBody");
    expect(conversationViewStylesModuleSource).toContain("answerOnlyProcessGroup: answerOnlyProcessShell");
    expect(conversationViewStylesModuleSource).toContain("userMessageBody: userMessageBubble");
  });

  it("keeps composer and send controls as named Tailwind slices", () => {
    expect(conversationViewStylesModuleSource).toContain("const conversationComposerShell");
    expect(conversationViewStylesModuleSource).toContain("const composerFieldShell");
    expect(conversationViewStylesModuleSource).toContain("const composerFieldDragActiveShell");
    expect(conversationViewStylesModuleSource).toContain("const composerRoundActionButton");
    expect(conversationViewStylesModuleSource).toContain("const composerPrimaryActionButton");
    expect(conversationViewStylesModuleSource).toContain("const composerSendActionButton");
    expect(conversationViewStylesModuleSource).toContain("composer: conversationComposerShell");
    expect(conversationViewStylesModuleSource).toContain("composerField: composerFieldShell");
    expect(conversationViewStylesModuleSource).toContain("composerFieldDragActive: composerFieldDragActiveShell");
    expect(styles.composer).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(styles.composerActionStack).toContain("grid-cols-1");
    expect(styles.composerActionStack).toContain("content-end");
    expect(styles.composerActionStack).toContain("gap-1");
    expect(conversationViewStylesModuleSource).toContain("composerRoundButton: composerRoundActionButton");
    expect(conversationViewStylesModuleSource).toContain("composerRoundButtonPrimary: composerPrimaryActionButton");
    expect(conversationViewStylesModuleSource).toContain("sendButton: composerSendActionButton");
    expect(styles.attachButton).toContain("focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)]");
    expect(styles.attachButton).toContain("active:bg-[color-mix(in_srgb,var(--vui-surface-workspace)_18%,var(--vui-control-muted-hover))]");
    expect(styles.attachButton).toContain("disabled:hover:bg-[color-mix(in_srgb,var(--vui-control-muted)_62%,transparent)]");
    expect(styles.composerRoundButton).toContain("border-[color-mix(in_srgb,var(--border-soft)_70%,transparent)]");
    expect(styles.composerRoundButton).toContain("hover:bg-[color-mix(in_srgb,var(--vui-surface-workspace)_14%,var(--vui-control-muted-hover))]");
    expect(styles.composerRoundButton).toContain("active:border-[color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))]");
    expect(styles.composerRoundButtonPrimary).toContain("!border-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)]");
    expect(styles.composerRoundButtonPrimary).toContain("hover:!bg-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-control-muted-hover))]");
    expect(styles.composerRoundButtonPrimary).toContain("active:!bg-[color-mix(in_srgb,var(--accent-cool)_22%,var(--vui-surface-row))]");
    expect(styles.sendButton).toContain("focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)]");
    expect(styles.stopButton).toContain("!border-[color-mix(in_srgb,var(--state-error)_34%,transparent)]");
    expect(styles.stopButton).toContain("hover:!bg-[color-mix(in_srgb,var(--state-error)_14%,var(--vui-control-muted-hover))]");
    expect(styles.stopButton).toContain("active:!bg-[color-mix(in_srgb,var(--state-error)_18%,var(--vui-surface-row))]");
    expect(styles.composerAttachmentTray).toContain("flex flex-wrap");
    expect(styles.composerAttachmentChip).toContain("overflow-hidden");
    expect(styles.composerAttachmentThumb).toContain("h-5");
    expect(styles.composerAttachmentThumb).toContain("w-5");
    expect(styles.composerAttachmentThumb).toContain("object-cover");
    expect(styles.composerAttachmentName).toContain("truncate");
    expect(styles.composerAttachmentRemoveButton).toContain("!w-6");
    expect(styles.composerFieldCodex).toContain("[@media(max-height:520px)]:min-h-[84px]");
    expect(styles.composerFieldCodex).toContain("[@media(max-height:520px)]:[&_textarea]:min-h-[44px]");

    const composerActionStackSource = conversationViewSource.slice(
      conversationViewSource.indexOf("const composerActions = ("),
      conversationViewSource.indexOf("\n\n  return (", conversationViewSource.indexOf("const composerActions = (")),
    );
    expect(composerActionStackSource).not.toContain("className={styles.attachButton}");
    expect(composerActionStackSource).toContain("className={primaryActionClassName}");
    expect(conversationViewSource).toContain('composerVariant === "codex" ? styles.composerToolbarCodex : styles.composerToolbar');
    expect(conversationViewSource).toContain("className={styles.attachButton}");
    expect(conversationViewSource).toContain("<ConversationInferenceControl {...llmControl} />");
    expect(conversationViewSource).toContain('composerVariant === "codex" ? composerActions : null');
    expect(conversationViewSource).toContain('composerVariant === "compact" ? composerActions : null');
    expect(styles.composerToolbar).toContain("items-center");
    expect(conversationViewSource).toContain("const primaryActionClassName = primaryActionIsEditSubmit");
    expect(conversationViewSource).toContain("styles.composerEditSubmitButton");
    // Labeled edit/rerun must not inherit square icon-only geometry.
    expect(conversationViewSource).not.toContain("composerEditSubmitButton} ${styles.composerRoundButtonPrimary}");
    expect(conversationViewSource).toContain("styles.composerRoundButtonPrimary");
    expect(conversationViewSource).toContain("icon={");
    expect(conversationViewSource).toContain("<RefreshCw");
  });
  it("keeps edit-mode composer chrome compact", () => {
    expect(styles.composerEditModeBar).toContain("min-h-7");
    expect(styles.composerEditModeBar).toContain("w-full");
    expect(styles.composerEditModeBar).toContain("px-2");
    expect(styles.composerEditModeBar).toContain("items-center");
    expect(styles.composerEditModeBar).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(styles.composerEditModeBar).not.toContain("accent-cool");
    expect(styles.composerEditModeIcon).not.toContain("p-2");
    expect(styles.composerEditModeCancel).toContain("!min-h-6");
    expect(styles.composerEditModeDescription).toContain("truncate");
    expect(styles.composerEditModePreview).toContain("truncate");
    expect(styles.composerEditModeWarning).toContain("state-warning");
    expect(styles.turnEditing).toContain("userMessageBody");
    expect(styles.turnEditing).not.toContain("vuiOpaqueRowClass");
    expect(styles.turnEditing).not.toMatch(/\bp-2\b/);
  });

  it("uses shared readable scale tokens for dense conversation text", () => {
    expect(conversationViewStylesSource).toContain("var(--vui-font-xs)");
    expect(conversationViewStylesSource).toContain("var(--vui-font-sm)");
    expect(conversationViewStylesSource).toContain("var(--vui-font-md)");
    expect(conversationViewStylesSource).toContain("var(--vui-font-chat)");
    expect(conversationViewStylesSource).not.toMatch(/font-size:\s*0\.(?:6\d|7[0-7])rem/);
  });
  it("caches response segmentation while delegating markdown rendering to the shared renderer", () => {
    expect(conversationViewSource).toContain("const responseSegmentCacheRef = useRef<Map<string, ResponseSegment[]>>(new Map())");
    expect(conversationViewSource).toContain("function getCachedResponseSegments(content: string)");
    expect(conversationViewSource).toContain('from "./conversationResponseSegmentCache"');
    expect(conversationViewSource).toContain("return getCachedResponseSegmentsFromCache(");
    expect(conversationViewSource).not.toContain("trimOldestCacheEntries(");
    expect(conversationViewSource).not.toContain("markdownBlockCacheRef");
    expect(conversationViewSource).not.toContain("MARKDOWN_PARSE_CACHE_LIMIT");
    expect(conversationViewSource).not.toContain("function getCachedMarkdownBlocks(content: string)");
    expect(conversationViewSource).not.toContain("parseConversationMarkdownBlocks");
    expect(conversationViewSource).not.toContain("renderConversationInlineMarkdown");
    expect(conversationViewSource).toContain('from "./LazyConversationMarkdownRenderer"');
    expect(conversationViewSource).toContain("<LazyConversationMarkdownRenderer");
    expect(conversationViewSource).not.toContain('from "./ConversationMarkdownRenderer"');
    expect(conversationViewSource).toContain("const responseSegments = showResponseBlock && !isStreamingStatusPlaceholder && !isResponseStreaming");
    expect(conversationViewSource).not.toContain("responseExpanded && !isResponseStreaming");
    expect(conversationViewSource).toContain("? getCachedResponseSegments(responseText)");
    expect(conversationViewSource).toContain("const prewarmMessages = timelineMessages");
    expect(conversationViewSource).toContain("window.setTimeout(prewarmNext, 48)");
  });

  it("keeps tool detail expansion work off collapsed renders", () => {
    expect(conversationViewSource).toContain('from "./ConversationOperationDetails"');
    expect(conversationViewSource).not.toContain("function DeferredOperationDetails");
    expect(conversationViewSource).not.toContain("useDeferredValue");
    expect(conversationOperationDetailsSource).toContain("export function DeferredOperationDetails");
    expect(conversationOperationDetailsSource).toContain("const deferredExpanded = useDeferredValue(expanded)");
    expect(conversationOperationDetailsSource).toContain("const detailRows = deferredExpanded ? buildDetailRows(operation) : []");
    expect(conversationViewSource).toContain("const canExpandDetails = hasOperationDetails(operation)");
    expect(conversationViewSource).toContain("<DeferredOperationDetails");
    expect(conversationViewSource).not.toContain("OPERATION_DETAILS_CLASS_NAMES");
    expect(conversationViewSource).not.toContain("classNames={OPERATION_DETAILS_CLASS_NAMES}");
    expect(conversationOperationDetailsSource).toContain('import styles from "./ConversationOperationDetails.styles"');
    expect(conversationOperationDetailsSource).toContain("classNames = styles");
    expect(conversationViewSource).toContain("buildOperationDetailRows(detailOperation, operationDetailLabels)");
    expect(conversationViewSource).not.toContain("function operationDetailRows(");
    expect(conversationViewSource).not.toContain("function readableOperationResult(");
    expect(conversationViewSource).not.toContain("function structuredResultSummary(");
    expect(conversationViewSource).not.toContain("function naturalRecordText(");
    expect(conversationViewSource).not.toContain("const detailRows = detailsExpanded ? operationDetailRows(operation) : []");
  });

  it("keeps extracted conversation child views owning their local style defaults", () => {
    expect(conversationStreamingResponseContentSource).toContain('import styles from "./ConversationStreamingResponseContent.styles"');
    expect(conversationStreamingResponseContentSource).toContain("classNames = styles");
    expect(conversationTurnAvatarContentSource).toContain('import styles from "./ConversationTurnAvatarContent.styles"');
    expect(conversationTurnAvatarContentSource).toContain("imageClassName = styles.turnAvatarImage");
    expect(conversationInlineMarkdownSource).toContain('import styles from "./conversationInlineMarkdown.styles"');
    expect(conversationInlineMarkdownSource).toContain("classNames: ConversationInlineMarkdownClassNames = styles");
    expect(conversationViewSource).not.toContain("classNames={{");
    expect(conversationViewSource).not.toContain("imageClassName={styles.turnAvatarImage}");
  });

  it("centralizes compact process signals in AgentMessage render state", () => {
    expect(agentMessageRenderStateSource).toContain("function compactJsonSignal(value: unknown)");
    expect(agentMessageRenderStateSource).toContain("function compactTextSignal(value: unknown)");
    expect(agentMessageRenderStateSource).toContain("compactJsonSignal(part.arguments ?? {})");
    expect(agentMessageRenderStateSource).toContain("compactTextSignal(part.resultPreview ?? \"\")");
    expect(conversationViewSource).not.toContain("JSON.stringify(toolCall.arguments ?? {})");
    expect(conversationViewSource).not.toContain("function lightweightJsonSignal(value: unknown)");
    expect(conversationViewSource).not.toContain("function lightweightTextSignal(value: unknown)");
  });

  it("keeps active-turn projection and history expansion anchors outside the render hot path", () => {
    expect(conversationViewSource).toContain("./useAgentMessageTimelineProjection");
    expect(conversationViewSource).not.toContain("./useConversationTimelineProjection");
    expect(conversationViewSource).toContain("projectAgentMessageTimelineMessages");
    expect(conversationViewSource).toContain("const activeAgentMessageTimelineProjection = useMemo");
    expect(conversationViewSource).toContain("activeAgentMessageTimelineProjection.messages");
    expect(conversationViewSource).toContain("activeAgentMessageTimelineProjection.agentMessages");
    expect(conversationViewSource).toContain("activeAgentMessageTimelineProjection.streamingMessages");
    expect(conversationViewSource).toContain("activeAgentMessageTimelineProjection.rowIdentities");
    expect(conversationViewSource).toContain("captureTimelineRowKeyAnchor");
    expect(conversationViewSource).toContain("restoreTimelineRowKeyAnchor");
    expect(conversationViewSource).not.toContain("projectConversationTimelineMessages");
    expect(conversationViewSource).not.toContain("const activeTimelineProjection = useMemo");
    expect(conversationViewSource).not.toContain("buildConversationTimelineRowIdentities(activeTimelineMessages)");
  });  it("keeps AgentThread projection behind a focused hook", () => {
    expect(conversationViewSource).toContain("useAgentThread");
    expect(conversationViewSource).toContain("const activeAgentMessages = activeAgentMessageTimelineProjection.agentMessages");
    expect(conversationViewSource).toContain("const agentThread = useAgentThread(sessionId, activeAgentMessages)");
    expect(conversationViewSource).not.toContain("useAgentThreadProjection");
    expect(conversationViewSource).not.toContain("function useAgentThreadForTimelineMessages");
    expect(conversationViewSource).not.toContain("agentMessageCacheRef");
    expect(conversationViewSource).not.toContain("conversationMessagesToAgentThread(");
  });

  it("binds AgentMessages to conversation turns by id instead of timeline index", () => {
    expect(conversationViewSource).toContain("agentMessagesByMessageId");
    expect(conversationViewSource).not.toContain("agentThread.messages[index]");
  });

  it("keeps AgentMessage render-state collection behind a focused helper", () => {
    expect(conversationViewSource).toContain("buildAgentMessageRenderState");
    expect(conversationViewSource).toContain("const agentRenderState = buildAgentMessageRenderState(agentMessage)");
    expect(conversationViewSource).not.toContain("function contentSectionIdsForChannel");
    expect(conversationViewSource).not.toContain("function processSectionIdsForSections");
  });

  it("does not recreate AgentMessage section state from legacy ConversationMessage helpers", () => {
    expect(conversationViewSource).not.toContain("function conversationMessageAgentSectionState");
    expect(conversationViewSource).not.toContain("conversationMessageHasAgentResponseBlock");
    expect(conversationViewSource).not.toContain("conversationMessageToAgentMessage(message)");
  });

  it("coalesces streaming auto-scroll frames without dispatching bottom state on every token", () => {
    expect(conversationViewSource).toContain("streamingScrollFrameRef");
    expect(conversationViewSource).toContain("function scrollTimelineToBottom");
    expect(conversationViewSource).toContain("if (!wasAtBottom) {");
    expect(conversationViewSource).toContain("onStreamingFramePaint({");
    expect(conversationViewSource).toContain("paintedAtMs: conversationPerformanceNowMs()");
    expect(conversationViewSource).not.toContain("const frameId = window.requestAnimationFrame");
  });

  it("restores per-session timeline scroll memory on thread revisit (C6)", () => {
    expect(conversationViewSource).toContain("peekSessionTimelineScroll");
    expect(conversationViewSource).toContain("restoreSessionTimelineScroll");
    expect(conversationViewSource).toContain("rememberSessionTimelineScroll");
    expect(conversationViewSource).toContain("initializedSessionRef.current !== sessionId");
  });

  it("keeps virtual-row ResizeObservers and streaming paint free of per-render thrash", () => {
    expect(conversationViewSource).toContain("timelineVirtualRowRefCallbacksRef");
    expect(conversationViewSource).toContain("timelineRowNodesRef");
    expect(conversationViewSource).toContain("streamingPaintMetricsRef");
    expect(conversationViewSource).toContain("followLatestRef.current ? 8 : 2");
    // ChatGPT/Claude: send always re-pins stick-to-bottom even after user scrolled up.
    expect(conversationViewSource).toContain("function pinFollowLatestForSubmit");
    expect(conversationViewSource).toContain("function handleSendAndFollowLatest");
    expect(conversationViewSource).toContain("handleSendAndFollowLatest()");
    expect(conversationViewSource).toContain("ref={timelineVirtualRowRef(rowKey)}");
    expect(conversationViewSource).toContain("timelineContentRef");
    expect(conversationViewSource).toContain("styles.timelineContent");
    // Height bumps re-pin only while following latest (coalesced rAF; content host RO is primary).
    expect(conversationViewSource).toMatch(
      /scheduleTimelineHeightVersionBump[\s\S]*?setTimelineRowHeightVersion/,
    );
    const bumpBlock = conversationViewSource.slice(
      conversationViewSource.indexOf("const scheduleTimelineHeightVersionBump"),
      conversationViewSource.indexOf("const bindTimelineVirtualRow"),
    );
    expect(bumpBlock).toContain("shouldStickTimelineToBottomOnContentResize");
    expect(bumpBlock).toContain("scheduleTimelineScrollToBottom()");
    expect(conversationViewSource).toContain("pinnedLatestUserMessageIdRef");
    expect(conversationViewSource).toContain("latestUserChanged");
    // Paint effect must not depend on Map/array identities that change every render.
    const paintBlock = conversationViewSource.slice(
      conversationViewSource.indexOf("if (!streamingTimelineScrollSignal || !onStreamingFramePaint)"),
      conversationViewSource.indexOf("useEffect(() => {\n    const timeline = timelineRef.current;\n    if (!timeline) {\n      return;\n    }\n    const handleScroll"),
    );
    expect(paintBlock).toContain("streamingTimelineScrollSignal");
    expect(paintBlock).not.toContain("agentRenderStatesByMessageId");
    expect(paintBlock).not.toContain("streamingTimelineMessages");
  });it("colors operation rows from each operation status instead of the operation kind", () => {
    expect(conversationViewSource).toContain("function operationStatusToneClassName(operation: AgentMessageOperation)");
    expect(conversationViewSource).toContain("operationStatusTone(operation)");
    expect(conversationViewSource).toContain("const statusTone = operationStatusToneClassName(operation);");
    expect(conversationViewSource).toContain("styles[`operationItem_${statusTone}`]");
    expect(conversationViewSource).toContain("styles[`operationIcon_${statusTone}`]");
    expect(conversationViewSource).toContain("styles[`operationText_${statusTone}`]");
    expect(conversationViewSource).toContain("styles.timelineCellBody");
    expect(conversationViewSource).toContain("styles.timelineCellTitle");
    expect(styles.operationItem_success).toContain("!text-[var(--fg-secondary)]");
    expect(styles.operationItem_success).not.toContain("state-success");
    expect(styles.operationItem_failed).toContain("!text-[var(--state-error)]");
    expect(styles.operationItem_warning).toContain("!text-[var(--state-warning)]");
    expect(styles.operationText_success).toContain("!text-[var(--fg-secondary)]");
    expect(styles.operationText_success).not.toContain("state-success");
    expect(styles.operationText_failed).toContain("!text-[var(--state-error)]");
    expect(styles.operationText_warning).toContain("!text-[var(--state-warning)]");
  });

  it("keeps successful child tool rows neutral inside a failed process group", () => {
    expect(conversationViewSource).toContain("const statusTone = operationStatusToneClassName(operation);");
    expect(conversationViewSource).toContain("styles[`operationText_${statusTone}`]");
    expect(conversationViewSource).toContain("styles[`operationStatus_${statusTone}`]");
    expect(styles.reActToolName).toContain("text-[var(--fg-primary)]");
    expect(styles.operationText_success).toContain("!text-[var(--fg-secondary)]");
    expect(styles.operationStatus_success).toContain("!text-[var(--fg-tertiary)]");
    expect(styles.operationStatus_success).not.toContain("state-success");
  });
  it("does not let top-edge history loading rewrite cached response expansion defaults", () => {
    expect(conversationViewSource).toContain("function revealEarlierTimelineMessages()");
    expect(conversationViewSource).toContain("preserveCurrentExpansionDefaults();");
    expect(conversationViewSource).toContain("function preserveCurrentExpansionDefaults()");
    expect(conversationViewSource).toContain("const responseExpanded = getExpansionState(message.id, \"response\", defaultResponseExpanded)");
    expect(conversationViewSource).not.toContain("defaultExpansionRef.current = {};\n    responseSegmentCacheRef.current.clear();\n    markdownBlockCacheRef.current.clear();\n    setSectionExpansion({});\n  }, [sessionId, visibleMessageLimit]");
  });

  it("freezes process and timeline expansion defaults before top-edge history loading", () => {
    expect(conversationViewSource).toContain('from "./conversationExpansionDefaults"');
    expect(conversationViewSource).toContain("preserveConversationExpansionDefaults({");
    expect(conversationViewSource).toContain("timelineItemsByMessageId: agentTimelineItemsByMessageId");
    expect(conversationViewSource).toContain("operationGroupsByMessageId: agentOperationGroupsByMessageId");
    expect(conversationViewSource).not.toMatch(/function preserveCurrentExpansionDefaults\(\)[\s\S]*?setDefault\(\"response\"[\s\S]*?}\n  }/);
  });

  it("keeps active streaming scroll signals on a small streaming-only tail", () => {
    expect(conversationViewSource).toContain("projectAgentMessageTimelineMessages({ timelineMessages, activeTurnMessage })");
    expect(conversationViewSource).toContain("const streamingTimelineMessages = activeAgentMessageTimelineProjection.streamingMessages");
    expect(conversationViewSource).toContain("buildStreamingTimelineScrollSignal(streamingTimelineMessages, agentRenderStatesByMessageId, {");
    expect(conversationViewSource).toContain("includeMentalSignals: showMentalSnapshots");
    expect(conversationViewSource).not.toContain("activeTimelineMessages.filter((message) => message.streaming)");
    expect(conversationViewSource).not.toContain("activeTimelineSignalMessages");
  });

  it("derives process scroll and latest tool summaries from AgentMessage render state", () => {
    expect(conversationViewSource).toContain("from \"./conversationTimelineScrollSignals\"");
    expect(conversationViewSource).toContain("buildTimelineScrollSignal(timelineMessages, agentRenderStatesByMessageId, {");
    expect(conversationViewSource).toContain("buildStreamingTimelineScrollSignal(streamingTimelineMessages, agentRenderStatesByMessageId, {");
    expect(conversationViewSource).toContain("renderState.toolCalls");
    expect(conversationViewSource).not.toContain("renderState.processSignal");
    expect(conversationViewSource).not.toContain("renderState.processSignalWithoutMental");
    expect(conversationViewSource).not.toContain("timelineSignalMessages");
    expect(conversationViewSource).not.toContain("mentalSnapshot: undefined");
    expect(conversationViewSource).not.toContain("message.thought?.length");
    expect(conversationViewSource).not.toContain("const mentalSnapshot = message.mentalSnapshot");
    expect(conversationViewSource).not.toContain("const toolSignal = (message.toolCalls ?? [])");
    expect(conversationViewSource).not.toContain(".find((message) => !isTurnErrorMessage(message) && (message.toolCalls?.length ?? 0) > 0)?.toolCalls");
  });

  it("auto-loads earlier messages from top-edge or pinned timeline state instead of a manual gate", () => {
    expect(conversationViewSource).toContain("function revealEarlierTimelineMessages()");
    expect(conversationViewSource).toContain("shouldLoadEarlierConversationMessages({");
    expect(conversationViewSource).toContain("const hiddenHistorySignalCount = hiddenRenderedMessageCount + (hasEarlierMessages ? 1 : 0)");
    expect(conversationViewSource).toContain("hiddenMessageCount: hiddenHistorySignalCount");
    expect(conversationViewSource).toContain("onLoadEarlierMessages()");
    expect(conversationViewSource).toContain("scrollHeight: timeline.scrollHeight");
    expect(conversationViewSource).toContain("clientHeight: timeline.clientHeight");
    expect(conversationViewSource).toContain("handleScroll");
    expect(conversationViewSource).toContain("revealEarlierTimelineMessages()");
    expect(conversationViewSource).toContain("captureTimelineRowKeyAnchor(timelineRef.current)");
    expect(conversationViewSource).toContain("restoreTimelineRowKeyAnchor(timelineRef.current, anchor)");
    expect(conversationViewSource).not.toContain("function showEarlierMessages()");
    expect(conversationViewSource).not.toContain("onClick={showEarlierMessages}");
    expect(conversationViewSource).not.toContain("setAllMessagesVisible(true)");
  });

  it("coalesces canonical and streaming timeline scroll requests into one frame", () => {
    expect(conversationViewSource).toContain("function scheduleTimelineScrollToBottom()");
    expect(conversationViewSource).toContain("scheduleTimelineScrollToBottom();");
    expect(conversationViewSource).not.toContain(
      "if (autoScrollToLatest && followLatestRef.current) {\n      scrollTimelineToBottom(timeline);",
    );
  });

  it("can render the opt-in compact workbench density", () => {
    const html = renderConversation([], { density: "compact" });

    expect(html).toContain("surfaceCompact");
  });

  it("keeps execution tool-call content borderless", () => {
    expect(styles.executionTraceGroup).toContain("border-0");
    expect(styles.reActOperationSummary).toContain("border-0");
    expect(styles.reActOperationSummary).toContain("inline-grid");
    expect(styles.reActOperationSummary).toContain("w-fit");
    expect(styles.reActOperationSummary).not.toContain("minmax(0,1fr)");
    expect(styles.reActResultItem).toContain("border-0");
    expect(styles.reActResultItem).toContain("bg-transparent");
    expect(styles.reActOperationGroup).toContain("border-l-0");
    expect(styles.reActThoughtText).toContain("border-l-0");
    expect(styles.reActThoughtText).toContain("bg-transparent");
    expect(styles.operationDetails).toContain("border-0");
    expect(styles.operationDetailRow).toContain("bg-transparent");
    expect(styles.operationDetailRow).not.toContain("rounded-[var(--radius-control)]");
    expect(styles.operationDetailValue).toContain("border-l-2");
    expect(styles.operationDetailValue).toContain("bg-transparent");
    expect(styles.operationDetailValue).toContain("font-mono");
    expect(styles.operationItem).toContain("w-[min(100%,72ch)]");
    expect(styles.operationItem).toContain("grid-cols-[22px_minmax(0,1fr)_auto_auto_16px]");
    expect(styles.timelineThoughtText).toContain("border-0");
    expect(styles.timelineThoughtText).toContain("bg-transparent");
    expect(styles.reActResultToggle).toContain("border-0");
  });

  it("keeps ReAct tool rows as line items instead of nested white cards", () => {
    const lineItemStyles = [
      styles.reActToolList,
      styles.reActToolItem,
      styles.reActToolLine,
      styles.reActToolSummary,
      styles.reActToolStatus,
      styles.reActToolDetailToggle,
    ].join(" ");

    expect(styles.reActToolLine).toContain("grid-cols-[minmax(9rem,auto)_minmax(0,1fr)_auto_auto]");
    expect(styles.reActToolList).toContain("gap-0");
    expect(styles.reActToolItem).toContain("border-0");
    expect(styles.reActToolItem).toContain("bg-transparent");
    expect(styles.reActToolLine).toContain("border-0");
    expect(styles.reActToolLine).toContain("bg-transparent");
    expect(styles.reActToolSummary).toContain("border-0");
    expect(styles.reActToolSummary).toContain("bg-transparent");
    expect(styles.reActToolStatus).toContain("border-0");
    expect(styles.reActToolStatus).toContain("bg-transparent");
    expect(styles.reActToolDetailToggle).toContain("border-0");
    expect(styles.reActToolDetailToggle).toContain("bg-transparent");
    expect(lineItemStyles).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(lineItemStyles).not.toMatch(/bg-vui-surface-row|bg-\[var\(--vui-surface-row\)\]/);
    expect(lineItemStyles).not.toContain("shadow-[var(--vui-shadow-hairline)]");
  });

  it("keeps streamed execution rows readable without forcing a wide reading measure", () => {
    expect(conversationViewStylesSource).not.toMatch(/font-size:\s*0\.(?:[0-6]\d?|7(?:0|1)?)rem/);
    expect(styles.operationItem).not.toContain("w-fit");
    expect(styles.operationItem).not.toContain("max-content");
    expect(styles.operationItemTool).not.toContain("max-content");
    expect(styles.operationText).toContain("max-w-full");
    expect(styles.messageBody).toContain("whitespace-pre-wrap");
    expect(styles.messageBody).toContain("[overflow-wrap:anywhere]");
    expect(styles.messageBody).toContain("max-w-full");
    expect(styles.markdownBody).toContain("max-w-full");
    expect(styles.responseSegment_answer).toContain("[&_.markdownBody]:max-w-[min(100%,128ch)]");
    expect(styles.assistantTurn).toContain("[&_.turnContent]:w-full");
    expect(styles.agentInboxTurn).toContain("[&_.turnContent]:w-[min(100%,1360px)]");
    expect(styles.groupTranscriptTurn).toContain("[&_.turnContent]:w-[min(100%,1360px)]");
    expect(styles.timelineAssistantTextCell).toContain("max-w-[min(100%,1360px)]");
    expect(styles.codexTranscriptSurface).toContain("w-full");
    expect(styles.codexTranscriptSurface).toContain("max-w-full");
    expect(styles.codexTranscriptCellSummary).toContain("max-w-full");
    expect(styles.messageBody).not.toContain("max-w-[min(100%,128ch)]");
  });
  it("renders composer session reference chips", () => {
    const html = renderConversation([], {
      composerReferences: [
        {
          referenceId: "session:ref-1",
          kind: "session",
          sessionId: "ref-1",
          title: "顾云舒上下文",
          agentDisplayName: "顾云舒",
        },
      ],
    });

    expect(html).toContain("顾云舒上下文");
    expect(html).toContain("顾云舒");
    expect(html).toContain('aria-label="待发送会话引用"');
    expect(html).toContain('role="list"');
    expect(html).toContain('role="listitem"');
  });

  it("connects slash command suggestions to the composer textarea", () => {
    const html = renderConversation([], {
      composerValue: "/",
      slashCommandSuggestions: [
        {
          directoryName: "ccdawn-brt",
          name: "BRT",
          command: "/brt",
          description: "Intent routing",
        },
      ],
    });

    expect(html).toContain('role="listbox"');
    expect(html).toContain('id="conversation-session-1-slash-suggestions"');
    expect(html).toContain('aria-controls="conversation-session-1-slash-suggestions"');
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain('aria-autocomplete="list"');
    expect(html).toContain('id="conversation-session-1-slash-suggestions-option-0"');
    expect(html).toContain('role="option"');
  });

  it("uses the configured user avatar preset for user turns", () => {
    const html = renderConversation(
      [
        {
          id: "message-user",
          role: "user",
          content: "Use my profile",
          timestamp: "2026-05-22T00:00:00Z",
        },
      ],
      { userAvatarPreset: "codex", userDisplayName: "Vibe Owner" },
    );

    expect(html).toContain(">C</div>");
    expect(html).toContain("Vibe Owner");
    expect(styles.turnAvatar).toContain("ring-[var(--vui-border-strong)]");
    expect(styles.turnAvatar).toContain("text-[var(--fg-primary)]");
  });it("renders agent inbox turns with the resolved source agent avatar", () => {
    const html = renderConversation(
      [
        {
          id: "agent-inbox",
          role: "user",
          content: "[Agent 私信]\n来源 Agent: A011 · 夏予安\n\n消息内容:\n请从组织设计角度回复。",
          timestamp: "2026-05-29T14:13:33Z",
          metadata: {
            kind: "agent_inbox_message",
            sourceAgentCode: "A011",
            sourceAgentName: "夏予安",
          },
        },
      ],
      {
        resolveTurnAvatar: (message) => {
          if (!isAgentInboxMessage(message)) {
            return undefined;
          }
          return {
            imageUrl: "/api/agents/avatar-image/11-white-guardian.png",
            fallback: "11",
          };
        },
      },
    );

    expect(html).toContain('src="/api/agents/avatar-image/11-white-guardian.png"');
    expect(html).toContain("Agent 私信 · A011 · 夏予安");
  });

  it("renders Agent inbox messages as inbound private messages instead of operator turns", () => {
    const html = renderConversation(
      [
        {
          id: "agent-inbox",
          role: "user",
          content: "[Agent 私信]\n来源 Agent: A011 · 夏予安\n\n消息内容:\n请从组织设计角度回复。",
          timestamp: "2026-05-29T14:13:33Z",
          metadata: {
            kind: "agent_inbox_message",
            sourceAgentCode: "A011",
            sourceAgentName: "夏予安",
          },
        },
      ],
      { userAvatarPreset: "codex", userDisplayName: "Vibe Owner" },
    );

    expect(html).toContain("agentInboxTurn");
    expect(html).toContain("Agent 私信 · A011 · 夏予安");
    expect(html).toContain("私信内容");
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("请从组织设计角度回复");
    expect(html).not.toContain("Vibe Owner");
    expect(html).not.toContain("aria-label=\"Edit and resend\"");
    expect(html).not.toContain("消息内容:");
  });

  it("renders research organization intent and wake chips on Agent inbox messages", () => {
    const html = renderConversation(
      [
        {
          id: "research-org-inbox",
          role: "user",
          content: "[Agent 私信]\n来源 Agent: A014 · 能力管家\n\n消息内容:\n权限审查已完成。",
          timestamp: "2026-05-30T14:13:33Z",
          metadata: {
            kind: "agent_inbox_message",
            inboxKind: "research_org_report",
            sourceAgentCode: "A014",
            sourceAgentName: "能力管家",
            researchOrgIntent: "status_report",
            researchOrgMessageType: "report",
            researchOrgDeliveryMode: "private",
            wakeStatus: "not_requested",
          },
        },
      ],
      { userAvatarPreset: "codex", userDisplayName: "Vibe Owner" },
    );

    expect(html).toContain("科研组织消息标签");
    expect(html).toContain("intent: status report");
    expect(html).toContain("type: report");
    expect(html).toContain("delivery: private");
    expect(html).toContain("wake: not requested");
    expect(html).toContain("Agent 私信 · A014 · 能力管家");
  });it("keeps command group expansion state scoped to the parent message during history reveal", () => {
    expect(conversationViewSource).toContain("renderCommandGroupTimelineItem(message, item, rowIdentity, isActiveTimelineItem)");
    expect(conversationViewSource).toContain("const expanded = getExpansionState(message.id, item.id, false)");
    expect(conversationViewSource).toContain("onClick={() => toggleSection(message.id, item.id, false)}");
    expect(conversationViewSource).not.toContain("const expanded = getExpansionState(item.id, \"details\", false)");
    expect(conversationViewSource).not.toContain("onClick={() => toggleSection(item.id, \"details\", false)}");
  });

  it("applies per-operation status tones inside expanded command packages", () => {
    expect(conversationViewSource).toContain("item.operations.map((operation) => {");
    expect(conversationViewSource).toContain("const statusTone = operationStatusToneClassName(operation);");
    expect(conversationViewSource).toContain("styles[`operationText_${statusTone}`]");
    expect(conversationViewSource).toContain("styles[`operationStatus_${statusTone}`]");
    expect(styles.operationText_success).toContain("!text-[var(--fg-secondary)]");
    expect(styles.operationText_failed).toContain("!text-[var(--state-error)]");
    expect(styles.operationText_warning).toContain("!text-[var(--state-warning)]");
  });it("prefers the configured user avatar image for user turns", () => {
    const html = renderConversation(
      [
        {
          id: "message-user",
          role: "user",
          content: "Use my local avatar",
          timestamp: "2026-05-22T00:00:00Z",
        },
      ],
      {
        userAvatarPreset: "codex",
        userAvatarImageUrl: "/api/config/avatar-image/avatar-test.png",
        userDisplayName: "Vibe Owner",
      },
    );

    expect(html).toContain('src="/api/config/avatar-image/avatar-test.png"');
    expect(html).not.toContain(">C</div>");
  });
  it("keeps the composer writable while a running turn shows guidance and keeps stop actions", () => {
    const html = renderConversation([], {
      composerValue: "下一句先写在这里",
      composerDisabled: true,
      composerActionMode: "stop",
      composerActionDisabled: false,
      composerGuidance: "当前轮仍在运行。安全引导会记录到会话上下文；打断引导会先记录再请求停止当前轮。",
      onSafeGuidance: () => undefined,
      onInterruptGuidance: () => undefined,
    });

    expect(html).toContain("下一句先写在这里");
    expect(html).toContain("当前轮仍在运行");
    expect(html).toContain("打断引导会先记录再请求停止当前轮");
    expect(html).toContain('aria-label="安全引导"');
    expect(html).not.toContain('aria-label="打断引导"');
    expect(html).toContain('aria-label="终止"');
    expect(html).toContain("composerRoundButtonPrimary");
    expect(html).toContain("stopButton");
    const textarea = html.match(/<textarea[^>]*>/)?.[0] ?? "";
    expect(textarea).not.toMatch(/\sdisabled(?:[=>\s]|$)/);
  });

  it("keeps the running composer stop-only until a draft exists while guidance remains visible", () => {
    const html = renderConversation([], {
      composerValue: "",
      composerDisabled: true,
      composerActionMode: "stop",
      composerActionDisabled: false,
      composerGuidance: "当前轮仍在运行。安全引导会记录到会话上下文；打断引导会先记录再请求停止当前轮。",
      onSafeGuidance: () => undefined,
      onInterruptGuidance: () => undefined,
    });

    expect(html).toContain("当前轮仍在运行");
    expect(html).toContain("打断引导会先记录再请求停止当前轮");
    expect(html).not.toContain('aria-label="安全引导"');
    expect(html).toContain('aria-label="终止"');
    expect(html.match(/composerRoundButton/g)?.length).toBe(1);
  });

  it("renders edit controls only for the latest user message", () => {
    const html = renderConversation([
      {
        id: "message-user-1",
        role: "user",
        content: "First prompt",
        timestamp: "2026-05-22T00:00:00Z",
      },
      {
        id: "message-assistant-1",
        role: "assistant",
        content: "First answer",
        timestamp: "2026-05-22T00:01:00Z",
      },
      {
        id: "message-user-2",
        role: "user",
        content: "Second prompt",
        timestamp: "2026-05-22T00:02:00Z",
      },
    ]);

    expect(html.match(/aria-label="Edit and resend"/g)?.length).toBe(1);
    expect(html).toContain("Second prompt");
    expect(html).toContain("First prompt");
  });  it("renders user image attachments and composer image chips", () => {
    const userMessage: ConversationMessage = {
      id: "message-user",
      role: "user",
      content: "看看这张图",
      timestamp: "2026-05-22T00:00:00Z",
      attachments: [
        {
          artifactId: "user-image-test.png",
          filename: "sketch.png",
          url: "/api/sessions/session-1/artifacts/user-image-test.png",
          imageUrl: "/api/sessions/session-1/artifacts/user-image-test.png",
          downloadUrl: "/api/sessions/session-1/artifacts/user-image-test.png?download=1",
          contentType: "image/png",
          sizeBytes: 128,
          kind: "user_image",
          status: "ready",
        },
      ],
    };
    const html = renderConversation(
      [userMessage],
      {
        composerAttachments: [
          {
            id: "pending-image",
            filename: "pending.png",
            previewUrl: "blob:pending-image",
            sizeBytes: 256,
            contentType: "image/png",
          },
        ],
        onRemoveComposerAttachment: () => undefined,
      },
    );
    const contextHtml = renderToStaticMarkup(
      <AgentContextSectionsView
        sections={buildAgentMessageRenderState(conversationMessageToAgentMessage(userMessage)).contextSections}
        lang="zh"
      />,
    );

    expect(contextHtml).toContain('src="/api/sessions/session-1/artifacts/user-image-test.png"');
    expect(contextHtml).toContain("sketch.png");
    expect(html).toContain("pending.png");
    expect(html).toContain("blob:pending-image");
    expect(html).toContain("composerAttachmentThumb");
    expect(html).toContain("composerAttachmentName");
    expect(html).toContain("composerAttachmentRemoveButton");
    expect(html).toContain('aria-label="待发送图片"');
    expect(html).toContain('role="list"');
    expect(html).toContain('role="listitem"');
    expect(conversationViewSource).toContain("<X size={13} aria-hidden=\"true\" />");
  });it("renders markdown in user messages with the same safe renderer", () => {
    const html = renderConversation([
      {
        id: "message-user",
        role: "user",
        content: [
          "### 我的目标",
          "",
          "- 修复显示",
          "- 保持安全",
        ].join("\n"),
        timestamp: "2026-05-22T00:00:00Z",
      },
    ]);

    expect(html).toContain("markdownHeading");
    expect(html).toContain(">我的目标</h4>");
    expect(html).toContain("<ul");
    expect(html).not.toContain("### 我的目标");
  });

  it("marks the active edit target and disables edit controls while busy", () => {
    const html = renderConversation(
      [
        {
          id: "message-user",
          role: "user",
          content: "Original prompt",
          timestamp: "2026-05-22T00:00:00Z",
        },
      ],
      {
        editingMessageId: "message-user",
        editUserMessageDisabled: true,
        composerValue: "Original prompt",
      },
    );

    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain("disabled");
    expect(html).toContain("Original prompt");
    expect(html).toContain("编辑消息");
  });

  it("renders edit mode as a visible composer status row with target preview and rerun action", () => {
    const html = renderConversation(
      [
        {
          id: "message-user",
          role: "user",
          content: "继续",
          timestamp: "2026-05-22T00:00:00Z",
        },
      ],
      {
        editingMessageId: "message-user",
        composerModeNotice: "正在编辑最新一条用户消息；发送后会替换这条消息并重跑后续对话。",
        composerModeTargetPreview: "继续",
        cancelComposerModeLabel: "取消编辑",
        composerValue: "继续",
        submitLabel: "保存并重跑",
        onCancelComposerMode: () => undefined,
      },
    );

    expect(html).toContain("composerEditModeBar");
    expect(html).toContain("composerEditModeLabel");
    expect(html).toContain("编辑消息");
    expect(html).toContain("aria-label=\"正在编辑最新一条用户消息；发送后会替换这条消息并重跑后续对话。\"");
    expect(html).not.toContain("composerEditModeDescription");
    expect(html).not.toContain("composerEditModePreview");
    expect(html).not.toContain("当前内容：继续");
    expect(html).toContain("composerEditModeCancel");
    expect(html).toContain("composerEditSubmitButton");
    expect(html).toContain("保存并重跑");
    expect(html).not.toContain("composerRoundButtonPrimary");
    expect(html).toMatch(/data-slot="vui-button-label"[^>]*>保存并重跑</);
    expect(html).not.toContain("composerModeNoticeIcon");
  });
  it("does not render the mental-model option in the composer", () => {
    const html = renderConversation([]);

    expect(html).not.toContain("下轮启用心智模型");
    expect(html).not.toContain("发送选项");
  });it("renders current turn error provider diagnostics with HTTP status", () => {
    const html = renderConversation([], {
      turnError: {
        message: "模型服务上游暂时失败，本轮没有完成。",
        errorType: "provider_upstream_error",
        reasonCode: "upstream_unavailable",
        reasonSummary: "provider 上游服务不可用或网关失败",
        reasonDetail: "No available accounts: no available accounts",
        httpStatus: 503,
        provider: "anthropic",
        providerHost: "www.atpify.cn",
        providerErrorType: "api_error",
        providerErrorMessage: "No available accounts: no available accounts",
        model: "claude-opus-4-7",
        recoverable: true,
        timestamp: "2026-05-22T00:01:00Z",
        turnId: "turn-1",
      },
    });

    expect(html).toContain("turnErrorText");
    expect(html).toContain("诊断详情");
    expect(html).toContain("<details");
    expect(html).toContain("状态码: 503");
    expect(html).toContain("类型: api_error");
    expect(html).toContain("通道: anthropic · www.atpify.cn");
    expect(html).toContain("模型: claude-opus-4-7");
    expect(styles.turnError).toContain("shadow-none");
    expect(styles.turnError).toContain("mx-auto");
    expect(styles.turnError).toContain("w-[min(100%,760px)]");
    expect(styles.turnErrorDiagnosticsBody).toContain("border-t");
    expect(styles.turnErrorText).toContain("[overflow-wrap:anywhere]");
    expect(styles.turnErrorText).not.toContain("border ");
    expect(styles.turnErrorDetail).toContain("[overflow-wrap:anywhere]");
    expect(styles.turnErrorDetail).not.toContain("rounded-[var(--radius-panel)]");
    expect(styles.turnErrorLabel).not.toContain("p-2");
  });
  it("does not render the next-state signal panel when no signals exist", () => {
    const html = renderConversation([]);

    expect(html).not.toContain("最近控制信号");
  });

  it("hides completed continue signals from the main conversation panel", () => {
    const continueSignal: ChatNextStateSignalSummary = {
      signalId: "chat-signal-continue",
      sessionId: "session-1",
      turnId: "turn-continue",
      source: "user",
      kind: "user_continues",
      polarity: "neutral",
      mode: "directive",
      relatedEventCode: "conversation.user_continue_requested",
      createdAt: "2026-05-25T00:19:12Z",
      summary: "用户请求继续上一轮未完成任务。",
    };

    expect(shouldShowNextStateSignalInConversation(continueSignal, "ready")).toBe(false);
    expect(shouldShowNextStateSignalInConversation(continueSignal, "completed")).toBe(false);
    expect(shouldShowNextStateSignalInConversation(continueSignal, "running")).toBe(true);

    const html = renderConversation([], { nextStateSignals: [continueSignal] });
    expect(html).not.toContain("最近控制信号");
    expect(html).not.toContain("用户请求继续上一轮未完成任务。");
  });

  it("keeps stop and failure signals visible after the turn finishes", () => {
    expect(
      shouldShowNextStateSignalInConversation(
        {
          signalId: "chat-signal-stop",
          sessionId: "session-1",
          turnId: "turn-stop",
          source: "user",
          kind: "user_stops",
          polarity: "negative",
          mode: "directive",
          relatedEventCode: "conversation.user_stop_requested",
          createdAt: "2026-05-25T00:19:12Z",
          summary: "用户请求停止当前对话轮次。",
        },
        "ready",
      ),
    ).toBe(true);
  });it("keeps runtime status content out of the assistant answer block", () => {
    const html = renderConversation([
      {
        id: "message-runtime-status-content",
        role: "assistant",
        content: "状态 正在思考，已收到思考片段... 模型已经开始返回 reasoning，正文可能稍后出现。",
        timestamp: "2026-06-05T09:35:18Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "running",
            name: "model_thinking",
            summary: "正在思考，已收到思考片段...",
          },
        ],
      },
    ]);

    expect(html).not.toContain("正在思考中");
    expect(html).not.toContain("正在请求");
    expect(html).not.toContain("执行过程");
    expect(html).not.toContain("模型思考");
    expect(html).not.toContain("工具调用");
    expect(html).not.toContain("1 步");
    expect(html).not.toContain("0/1");
    expect(html).not.toContain("第 1 轮");
    expect(html).not.toContain("reasoning 已开始返回");
    expect(html).not.toContain('title="展开工具详情"');
    expect(html).not.toContain("正在思考，已收到思考片段");
    expect(html).not.toContain("回答</span>");
  });

  it("keeps transient reasoning placeholders out of the assistant answer block", () => {
    const html = renderConversation([
      {
        id: "message-runtime-reasoning-placeholder",
        role: "assistant",
        content: "正在思考，已收到思考片段...\n模型已经开始返回 reasoning，正文可能稍后出现。",
        timestamp: "2026-06-05T09:35:18Z",
        streaming: true,
        streamStage: "model_thinking",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "running",
            name: "model_thinking",
            summary: "正在思考，已收到思考片段...",
          },
        ],
      },
    ]);

    expect(html).not.toContain("正在思考中");
    expect(html).not.toContain("正在请求");
    expect(html).not.toContain("正在思考，已收到思考片段");
    expect(html).not.toContain("模型已经开始返回 reasoning");
    expect(html).not.toContain("正文可能稍后出现");
    expect(html).not.toContain("回答</span>");
    expect(html).not.toContain("responseSection");
  });  it("hides model-request placeholder instead of rendering a separate answer block", () => {
    const placeholder = "正在请求模型，等待首个响应片段...\n上下文已组装完成，正在进入 LLM 调用。";
    const html = renderConversation(
      [
        {
          id: "message-model-request-preview",
          role: "assistant",
          content: placeholder,
          timestamp: "2026-06-23T18:11:00Z",
          streaming: true,
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "running",
              name: "model_request",
              summary: placeholder,
            },
          ],
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html).not.toContain("正在请求");
    expect(html).not.toContain("生成中");
    expect(html).not.toContain("正在请求模型，等待首个响应片段...");
    expect(html).not.toContain("上下文已组装完成");
    expect(html).not.toContain("answerOnlyProcessPreview");
    expect(html).not.toContain("回答</span>");
    expect(html).not.toContain("responseSection");
  });
  it("hides request-only internal process state without empty expandable details", () => {
    const html = renderConversation(
      [
        {
          id: "message-request-only-static",
          role: "assistant",
          content: "",
          timestamp: "2026-06-29T13:32:00Z",
          streaming: true,
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "running",
              name: "model_request",
              summary: "正在请求模型，等待首个响应片段。",
            },
          ],
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html).not.toContain("正在请求");
    expect(html).not.toContain("生成中");
    expect(html).not.toContain("aria-expanded");
    expect(html).not.toContain('title="展开执行明细"');
    expect(html).not.toContain("answerOnlyProcessGroup");
  });it("hides collapsed answer-only internal process summary before real details exist", () => {
    const placeholder = "正在请求模型，等待首个响应片段...\n上下文已组装完成，正在进入 LLM 调用。";
    const html = renderConversation(
      [
        {
          id: "message-model-request-single-spinner",
          role: "assistant",
          content: placeholder,
          timestamp: "2026-06-23T18:11:00Z",
          streaming: true,
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "running",
              name: "model_request",
              summary: placeholder,
            },
          ],
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html).not.toContain("正在请求");
    expect(html).not.toContain("生成中");
    expect(html).not.toContain("statusSpinner");
  });

  it("does not use an animated spinner for the answer-only process summary icon", () => {
    const start = conversationViewSource.indexOf("function processSummaryIcon");
    const end = conversationViewSource.indexOf("function hasOperationDetails", start);
    const processSummaryIconSource = conversationViewSource.slice(start, end);

    expect(processSummaryIconSource).toContain("function processSummaryIcon");
    expect(end).toBeGreaterThan(start);
    expect(processSummaryIconSource).not.toContain("styles.statusSpinner");
  });it("does not show legacy mental snapshots as active process sections", () => {
    const html = renderConversation([
      {
        id: "message-mental-running",
        role: "assistant",
        content: "",
        timestamp: "2026-05-26T00:01:00Z",
        streaming: true,
        mentalSnapshot: {
          mood: "focused",
          feeling: "tracking state",
          whisper: "",
          summary: "Following the active turn",
          cognitiveState: "productive",
          confidence: 0.7,
          sampleSize: 1,
          interventionCount: 0,
          updatedAt: "2026-05-26T00:01:05Z",
          source: "runtime",
        },
      },
    ]);

    expect(html).not.toContain("心智模型");
    expect(html).not.toContain("Following the active turn");
    expect(html).not.toContain("tracking state");
    expect(html.match(/statusSpinner/g)?.length).toBeUndefined();
  });});
