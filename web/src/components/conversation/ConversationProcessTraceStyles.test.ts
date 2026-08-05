import { describe, expect, it } from "vitest";

import styles from "./ConversationView.styles";

describe("conversation process trace styles", () => {
  it("keeps timeline operation rows scannable instead of generated nested cards", () => {
    expect(styles.timelineCellHeader).toContain("grid-cols-[20px_minmax(0,1fr)]");
    expect(styles.timelineCellHeader).not.toContain("grid-cols-[20px_minmax(0,1fr)_24px]");
    expect(styles.timelineCellHeader).not.toContain("grid-cols-[20px_fit-content(52rem)_24px_minmax(0,1fr)]");
    expect(styles.timelineCellHeader).not.toContain("_max-content_");
    expect(styles.timelineCellHeader).toContain("overflow-visible");
    expect(styles.timelineCellHeader).not.toContain("flex flex-wrap");
    expect(styles.timelineCellHeader).not.toContain("overflow-auto");
    expect(styles.timelineCellHeader).toContain("gap-x-2");
    expect(styles.timelineCellBody).toContain("overflow-hidden");
    expect(styles.timelineCellTitleRow).toContain("inline-flex");
    expect(styles.timelineCellTitleRow).toContain("items-baseline");
    expect(styles.timelineCellTitle).toContain("[overflow-wrap:anywhere]");
    expect(styles.timelineCellTitle).toContain("[font-size:var(--vui-font-xs)]");
    expect(styles.timelineCellTitle).toContain("font-normal");
    expect(styles.timelineCellTitle).toContain("text-[var(--fg-tertiary)]");
    expect(styles.timelineCellMeta).toContain("inline-flex");
    expect(styles.timelineCellMeta).toContain("align-baseline");
    expect(styles.timelineCellMeta).toContain("whitespace-nowrap");
    expect(styles.timelineCellMeta).not.toContain("max-w-[min(30ch,34vw)]");
    expect(styles.timelineCellMeta).not.toContain("justify-self-end");
    expect(styles.timelineCellMeta).not.toContain("text-right");
    expect(styles.timelineCellMeta).toContain("[font-size:var(--vui-font-xs)]");
    expect(styles.timelineCellMeta).toContain("text-[var(--fg-tertiary)]");
    expect(styles.timelineThoughtHeader).toContain("grid-cols-[20px_minmax(0,1fr)_24px]");
    expect(styles.timelineThoughtHeader).toContain("!items-center");
    expect(styles.timelineThoughtHeader).toContain("overflow-hidden");
    expect(styles.timelineThoughtHeader).not.toContain("grid-cols-[20px_fit-content(52rem)_24px_minmax(0,1fr)]");
    expect(styles.timelineThoughtHeader).not.toContain("max-content");
    expect(styles.timelineThoughtInlinePreview).toContain("truncate");
    expect(styles.timelineThoughtInlinePreview).toContain("flex-1");
    expect(styles.timelineThoughtInlinePreview).not.toContain("line-clamp-2");
    expect(styles.timelineThoughtInlinePreview).not.toContain("whitespace-normal");

    expect(styles.timelineCellCompactTitleRow).toContain("[&_.timelineCellTitle]:max-w-none");
    expect(styles.timelineCellCompactTitleRow).toContain("[&_.timelineCellTitle]:shrink-0");
    expect(styles.timelineCellCompactTitleRow).not.toContain("[&_.timelineCellTitle]:truncate");
    expect(styles.timelineCellInlineChevron).toContain("size-3.5");
    expect(styles.timelineCellInlineChevron).not.toMatch(/border|rounded|shadow/);

    expect(styles.timelineCommandRow).toContain("bg-transparent");
    expect(styles.timelineCommandRow).toContain("grid-cols-[15px_minmax(0,1fr)]");
    expect(styles.timelineCommandRow).not.toContain("_max-content");
    expect(styles.timelineCommandRow).toContain("py-[0.35rem]");
    expect(styles.timelineCommandRow).toContain("[font-size:var(--vui-font-xs)]");
    expect(styles.timelineCommandRow).toContain("text-[var(--fg-tertiary)]");
    expect(styles.timelineCommandRow).toContain("border-0");
    expect(styles.timelineCommandRow).not.toContain("border-b ");
    expect(styles.timelineCommandRow).not.toContain("overflow-auto");
    expect(styles.timelineCommandRow).not.toContain("bg-[var(--vui-surface-row)]");
    expect(styles.timelineCommandList).toContain("border-0");
    expect(styles.timelineCommandList).not.toContain("border-y");
    expect(styles.timelineCommandList).toContain("max-h-[min(18rem,42vh)]");
    expect(styles.timelineCommandError).toContain("col-start-2");
    expect(styles.timelineCommandError).not.toContain("col-span-2");
    expect(styles.timelineCommandError).toContain("[font-size:var(--vui-font-xs)]");
  });

  it("keeps normal completed process rows neutral and reserves red for failures", () => {
    expect(styles.timelineOperationCell_success).toContain("text-[var(--fg-tertiary)]");
    expect(styles.timelineOperationCell_success).not.toContain("state-success");
    expect(styles.answerOnlyProcessGroup_success).toContain("text-[var(--fg-secondary)]");
    expect(styles.answerOnlyProcessGroup_success).not.toContain("state-success");
    expect(styles.answerOnlyProcessGroup_running).toContain("bg-transparent");
    expect(styles.answerOnlyProcessGroup_running).not.toContain("state-success");
    expect(styles.reActOperationGroup_success).toContain("text-[var(--fg-secondary)]");
    expect(styles.reActOperationGroup_success).not.toContain("state-success");
    expect(styles.reActOperationGroup_running).toContain("bg-transparent");
    expect(styles.reActOperationGroup_running).not.toContain("state-success");
    expect(styles.reActOperationGroup_tool).toContain("text-[var(--fg-secondary)]");
    expect(styles.reActOperationGroup_tool).not.toContain("accent-warm");
    expect(styles.operationIcon_tool).toContain("text-[var(--fg-tertiary)]");
    expect(styles.operationIcon_tool).not.toContain("accent-warm");
    expect(styles.operationText_success).toContain("!text-[var(--fg-secondary)]");
    expect(styles.operationStatus_success).toContain("!text-[var(--fg-tertiary)]");
    expect(styles.operationIcon_success).toContain("!text-[var(--fg-tertiary)]");
    expect(styles.operationText_failed).toContain("!text-[var(--state-error)]");
    expect(styles.timelineOperationCell_failed).toContain("state-error");
  });

  it("separates narrative body color from process/tool rail color like Codex", () => {
    expect(styles.codexTranscriptCommentaryCell).toContain("text-[var(--fg-primary)]");
    expect(styles.codexTranscriptFinalCell).toContain("text-[var(--fg-primary)]");
    expect(styles.codexTranscriptProcessCell).toContain("text-[var(--fg-tertiary)]");
    expect(styles.codexTranscriptCellTitle).toContain("text-[var(--fg-tertiary)]");
    expect(styles.codexTranscriptCellTitle).toContain("font-normal");
  });

  it("keeps compact chat surface readable over the page background", () => {
    expect(styles.surfaceCompact).toContain("bg-[var(--vui-surface-chat)]");
    expect(styles.surfaceCompact).not.toContain("var(--surface-panel)");
    expect(styles.surfaceCompact).not.toContain("backdrop-blur");

    expect(styles.timelineCellPreview).toContain("line-clamp-2");
    expect(styles.timelineCellPreview).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.timelineCellPreview).toContain("text-[var(--fg-secondary)]");
    expect(styles.timelineCellPreview).not.toContain("text-[var(--fg-tertiary)]");
    expect(styles.timelineCellPreview).not.toContain("[font-size:var(--vui-font-xs)]");
  });

  it("keeps progress commentary readable while completed tool summaries remain quiet", () => {
    expect(styles.codexTranscriptCommentaryCell).toContain("text-[var(--fg-primary)]");
    expect(styles.codexTranscriptCommentaryCell).not.toContain("text-[var(--fg-secondary)]");
    expect(styles.codexTranscriptCommentaryCell).toContain("bg-transparent");
    expect(styles.codexTranscriptFinalCell).toContain("leading-[var(--vui-line-readable)]");
    expect(styles.codexTranscriptFinalCell).toContain("text-[var(--fg-primary)]");
    expect(styles.codexTranscriptFinalCell).not.toContain("bg-[var(--state-error)]");
    expect(styles.codexTranscriptErrorCell).toContain("border-l");
    expect(styles.codexTranscriptProcessCell).toContain("border-0");
    expect(styles.codexTranscriptSurface).toContain("w-full");
    expect(styles.codexTranscriptSurface).toContain("max-w-full");
    expect(styles.codexTranscriptSurface).toContain("px-0");
  });
});
