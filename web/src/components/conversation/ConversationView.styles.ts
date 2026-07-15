// Human-owned Tailwind style map for ConversationView. The file still carries
// broad generated coverage for dynamic `styles[`prefix_${tone}`]` lookups, but
// visible shell styles are being migrated into named, reusable slices.
const conversationViewScope = "vui-components-conversationview";

function cv(key: string, ...classNames: string[]) {
  return [conversationViewScope, key, ...classNames].join(" ");
}

const readableMessageText = "min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]";
const readableMarkdownMeasure = "max-w-[min(100%,128ch)]";
const assistantMessageMeasure = "w-[min(100%,1360px)] max-w-full";
const transcriptTurnRail = "w-full max-w-[960px] justify-self-center";
const assistantResponseSection = cv(
  "responseSection",
  "min-w-0 grid",
  assistantMessageMeasure,
  "gap-1 border-l border-[color-mix(in_srgb,var(--fg-tertiary)_24%,var(--vui-border-subtle))] bg-transparent pl-2.5 shadow-none",
);
const assistantResponseBody = cv(
  "responseBody",
  readableMessageText,
  "grid gap-1.5 border-0 bg-transparent py-1 pl-5 pr-0 text-[var(--fg-primary)] shadow-none",
);
const answerOnlyProcessShell = cv(
  "answerOnlyProcessGroup",
  "min-w-0 grid",
  assistantMessageMeasure,
  "gap-1 bg-transparent p-0 text-[var(--fg-secondary)] shadow-none",
);
const userMessageBubble = cv(
  "userMessageBody",
  readableMessageText,
  "w-fit max-w-[min(100%,68ch)] justify-self-end rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_6%,var(--vui-surface-panel))] px-2.5 py-1.5 text-left text-[var(--fg-primary)] shadow-none",
);
const conversationComposerShell = cv(
  "composer",
  "grid flex-none grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-t border-[color-mix(in_srgb,var(--border-soft)_82%,transparent)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_74%,transparent)] px-[11px] py-[7px] pb-[9px] backdrop-blur-[6px] shadow-none",
);
const conversationComposerCodexShell = cv(
  "composerCodex",
  "mx-auto grid w-full max-w-[960px] min-w-0 flex-none rounded-[24px] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] shadow-[var(--vui-shadow-soft)] max-[719px]:rounded-[18px]",
);
const composerNativeFieldTargets =
  "[&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-[48px] [&_textarea]:max-h-[112px] [&_textarea]:resize-none [&_input]:w-full [&_select]:w-full [&_textarea]:w-full";
const composerFieldBase = `min-w-0 grid gap-1 text-[var(--vui-font-xs)] text-[var(--fg-secondary)] ${composerNativeFieldTargets}`;
const composerFieldShell = cv("composerField", composerFieldBase);
const composerFieldCodexShell = cv(
  "composerFieldCodex",
  composerFieldBase,
  "grid min-h-[112px] min-w-0 grid-rows-[auto_minmax(48px,1fr)_auto] gap-1 px-4 py-3 max-[719px]:min-h-[104px] max-[719px]:px-3 max-[719px]:py-2.5",
);
const composerToolbarShell = cv("composerToolbar", "flex min-w-0 items-center gap-1 pt-0.5");
const composerToolbarCodexShell = cv(
  "composerToolbarCodex",
  "flex min-h-8 min-w-0 items-center justify-between gap-2",
);
const composerFieldDragActiveShell = cv(
  "composerFieldDragActive",
  "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)]",
);
const compactControlButton =
  "min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55";
const compactIconButtonSize =
  "h-[var(--vui-control-height-sm)] min-h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)] shrink-0";
const composerQuietActionState =
  "border-[color-mix(in_srgb,var(--border-soft)_70%,transparent)] bg-[color-mix(in_srgb,var(--vui-control-muted)_62%,transparent)] text-[var(--fg-tertiary)] shadow-none transition-colors duration-150 hover:border-[color-mix(in_srgb,var(--border-strong)_72%,transparent)] hover:bg-[color-mix(in_srgb,var(--surface-page)_14%,var(--vui-control-muted-hover))] hover:text-[var(--fg-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--vui-surface-panel)] active:border-[color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))] active:bg-[color-mix(in_srgb,var(--surface-page)_18%,var(--vui-control-muted-hover))] disabled:cursor-default disabled:opacity-45 disabled:hover:border-[color-mix(in_srgb,var(--border-soft)_70%,transparent)] disabled:hover:bg-[color-mix(in_srgb,var(--vui-control-muted)_62%,transparent)] disabled:hover:text-[var(--fg-tertiary)]";
const composerRoundActionButton = cv(
  "composerRoundButton",
  "min-w-0 inline-grid",
  compactIconButtonSize,
  "place-items-center rounded-[var(--radius-control)] border p-0",
  composerQuietActionState,
);
const composerPrimaryActionButton = cv(
  "composerRoundButtonPrimary",
  compactIconButtonSize,
  "p-0 !border-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] !bg-[color-mix(in_srgb,var(--accent-cool)_14%,var(--vui-surface-row))] !text-[var(--accent-cool)] hover:!border-[color-mix(in_srgb,var(--accent-cool)_56%,transparent)] hover:!bg-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-control-muted-hover))] hover:!text-[var(--accent-cool)] focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] active:!border-[color-mix(in_srgb,var(--accent-cool)_62%,transparent)] active:!bg-[color-mix(in_srgb,var(--accent-cool)_22%,var(--vui-surface-row))] disabled:hover:!border-[color-mix(in_srgb,var(--border-soft)_70%,transparent)] disabled:hover:!bg-[color-mix(in_srgb,var(--vui-control-muted)_62%,transparent)] disabled:hover:!text-[var(--fg-tertiary)]",
);
const composerSendActionButton = cv(
  "sendButton",
  compactIconButtonSize,
  "inline-grid place-items-center rounded-[var(--radius-control)] border p-0 !border-[color-mix(in_srgb,var(--accent-cool)_42%,transparent)] !bg-[color-mix(in_srgb,var(--accent-cool)_16%,var(--vui-surface-row))] !text-[var(--accent-cool)] shadow-none transition-colors duration-150 hover:translate-y-0 hover:!border-[color-mix(in_srgb,var(--accent-cool)_56%,transparent)] hover:!bg-[color-mix(in_srgb,var(--accent-cool)_19%,var(--vui-control-muted-hover))] hover:!text-[var(--accent-cool)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--vui-surface-panel)] active:!bg-[color-mix(in_srgb,var(--accent-cool)_22%,var(--vui-surface-row))] disabled:!border-[color-mix(in_srgb,var(--border-soft)_70%,transparent)] disabled:!bg-[color-mix(in_srgb,var(--vui-control-muted)_62%,transparent)] disabled:!text-[var(--fg-tertiary)] disabled:hover:!border-[color-mix(in_srgb,var(--border-soft)_70%,transparent)] disabled:hover:!bg-[color-mix(in_srgb,var(--vui-control-muted)_62%,transparent)] disabled:hover:!text-[var(--fg-tertiary)]",
);
const composerHiddenAttachmentField = cv("hiddenAttachmentInput", composerFieldBase, "hidden");
const composerGenericInputField = cv("input", composerFieldBase);

const styles: Record<string, string> = {
  agentInboxMessageBody:
    "vui-components-conversationview agentInboxMessageBody min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentInboxPreview:
    "vui-components-conversationview agentInboxPreview min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentInboxSection:
    "vui-components-conversationview agentInboxSection min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentInboxToggle:
    "vui-components-conversationview agentInboxToggle min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  agentInboxTurn:
    `vui-components-conversationview agentInboxTurn grid min-w-0 ${transcriptTurnRail} grid-cols-[34px_minmax(0,1fr)] gap-x-3 [&_.turnContent]:w-[min(100%,1360px)] [&_.turnContent]:p-0 [&_.turnContent]:border-l-0`,
  answerOnlyProcessDetails:
    "vui-components-conversationview answerOnlyProcessDetails min-w-0",
  answerOnlyProcessGroup: answerOnlyProcessShell,
  answerOnlyProcessGroup_active:
    "vui-components-conversationview answerOnlyProcessGroup_active min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  answerOnlyProcessGroup_answer:
    "vui-components-conversationview answerOnlyProcessGroup_answer min-w-0",
  answerOnlyProcessGroup_blocked:
    "vui-components-conversationview answerOnlyProcessGroup_blocked min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  answerOnlyProcessGroup_code:
    "vui-components-conversationview answerOnlyProcessGroup_code min-w-0 font-mono text-[var(--vui-font-xs)]",
  answerOnlyProcessGroup_commit:
    "vui-components-conversationview answerOnlyProcessGroup_commit min-w-0",
  answerOnlyProcessGroup_danger:
    "vui-components-conversationview answerOnlyProcessGroup_danger min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  answerOnlyProcessGroup_done:
    "vui-components-conversationview answerOnlyProcessGroup_done min-w-0",
  answerOnlyProcessGroup_error:
    "vui-components-conversationview answerOnlyProcessGroup_error min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  answerOnlyProcessGroup_failed:
    "vui-components-conversationview answerOnlyProcessGroup_failed min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  answerOnlyProcessGroup_files:
    "vui-components-conversationview answerOnlyProcessGroup_files min-w-0",
  answerOnlyProcessGroup_idle:
    "vui-components-conversationview answerOnlyProcessGroup_idle min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-tertiary)]",
  answerOnlyProcessGroup_info:
    "vui-components-conversationview answerOnlyProcessGroup_info min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  answerOnlyProcessGroup_intent:
    "vui-components-conversationview answerOnlyProcessGroup_intent min-w-0",
  answerOnlyProcessGroup_logs:
    "vui-components-conversationview answerOnlyProcessGroup_logs min-w-0",
  answerOnlyProcessGroup_mental:
    "vui-components-conversationview answerOnlyProcessGroup_mental min-w-0",
  answerOnlyProcessGroup_meta:
    "vui-components-conversationview answerOnlyProcessGroup_meta min-w-0 flex flex-wrap items-center gap-1.5",
  answerOnlyProcessGroup_missing:
    "vui-components-conversationview answerOnlyProcessGroup_missing min-w-0",
  answerOnlyProcessGroup_muted:
    "vui-components-conversationview answerOnlyProcessGroup_muted min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  answerOnlyProcessGroup_neutral:
    "vui-components-conversationview answerOnlyProcessGroup_neutral min-w-0",
  answerOnlyProcessGroup_ok:
    "vui-components-conversationview answerOnlyProcessGroup_ok min-w-0 bg-transparent text-[var(--fg-secondary)]",
  answerOnlyProcessGroup_pending:
    "vui-components-conversationview answerOnlyProcessGroup_pending min-w-0",
  answerOnlyProcessGroup_ready:
    "vui-components-conversationview answerOnlyProcessGroup_ready min-w-0 bg-transparent text-[var(--fg-secondary)]",
  answerOnlyProcessGroup_running:
    "vui-components-conversationview answerOnlyProcessGroup_running min-w-0 border-0 bg-transparent text-[var(--fg-secondary)] shadow-none",
  answerOnlyProcessGroup_status:
    "vui-components-conversationview answerOnlyProcessGroup_status min-w-0",
  answerOnlyProcessGroup_success:
    "vui-components-conversationview answerOnlyProcessGroup_success min-w-0 bg-transparent text-[var(--fg-secondary)]",
  answerOnlyProcessGroup_thought:
    "vui-components-conversationview answerOnlyProcessGroup_thought min-w-0",
  answerOnlyProcessGroup_tool:
    "vui-components-conversationview answerOnlyProcessGroup_tool min-w-0 bg-transparent text-[var(--fg-secondary)]",
  answerOnlyProcessGroup_verification:
    "vui-components-conversationview answerOnlyProcessGroup_verification min-w-0",
  answerOnlyProcessGroup_wake:
    "vui-components-conversationview answerOnlyProcessGroup_wake min-w-0",
  answerOnlyProcessGroup_warn:
    "vui-components-conversationview answerOnlyProcessGroup_warn min-w-0",
  answerOnlyProcessGroup_warning:
    "vui-components-conversationview answerOnlyProcessGroup_warning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  answerOnlyProcessIcon:
    "vui-components-conversationview answerOnlyProcessIcon min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  answerOnlyProcessMeta:
    "vui-components-conversationview answerOnlyProcessMeta min-w-0 truncate whitespace-nowrap",
  answerOnlyProcessPreview:
    "vui-components-conversationview answerOnlyProcessPreview min-w-0 truncate whitespace-nowrap border-0 bg-transparent p-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] shadow-none",
  answerOnlyProcessStatic:
    "vui-components-conversationview answerOnlyProcessStatic min-w-0 !inline-grid w-fit max-w-full grid-cols-[14px_auto_auto] items-center gap-1.5",
  answerOnlyProcessTitle:
    "vui-components-conversationview answerOnlyProcessTitle min-w-0 truncate whitespace-nowrap text-[var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]",
  answerOnlyProcessToggle:
    "vui-components-conversationview answerOnlyProcessToggle min-w-0 grid border-0 bg-transparent p-0 text-[var(--fg-secondary)] hover:border-transparent hover:bg-transparent [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:inline-grid [&_[data-slot=vui-button-label]]:max-w-full [&_[data-slot=vui-button-label]]:grid-cols-[14px_auto_auto_minmax(0,1fr)_14px] [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-1.5",
  assistantCard:
    "vui-components-conversationview assistantCard min-w-0 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-strong)_72%,transparent)] bg-[var(--vui-surface-chat-panel)] p-2 shadow-none",
  assistantTurn:
    `vui-components-conversationview assistantTurn grid min-w-0 ${transcriptTurnRail} grid-cols-[34px_minmax(0,1fr)] gap-x-2.5 [&_.turnContent]:w-[min(100%,1360px)] [&_.turnContent]:p-0 [&_.turnContent]:border-l-0`,
  assistantTurnContinuation:
    `vui-components-conversationview assistantTurnContinuation grid min-w-0 ${transcriptTurnRail} grid-cols-[34px_minmax(0,1fr)] gap-x-2.5 [&_.turnAvatar]:bg-transparent [&_.turnContent]:w-[min(100%,1360px)] [&_.turnContent]:gap-1`,
  attachButton:
    cv("attachButton", "min-w-0 inline-grid", compactIconButtonSize, "place-items-center rounded-[var(--radius-control)] border p-0 text-[var(--vui-font-xs)] font-semibold leading-tight", composerQuietActionState),
  auxiliaryBlock:
    "vui-components-conversationview auxiliaryBlock min-w-0",
  auxiliaryBlock_active:
    "vui-components-conversationview auxiliaryBlock_active min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  auxiliaryBlock_answer:
    "vui-components-conversationview auxiliaryBlock_answer min-w-0",
  auxiliaryBlock_blocked:
    "vui-components-conversationview auxiliaryBlock_blocked min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  auxiliaryBlock_code:
    "vui-components-conversationview auxiliaryBlock_code min-w-0 font-mono text-[var(--vui-font-xs)]",
  auxiliaryBlock_commit:
    "vui-components-conversationview auxiliaryBlock_commit min-w-0",
  auxiliaryBlock_danger:
    "vui-components-conversationview auxiliaryBlock_danger min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  auxiliaryBlock_done:
    "vui-components-conversationview auxiliaryBlock_done min-w-0",
  auxiliaryBlock_error:
    "vui-components-conversationview auxiliaryBlock_error min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  auxiliaryBlock_failed:
    "vui-components-conversationview auxiliaryBlock_failed min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  auxiliaryBlock_files:
    "vui-components-conversationview auxiliaryBlock_files min-w-0",
  auxiliaryBlock_idle:
    "vui-components-conversationview auxiliaryBlock_idle min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-tertiary)]",
  auxiliaryBlock_info:
    "vui-components-conversationview auxiliaryBlock_info min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  auxiliaryBlock_intent:
    "vui-components-conversationview auxiliaryBlock_intent min-w-0",
  auxiliaryBlock_logs:
    "vui-components-conversationview auxiliaryBlock_logs min-w-0",
  auxiliaryBlock_mental:
    "vui-components-conversationview auxiliaryBlock_mental min-w-0",
  auxiliaryBlock_meta:
    "vui-components-conversationview auxiliaryBlock_meta min-w-0 flex flex-wrap items-center gap-1.5",
  auxiliaryBlock_missing:
    "vui-components-conversationview auxiliaryBlock_missing min-w-0",
  auxiliaryBlock_muted:
    "vui-components-conversationview auxiliaryBlock_muted min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  auxiliaryBlock_neutral:
    "vui-components-conversationview auxiliaryBlock_neutral min-w-0",
  auxiliaryBlock_ok:
    "vui-components-conversationview auxiliaryBlock_ok min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  auxiliaryBlock_pending:
    "vui-components-conversationview auxiliaryBlock_pending min-w-0",
  auxiliaryBlock_ready:
    "vui-components-conversationview auxiliaryBlock_ready min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  auxiliaryBlock_running:
    "vui-components-conversationview auxiliaryBlock_running min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  auxiliaryBlock_status:
    "vui-components-conversationview auxiliaryBlock_status min-w-0",
  auxiliaryBlock_success:
    "vui-components-conversationview auxiliaryBlock_success min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  auxiliaryBlock_thought:
    "vui-components-conversationview auxiliaryBlock_thought min-w-0",
  auxiliaryBlock_tool:
    "vui-components-conversationview auxiliaryBlock_tool min-w-0 border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  auxiliaryBlock_verification:
    "vui-components-conversationview auxiliaryBlock_verification min-w-0",
  auxiliaryBlock_wake:
    "vui-components-conversationview auxiliaryBlock_wake min-w-0",
  auxiliaryBlock_warn:
    "vui-components-conversationview auxiliaryBlock_warn min-w-0",
  auxiliaryBlock_warning:
    "vui-components-conversationview auxiliaryBlock_warning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  auxiliaryPanel:
    "vui-components-conversationview auxiliaryPanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  auxiliaryPanel_mental:
    "vui-components-conversationview auxiliaryPanel_mental min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  auxiliaryPanel_thought:
    "vui-components-conversationview auxiliaryPanel_thought min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  backToBottomButton:
    "vui-components-conversationview backToBottomButton absolute bottom-[calc(var(--vui-control-height-md)_+_18px)] left-1/2 z-20 min-w-0 -translate-x-1/2 !inline-flex min-h-[var(--vui-control-height-sm)] !w-fit max-w-[calc(100%_-_24px)] items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-control-muted)_92%,var(--vui-surface-panel))] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] shadow-[var(--vui-shadow-soft)] backdrop-blur-[6px] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 [&_[data-slot=vui-button-content]]:!inline-flex [&_[data-slot=vui-button-content]]:!w-fit [&_[data-slot=vui-button-content]]:items-center [&_[data-slot=vui-button-content]]:gap-1.5 [&_[data-slot=vui-button-label]]:!inline-flex [&_[data-slot=vui-button-label]]:!w-fit [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-1.5",
  cliAgentLifecycleIcon:
    "vui-components-conversationview cliAgentLifecycleIcon min-w-0 shrink-0 text-[var(--fg-tertiary)] border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  cliAgentLifecycleMeta:
    "vui-components-conversationview cliAgentLifecycleMeta min-w-0 flex flex-wrap items-center gap-1.5 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)] [&_time]:flex-none",
  cliAgentLifecycleText:
    "vui-components-conversationview cliAgentLifecycleText min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  cliAgentLifecycleTime:
    "vui-components-conversationview cliAgentLifecycleTime min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  cliAgentLifecycleTurn:
    "vui-components-conversationview cliAgentLifecycleTurn min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)] bg-[color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)]",
  composer: conversationComposerShell,
  composerAttachmentChip:
    "vui-components-conversationview composerAttachmentChip min-w-0 inline-flex min-h-7 w-fit max-w-full items-center justify-start gap-1.5 overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 pr-1 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  composerAttachmentName:
    "vui-components-conversationview composerAttachmentName min-w-0 max-w-[14rem] truncate",
  composerAttachmentRemoveButton:
    "vui-components-conversationview composerAttachmentRemoveButton !h-6 !min-h-6 !w-6 !min-w-6 shrink-0 !rounded-full !p-0",
  composerAttachmentThumb:
    "vui-components-conversationview composerAttachmentThumb block h-5 max-h-5 w-5 max-w-5 shrink-0 rounded-[var(--radius-control)] object-cover",
  composerAttachmentTray:
    "vui-components-conversationview composerAttachmentTray min-w-0 max-w-full overflow-hidden flex flex-wrap items-center gap-1.5",
  composerActionStack:
    "vui-components-conversationview composerActionStack grid min-w-0 w-fit grid-cols-1 content-end items-end gap-1 self-end justify-self-end",
  composerError:
    "vui-components-conversationview composerError min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  composerEditModeDescription:
    "vui-components-conversationview composerEditModeDescription min-w-0 whitespace-normal break-words text-[var(--vui-font-xs)] font-medium leading-[1.45] text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
  composerEditModeBar:
    "vui-components-conversationview composerEditModeBar grid min-w-0 min-h-8 w-full max-w-full grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-2 gap-y-1 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] px-2 py-1.5 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  composerEditModeCancel:
    "vui-components-conversationview composerEditModeCancel !min-h-6 !w-fit !rounded-[var(--radius-control)] !px-1.5 !py-0 text-[var(--vui-font-xs)] font-semibold leading-none",
  composerEditModeCopy:
    "vui-components-conversationview composerEditModeCopy grid min-w-0 gap-0.5",
  composerEditModeIcon:
    "vui-components-conversationview composerEditModeIcon min-w-0 shrink-0 pt-0.5 text-[var(--accent-cool)]",
  composerEditModeLabel:
    "vui-components-conversationview composerEditModeLabel min-w-0 truncate font-semibold text-[var(--fg-primary)]",
  composerEditModePreview:
    "vui-components-conversationview composerEditModePreview min-w-0 max-w-full truncate text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  composerEditModeWarning:
    "vui-components-conversationview composerEditModeWarning min-w-0 whitespace-normal break-words text-[var(--vui-font-xs)] font-semibold leading-[1.45] text-[var(--state-warning)] [overflow-wrap:anywhere]",
  composerEditSubmitButton:
    "vui-components-conversationview composerEditSubmitButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-[min(100%,11rem)] items-center justify-center gap-1.5 rounded-[var(--radius-control)] border px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight shadow-none",
  composerField: composerFieldShell,
  composerFieldCodex: composerFieldCodexShell,
  composerFieldDragActive: composerFieldDragActiveShell,
  composerGuidance:
    "vui-components-conversationview composerGuidance min-w-0",
  composerGuidanceIcon:
    "vui-components-conversationview composerGuidanceIcon min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  composerModeNotice:
    "vui-components-conversationview composerModeNotice min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  composerModeNoticeIcon:
    "vui-components-conversationview composerModeNoticeIcon min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 shrink-0 text-[var(--fg-tertiary)]",
  composerReferenceChip:
    "vui-components-conversationview composerReferenceChip min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  composerReferenceCopy:
    "vui-components-conversationview composerReferenceCopy min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  composerReferenceIcon:
    "vui-components-conversationview composerReferenceIcon min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  composerReferenceTray:
    "vui-components-conversationview composerReferenceTray min-w-0",
  composerRoundButton: composerRoundActionButton,
  composerRoundButtonPrimary: composerPrimaryActionButton,
  computerUseActions:
    "vui-components-conversationview computerUseActions min-w-0 flex flex-wrap items-center gap-1.5",
  computerUseError:
    "vui-components-conversationview computerUseError min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  computerUseHeader:
    "vui-components-conversationview computerUseHeader min-w-0 flex flex-wrap items-center gap-1.5",
  computerUsePanel:
    "vui-components-conversationview computerUsePanel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  computerUseScreenshot:
    "vui-components-conversationview computerUseScreenshot min-w-0",
  computerUseSteps:
    "vui-components-conversationview computerUseSteps min-w-0",
  computerUseSummary:
    "vui-components-conversationview computerUseSummary min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  codexTranscriptAssistantCell:
    "vui-components-conversationview codexTranscriptAssistantCell min-w-0 grid gap-1 border-0 bg-transparent shadow-none",
  codexTranscriptCell:
    "vui-components-conversationview codexTranscriptCell min-w-0",
  codexTranscriptCellBody:
    "vui-components-conversationview codexTranscriptCellBody min-w-0 grid gap-0.5",
  codexTranscriptCompactErrorDetails:
    "vui-components-conversationview codexTranscriptCompactErrorDetails inline-block min-w-0 shrink-0 border-0 bg-transparent group",
  codexTranscriptCompactErrorDetailsSummary:
    "vui-components-conversationview codexTranscriptCompactErrorDetailsSummary inline-flex cursor-pointer list-none select-none items-center gap-1 [&::-webkit-details-marker]:hidden",
  codexTranscriptCompactErrorSummary:
    "vui-components-conversationview codexTranscriptCompactErrorSummary min-w-0 flex-1 whitespace-normal break-words text-[var(--vui-font-xs)] leading-[var(--vui-line-tight)] text-[var(--state-error)] [overflow-wrap:anywhere]",
  codexTranscriptCellIcon:
    "vui-components-conversationview codexTranscriptCellIcon mt-[0.15rem] grid size-4 shrink-0 place-items-center text-[var(--fg-tertiary)]",
  codexTranscriptCellMeta:
    "vui-components-conversationview codexTranscriptCellMeta inline-flex min-w-0 shrink-0 align-baseline whitespace-nowrap text-[var(--vui-font-xs)] leading-[var(--vui-line-tight)] text-[var(--fg-tertiary)]",
  codexTranscriptCellSummary:
    "vui-components-conversationview codexTranscriptCellSummary min-w-0 max-w-[min(100%,128ch)] text-[var(--vui-font-sm)] leading-[1.42] text-[var(--fg-secondary)] whitespace-normal break-words [overflow-wrap:anywhere]",
  codexTranscriptCellTitle:
    "vui-components-conversationview codexTranscriptCellTitle min-w-0 whitespace-normal text-[var(--vui-font-sm)] font-semibold leading-[1.35] text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
  codexTranscriptCellTitleRow:
    "vui-components-conversationview codexTranscriptCellTitleRow min-w-0 inline-flex max-w-full flex-wrap items-baseline gap-x-2 gap-y-0.5",
  codexTranscriptCommentaryCell:
    "vui-components-conversationview codexTranscriptCommentaryCell border-0 bg-transparent py-1 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  codexTranscriptErrorCell:
    "vui-components-conversationview codexTranscriptErrorCell border-0 border-l-2 border-l-[var(--state-error)] bg-[color-mix(in_srgb,var(--state-error)_5%,transparent)] px-3 py-2",
  codexTranscriptFinalCell:
    "vui-components-conversationview codexTranscriptFinalCell border-0 bg-transparent py-2 text-[var(--fg-primary)] leading-[var(--vui-line-readable)] [&_.markdownBody]:max-w-full [&_pre]:max-w-full [&_pre]:overflow-x-auto [&_table]:max-w-full [&_img]:max-w-full [&_a]:break-words",
  codexTranscriptCell_error:
    "vui-components-conversationview codexTranscriptCell_error border-0 border-l-2 border-l-[var(--state-error)] bg-[color-mix(in_srgb,var(--state-error)_5%,transparent)] px-3 py-2 text-[var(--fg-secondary)] [&_.codexTranscriptCellIcon]:text-[var(--state-error)] [&_.codexTranscriptCellMeta]:text-[var(--state-error)] [&_.codexTranscriptCellTitle]:text-[var(--state-error)]",
  codexTranscriptCell_neutral:
    "vui-components-conversationview codexTranscriptCell_neutral text-[var(--fg-secondary)]",
  codexTranscriptCell_running:
    "vui-components-conversationview codexTranscriptCell_running text-[var(--fg-secondary)]",
  codexTranscriptCell_warning:
    "vui-components-conversationview codexTranscriptCell_warning text-[var(--state-warning)] [&_.codexTranscriptCellIcon]:text-[var(--state-warning)] [&_.codexTranscriptCellMeta]:text-[var(--state-warning)] [&_.codexTranscriptCellTitle]:text-[var(--state-warning)]",
  codexTranscriptProcessCell:
    "vui-components-conversationview codexTranscriptProcessCell grid grid-cols-[20px_minmax(0,1fr)] items-start gap-x-2 gap-y-1 border-0 bg-transparent py-1 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)]",
  codexTranscriptSurface:
    "vui-components-conversationview codexTranscriptSurface mx-auto grid w-[min(100%,1360px)] max-w-[880px] min-w-0 content-start gap-2 px-3 sm:px-5",
  conversationCellTimeline:
    "vui-components-conversationview conversationCellTimeline min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  emptyState:
    "vui-components-conversationview emptyState min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  executionRequestSummary:
    "vui-components-conversationview executionRequestSummary min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  executionTraceGroup:
    "vui-components-conversationview executionTraceGroup min-w-0 border-0 bg-transparent",
  eyebrow:
    "vui-components-conversationview eyebrow min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  groupTranscriptBody:
    "vui-components-conversationview groupTranscriptBody min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  groupTranscriptTurn:
    `vui-components-conversationview groupTranscriptTurn grid min-w-0 ${transcriptTurnRail} grid-cols-[34px_minmax(0,1fr)] gap-x-3 [&_.turnContent]:w-[min(100%,1360px)] [&_.turnContent]:p-0 [&_.turnContent]:border-l-0`,
  header:
    "vui-components-conversationview header min-w-0 flex flex-wrap items-center gap-1.5",
  headerControls:
    "vui-components-conversationview headerControls min-w-0 flex flex-wrap items-center gap-1.5",
  hiddenAttachmentInput: composerHiddenAttachmentField,
  imageArtifact:
    "vui-components-conversationview imageArtifact min-w-0",
  imageArtifactFooter:
    "vui-components-conversationview imageArtifactFooter min-w-0 flex flex-wrap items-center gap-1.5",
  imageArtifactFrame:
    "vui-components-conversationview imageArtifactFrame min-w-0",
  imageArtifactMeta:
    "vui-components-conversationview imageArtifactMeta min-w-0 flex flex-wrap items-center gap-1.5",
  imageArtifactPrompt:
    "vui-components-conversationview imageArtifactPrompt min-w-0",
  imageDownloadButton:
    "vui-components-conversationview imageDownloadButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  imagePreview:
    "vui-components-conversationview imagePreview min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  imagePreviewActions:
    "vui-components-conversationview imagePreviewActions min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 flex flex-wrap items-center gap-1.5",
  imagePreviewButton:
    "vui-components-conversationview imagePreviewButton min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  imagePreviewCloseButton:
    "vui-components-conversationview imagePreviewCloseButton min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  imagePreviewDialog:
    "vui-components-conversationview imagePreviewDialog min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  imagePreviewLarge:
    "vui-components-conversationview imagePreviewLarge min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  imagePreviewOverlay:
    "vui-components-conversationview imagePreviewOverlay min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  imagePreviewToolbar:
    "vui-components-conversationview imagePreviewToolbar min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 flex flex-wrap items-center gap-1.5",
  inlineCode:
    "vui-components-conversationview inlineCode min-w-0 font-mono text-[var(--vui-font-xs)] whitespace-normal break-words",
  inlineLink:
    "vui-components-conversationview inlineLink min-w-0",
  inlineStrong:
    "vui-components-conversationview inlineStrong min-w-0",
  input: composerGenericInputField,
  markdownBlockquote:
    "vui-components-conversationview markdownBlockquote min-w-0",
  markdownBody:
    `vui-components-conversationview markdownBody min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] ${readableMarkdownMeasure}`,
  markdownBodyWithTable:
    "vui-components-conversationview markdownBodyWithTable min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] max-w-full",
  markdownDivider:
    "vui-components-conversationview markdownDivider min-w-0",
  markdownHeading:
    "vui-components-conversationview markdownHeading min-w-0",
  markdownHeading1:
    "vui-components-conversationview markdownHeading1 min-w-0",
  markdownHeading2:
    "vui-components-conversationview markdownHeading2 min-w-0",
  markdownHeading3:
    "vui-components-conversationview markdownHeading3 min-w-0",
  markdownHeading4:
    "vui-components-conversationview markdownHeading4 min-w-0",
  markdownHeadingactive:
    "vui-components-conversationview markdownHeadingactive min-w-0",
  markdownHeadinganswer:
    "vui-components-conversationview markdownHeadinganswer min-w-0",
  markdownHeadingblocked:
    "vui-components-conversationview markdownHeadingblocked min-w-0",
  markdownHeadingcode:
    "vui-components-conversationview markdownHeadingcode min-w-0",
  markdownHeadingcommit:
    "vui-components-conversationview markdownHeadingcommit min-w-0",
  markdownHeadingdanger:
    "vui-components-conversationview markdownHeadingdanger min-w-0",
  markdownHeadingdone:
    "vui-components-conversationview markdownHeadingdone min-w-0",
  markdownHeadingerror:
    "vui-components-conversationview markdownHeadingerror min-w-0",
  markdownHeadingfailed:
    "vui-components-conversationview markdownHeadingfailed min-w-0",
  markdownHeadingfiles:
    "vui-components-conversationview markdownHeadingfiles min-w-0",
  markdownHeadingidle:
    "vui-components-conversationview markdownHeadingidle min-w-0",
  markdownHeadinginfo:
    "vui-components-conversationview markdownHeadinginfo min-w-0",
  markdownHeadingintent:
    "vui-components-conversationview markdownHeadingintent min-w-0",
  markdownHeadinglogs:
    "vui-components-conversationview markdownHeadinglogs min-w-0",
  markdownHeadingmental:
    "vui-components-conversationview markdownHeadingmental min-w-0",
  markdownHeadingmeta:
    "vui-components-conversationview markdownHeadingmeta min-w-0",
  markdownHeadingmissing:
    "vui-components-conversationview markdownHeadingmissing min-w-0",
  markdownHeadingmuted:
    "vui-components-conversationview markdownHeadingmuted min-w-0",
  markdownHeadingneutral:
    "vui-components-conversationview markdownHeadingneutral min-w-0",
  markdownHeadingok:
    "vui-components-conversationview markdownHeadingok min-w-0",
  markdownHeadingpending:
    "vui-components-conversationview markdownHeadingpending min-w-0",
  markdownHeadingready:
    "vui-components-conversationview markdownHeadingready min-w-0",
  markdownHeadingrunning:
    "vui-components-conversationview markdownHeadingrunning min-w-0",
  markdownHeadingstatus:
    "vui-components-conversationview markdownHeadingstatus min-w-0",
  markdownHeadingsuccess:
    "vui-components-conversationview markdownHeadingsuccess min-w-0",
  markdownHeadingthought:
    "vui-components-conversationview markdownHeadingthought min-w-0",
  markdownHeadingtool:
    "vui-components-conversationview markdownHeadingtool min-w-0",
  markdownHeadingverification:
    "vui-components-conversationview markdownHeadingverification min-w-0",
  markdownHeadingwake:
    "vui-components-conversationview markdownHeadingwake min-w-0",
  markdownHeadingwarn:
    "vui-components-conversationview markdownHeadingwarn min-w-0",
  markdownHeadingwarning:
    "vui-components-conversationview markdownHeadingwarning min-w-0",
  markdownImage:
    "vui-components-conversationview markdownImage min-w-0",
  markdownImageCaption:
    "vui-components-conversationview markdownImageCaption min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  markdownImageFigure:
    "vui-components-conversationview markdownImageFigure min-w-0",
  markdownImageLink:
    "vui-components-conversationview markdownImageLink min-w-0",
  markdownTable:
    "vui-components-conversationview markdownTable min-w-full table-fixed",
  markdownTableWrap:
    "vui-components-conversationview markdownTableWrap max-w-full overflow-x-auto overflow-y-hidden [scrollbar-gutter:stable]",
  mentalBodyList:
    "vui-components-conversationview mentalBodyList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  mentalBodyRow:
    "vui-components-conversationview mentalBodyRow min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  mentalIntervention:
    "vui-components-conversationview mentalIntervention min-w-0",
  mentalMetaGrid:
    "vui-components-conversationview mentalMetaGrid min-w-0 flex flex-wrap items-center gap-1.5 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  mentalMetaItem:
    "vui-components-conversationview mentalMetaItem min-w-0 flex flex-wrap items-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  mentalSnapshot:
    "vui-components-conversationview mentalSnapshot min-w-0",
  mentalSummary:
    "vui-components-conversationview mentalSummary min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  mentalWhisper:
    "vui-components-conversationview mentalWhisper min-w-0",
  messageBody:
    `vui-components-conversationview messageBody min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] whitespace-pre-wrap [overflow-wrap:anywhere] ${readableMarkdownMeasure}`,
  messageCard:
    "vui-components-conversationview messageCard min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  messageMeta:
    "vui-components-conversationview messageMeta min-w-0 flex flex-wrap items-center gap-1.5 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  metaStack:
    "vui-components-conversationview metaStack min-w-0 flex flex-wrap items-center gap-1.5",
  nextStateSignalEvent:
    "vui-components-conversationview nextStateSignalEvent min-w-0",
  nextStateSignalItem:
    "vui-components-conversationview nextStateSignalItem min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  nextStateSignalKind:
    "vui-components-conversationview nextStateSignalKind min-w-0",
  nextStateSignalList:
    "vui-components-conversationview nextStateSignalList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  nextStateSignalMeta:
    "vui-components-conversationview nextStateSignalMeta min-w-0 flex flex-wrap items-center gap-1.5",
  nextStateSignalText:
    "vui-components-conversationview nextStateSignalText min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  nextStateSignals:
    "vui-components-conversationview nextStateSignals min-w-0",
  nextStateSignalsCount:
    "vui-components-conversationview nextStateSignalsCount min-w-0",
  nextStateSignalsSummary:
    "vui-components-conversationview nextStateSignalsSummary min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  nextStateSignalsToggle:
    "vui-components-conversationview nextStateSignalsToggle min-w-0",
  operationChevron:
    "vui-components-conversationview operationChevron min-w-0",
  operationDetailLabel:
    "vui-components-conversationview operationDetailLabel min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  operationDetailRow:
    "vui-components-conversationview operationDetailRow min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 rounded-[var(--radius-control)] bg-[var(--vui-surface-row)]",
  operationDetailToggle:
    "vui-components-conversationview operationDetailToggle min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  operationDetailValue:
    "vui-components-conversationview operationDetailValue min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  operationDetails:
    "vui-components-conversationview operationDetails min-w-0 border-0 bg-transparent",
  operationDetailsChevronButton:
    "vui-components-conversationview operationDetailsChevronButton inline-flex size-4 min-w-0 shrink-0 items-center justify-center border-0 bg-transparent p-0 text-[var(--fg-tertiary)] leading-none hover:text-[var(--fg-primary)]",
  operationDetailsChevronClosed:
    "vui-components-conversationview operationDetailsChevronClosed inline-flex group-open:hidden",
  operationDetailsChevronOpen:
    "vui-components-conversationview operationDetailsChevronOpen hidden group-open:inline-flex",
  operationDetailsDisclosure:
    "vui-components-conversationview operationDetailsDisclosure min-w-0 border-0 bg-transparent group",
  operationDetailsSummary:
    "vui-components-conversationview operationDetailsSummary min-w-0 flex cursor-pointer list-none select-none items-center gap-1.5 [&::-webkit-details-marker]:hidden",
  operationDetails_thought:
    "vui-components-conversationview operationDetails_thought min-w-0",
  operationDuration:
    "vui-components-conversationview operationDuration min-w-0",
  operationGroup:
    "vui-components-conversationview operationGroup min-w-0",
  operationIcon:
    "vui-components-conversationview operationIcon inline-grid size-4 min-w-0 shrink-0 place-items-center text-[var(--fg-tertiary)]",
  operationIcon_active:
    "vui-components-conversationview operationIcon_active min-w-0 shrink-0 text-[var(--fg-tertiary)] border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  operationIcon_answer:
    "vui-components-conversationview operationIcon_answer min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_blocked:
    "vui-components-conversationview operationIcon_blocked min-w-0 shrink-0 text-[var(--fg-tertiary)] border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  operationIcon_code:
    "vui-components-conversationview operationIcon_code min-w-0 shrink-0 text-[var(--fg-tertiary)] font-mono text-[var(--vui-font-xs)]",
  operationIcon_commit:
    "vui-components-conversationview operationIcon_commit min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_danger:
    "vui-components-conversationview operationIcon_danger min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)] shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_done:
    "vui-components-conversationview operationIcon_done min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_error:
    "vui-components-conversationview operationIcon_error min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)] shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_failed:
    "vui-components-conversationview operationIcon_failed min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] !text-[var(--state-error)] shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_files:
    "vui-components-conversationview operationIcon_files min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_idle:
    "vui-components-conversationview operationIcon_idle min-w-0 shrink-0 text-[var(--fg-tertiary)] border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)]",
  operationIcon_info:
    "vui-components-conversationview operationIcon_info min-w-0 shrink-0 text-[var(--fg-tertiary)] border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  operationIcon_intent:
    "vui-components-conversationview operationIcon_intent min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_logs:
    "vui-components-conversationview operationIcon_logs min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_mental:
    "vui-components-conversationview operationIcon_mental min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_meta:
    "vui-components-conversationview operationIcon_meta min-w-0 flex flex-wrap items-center gap-1.5 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_missing:
    "vui-components-conversationview operationIcon_missing min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_muted:
    "vui-components-conversationview operationIcon_muted min-w-0 shrink-0 text-[var(--fg-tertiary)] text-[var(--vui-font-xs)] leading-tight",
  operationIcon_neutral:
    "vui-components-conversationview operationIcon_neutral min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_ok:
    "vui-components-conversationview operationIcon_ok min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_pending:
    "vui-components-conversationview operationIcon_pending min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_ready:
    "vui-components-conversationview operationIcon_ready min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_running:
    "vui-components-conversationview operationIcon_running min-w-0 shrink-0 text-[var(--fg-secondary)]",
  operationIcon_status:
    "vui-components-conversationview operationIcon_status min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_success:
    "vui-components-conversationview operationIcon_success min-w-0 shrink-0 !text-[var(--fg-tertiary)]",
  operationIcon_thought:
    "vui-components-conversationview operationIcon_thought min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_tool:
    "vui-components-conversationview operationIcon_tool min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_verification:
    "vui-components-conversationview operationIcon_verification min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_wake:
    "vui-components-conversationview operationIcon_wake min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_warn:
    "vui-components-conversationview operationIcon_warn min-w-0 shrink-0 text-[var(--fg-tertiary)]",
  operationIcon_warning:
    "vui-components-conversationview operationIcon_warning min-w-0 shrink-0 text-[var(--fg-tertiary)] border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] !text-[var(--state-warning)]",
  operationItem:
    "vui-components-conversationview operationItem min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 w-[min(100%,72ch)] grid grid-cols-[22px_minmax(0,1fr)_auto_auto_16px] items-start gap-1.5 !rounded-none !border-x-0 !border-t-0 border-b border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] !bg-transparent !p-0 !pb-1 !text-[var(--fg-secondary)] !shadow-none",
  operationItemActive:
    "vui-components-conversationview operationItemActive min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  operationItemTool:
    "vui-components-conversationview operationItemTool min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 text-[var(--fg-secondary)] max-w-full",
  operationItemWrap:
    "vui-components-conversationview operationItemWrap min-w-0 border-0 bg-transparent p-0 shadow-none",
  operationItem_active:
    "vui-components-conversationview operationItem_active min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  operationItem_answer:
    "vui-components-conversationview operationItem_answer min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_blocked:
    "vui-components-conversationview operationItem_blocked min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  operationItem_code:
    "vui-components-conversationview operationItem_code min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 font-mono text-[var(--vui-font-xs)]",
  operationItem_commit:
    "vui-components-conversationview operationItem_commit min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_danger:
    "vui-components-conversationview operationItem_danger min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  operationItem_done:
    "vui-components-conversationview operationItem_done min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_error:
    "vui-components-conversationview operationItem_error min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  operationItem_failed:
    "vui-components-conversationview operationItem_failed min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 !border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] !bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] !text-[var(--state-error)]",
  operationItem_files:
    "vui-components-conversationview operationItem_files min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_idle:
    "vui-components-conversationview operationItem_idle min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 text-[var(--fg-tertiary)]",
  operationItem_info:
    "vui-components-conversationview operationItem_info min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  operationItem_intent:
    "vui-components-conversationview operationItem_intent min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_logs:
    "vui-components-conversationview operationItem_logs min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_mental:
    "vui-components-conversationview operationItem_mental min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_meta:
    "vui-components-conversationview operationItem_meta min-w-0 flex flex-wrap items-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_missing:
    "vui-components-conversationview operationItem_missing min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_muted:
    "vui-components-conversationview operationItem_muted min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  operationItem_neutral:
    "vui-components-conversationview operationItem_neutral min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_ok:
    "vui-components-conversationview operationItem_ok min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 text-[var(--fg-secondary)]",
  operationItem_pending:
    "vui-components-conversationview operationItem_pending min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_ready:
    "vui-components-conversationview operationItem_ready min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 text-[var(--fg-secondary)]",
  operationItem_running:
    "vui-components-conversationview operationItem_running min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 text-[var(--fg-secondary)]",
  operationItem_status:
    "vui-components-conversationview operationItem_status min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_success:
    "vui-components-conversationview operationItem_success min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 !text-[var(--fg-secondary)]",
  operationItem_thought:
    "vui-components-conversationview operationItem_thought min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_tool:
    "vui-components-conversationview operationItem_tool min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 text-[var(--fg-secondary)]",
  operationItem_verification:
    "vui-components-conversationview operationItem_verification min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_wake:
    "vui-components-conversationview operationItem_wake min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_warn:
    "vui-components-conversationview operationItem_warn min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationItem_warning:
    "vui-components-conversationview operationItem_warning min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 !border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] !bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] !text-[var(--state-warning)]",
  operationName:
    "vui-components-conversationview operationName min-w-0 text-[var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]",
  operationStatus:
    "vui-components-conversationview operationStatus min-w-0 justify-self-start",
  operationStatus_failed:
    "vui-components-conversationview operationStatus_failed min-w-0 !text-[var(--state-error)]",
  operationStatus_success:
    "vui-components-conversationview operationStatus_success min-w-0 !text-[var(--fg-tertiary)]",
  operationStatus_warning:
    "vui-components-conversationview operationStatus_warning min-w-0 !text-[var(--state-warning)]",
  operationStatusLead:
    "vui-components-conversationview operationStatusLead min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  operationStatusLine:
    "vui-components-conversationview operationStatusLine min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  operationStatusMeta:
    "vui-components-conversationview operationStatusMeta min-w-0 flex flex-wrap items-center gap-1.5",
  operationSummary:
    "vui-components-conversationview operationSummary min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  operationSummaryCount:
    "vui-components-conversationview operationSummaryCount min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2",
  operationSummaryPreview:
    "vui-components-conversationview operationSummaryPreview min-w-0 border-0 bg-transparent p-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] shadow-none line-clamp-1 whitespace-normal [overflow-wrap:anywhere]",
  operationSummaryText:
    "vui-components-conversationview operationSummaryText min-w-0 border-0 bg-transparent p-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] shadow-none line-clamp-1 whitespace-normal [overflow-wrap:anywhere]",
  operationText:
    "vui-components-conversationview operationText min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] max-w-full",
  operationText_failed:
    "vui-components-conversationview operationText_failed min-w-0 !text-[var(--state-error)]",
  operationText_success:
    "vui-components-conversationview operationText_success min-w-0 !text-[var(--fg-secondary)]",
  operationText_warning:
    "vui-components-conversationview operationText_warning min-w-0 !text-[var(--state-warning)]",
  operationTimeline:
    "vui-components-conversationview operationTimeline min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  operationTimelineTrimmed:
    "vui-components-conversationview operationTimelineTrimmed min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  phase:
    "vui-components-conversationview phase min-w-0",
  reActOperationBody:
    "vui-components-conversationview reActOperationBody min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  reActOperationGroup:
    "vui-components-conversationview reActOperationGroup min-w-0 border-l-0 bg-transparent",
  reActOperationGroup_active:
    "vui-components-conversationview reActOperationGroup_active min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  reActOperationGroup_answer:
    "vui-components-conversationview reActOperationGroup_answer min-w-0",
  reActOperationGroup_blocked:
    "vui-components-conversationview reActOperationGroup_blocked min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  reActOperationGroup_code:
    "vui-components-conversationview reActOperationGroup_code min-w-0 font-mono text-[var(--vui-font-xs)]",
  reActOperationGroup_commit:
    "vui-components-conversationview reActOperationGroup_commit min-w-0",
  reActOperationGroup_danger:
    "vui-components-conversationview reActOperationGroup_danger min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  reActOperationGroup_done:
    "vui-components-conversationview reActOperationGroup_done min-w-0",
  reActOperationGroup_error:
    "vui-components-conversationview reActOperationGroup_error min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  reActOperationGroup_failed:
    "vui-components-conversationview reActOperationGroup_failed min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  reActOperationGroup_files:
    "vui-components-conversationview reActOperationGroup_files min-w-0",
  reActOperationGroup_idle:
    "vui-components-conversationview reActOperationGroup_idle min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-tertiary)]",
  reActOperationGroup_info:
    "vui-components-conversationview reActOperationGroup_info min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  reActOperationGroup_intent:
    "vui-components-conversationview reActOperationGroup_intent min-w-0",
  reActOperationGroup_logs:
    "vui-components-conversationview reActOperationGroup_logs min-w-0",
  reActOperationGroup_mental:
    "vui-components-conversationview reActOperationGroup_mental min-w-0",
  reActOperationGroup_meta:
    "vui-components-conversationview reActOperationGroup_meta min-w-0 flex flex-wrap items-center gap-1.5",
  reActOperationGroup_missing:
    "vui-components-conversationview reActOperationGroup_missing min-w-0",
  reActOperationGroup_muted:
    "vui-components-conversationview reActOperationGroup_muted min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  reActOperationGroup_neutral:
    "vui-components-conversationview reActOperationGroup_neutral min-w-0",
  reActOperationGroup_ok:
    "vui-components-conversationview reActOperationGroup_ok min-w-0 bg-transparent text-[var(--fg-secondary)]",
  reActOperationGroup_pending:
    "vui-components-conversationview reActOperationGroup_pending min-w-0",
  reActOperationGroup_ready:
    "vui-components-conversationview reActOperationGroup_ready min-w-0 bg-transparent text-[var(--fg-secondary)]",
  reActOperationGroup_running:
    "vui-components-conversationview reActOperationGroup_running min-w-0 bg-transparent text-[var(--fg-secondary)]",
  reActOperationGroup_status:
    "vui-components-conversationview reActOperationGroup_status min-w-0",
  reActOperationGroup_success:
    "vui-components-conversationview reActOperationGroup_success min-w-0 bg-transparent text-[var(--fg-secondary)]",
  reActOperationGroup_thought:
    "vui-components-conversationview reActOperationGroup_thought min-w-0",
  reActOperationGroup_tool:
    "vui-components-conversationview reActOperationGroup_tool min-w-0 bg-transparent text-[var(--fg-secondary)]",
  reActOperationGroup_verification:
    "vui-components-conversationview reActOperationGroup_verification min-w-0",
  reActOperationGroup_wake:
    "vui-components-conversationview reActOperationGroup_wake min-w-0",
  reActOperationGroup_warn:
    "vui-components-conversationview reActOperationGroup_warn min-w-0",
  reActOperationGroup_warning:
    "vui-components-conversationview reActOperationGroup_warning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  reActOperationList:
    "vui-components-conversationview reActOperationList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  reActOperationMeta:
    "vui-components-conversationview reActOperationMeta min-w-0 flex flex-wrap items-center gap-1.5",
  reActOperationSection:
    "vui-components-conversationview reActOperationSection min-w-0",
  reActOperationSectionLabel:
    "vui-components-conversationview reActOperationSectionLabel min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  reActOperationSummary:
    "vui-components-conversationview reActOperationSummary min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)] p-2 inline-grid w-fit border-0 bg-transparent",
  reActOperationTitle:
    "vui-components-conversationview reActOperationTitle min-w-0 text-[var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]",
  reActResultItem:
    "vui-components-conversationview reActResultItem min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-0 bg-transparent",
  reActResultItem_failed:
    "vui-components-conversationview reActResultItem_failed min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  reActResultLabel:
    "vui-components-conversationview reActResultLabel min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  reActResultList:
    "vui-components-conversationview reActResultList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  reActResultToggle:
    "vui-components-conversationview reActResultToggle min-w-0 border-0 bg-transparent",
  reActResultValue:
    "vui-components-conversationview reActResultValue min-w-0",
  reActThoughtStack:
    "vui-components-conversationview reActThoughtStack min-w-0",
  reActThoughtText:
    "vui-components-conversationview reActThoughtText min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] border-l-0 bg-transparent",
  reActToolDetailToggle:
    "vui-components-conversationview reActToolDetailToggle min-w-0 border-0 bg-transparent p-0 text-[var(--fg-tertiary)] shadow-none hover:bg-transparent hover:text-[var(--fg-primary)]",
  reActToolItem:
    "vui-components-conversationview reActToolItem min-w-0 border-0 bg-transparent p-0 text-[var(--fg-secondary)] shadow-none",
  reActToolLine:
    "vui-components-conversationview reActToolLine min-w-0 grid grid-cols-[minmax(9rem,auto)_minmax(0,1fr)_auto_auto] items-start gap-1.5 border-0 border-b border-[color-mix(in_srgb,var(--accent-warm)_18%,var(--vui-border-subtle))] bg-transparent py-1.5 text-[var(--fg-secondary)] shadow-none",
  reActToolList:
    "vui-components-conversationview reActToolList min-w-0 grid min-h-0 content-start gap-0 overflow-visible border-0 bg-transparent text-[var(--fg-secondary)]",
  reActToolName:
    "vui-components-conversationview reActToolName min-w-0 truncate text-[var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]",
  reActToolStatus:
    "vui-components-conversationview reActToolStatus min-w-0 inline-flex items-center gap-1 border-0 bg-transparent text-[var(--fg-tertiary)]",
  reActToolSummary:
    "vui-components-conversationview reActToolSummary min-w-0 border-0 bg-transparent p-0 text-[var(--fg-secondary)] shadow-none line-clamp-1 whitespace-normal [overflow-wrap:anywhere]",
  researchOrgChip:
    "vui-components-conversationview researchOrgChip min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  researchOrgChipRow:
    "vui-components-conversationview researchOrgChipRow min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  researchOrgChip_active:
    "vui-components-conversationview researchOrgChip_active min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  researchOrgChip_answer:
    "vui-components-conversationview researchOrgChip_answer min-w-0",
  researchOrgChip_blocked:
    "vui-components-conversationview researchOrgChip_blocked min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  researchOrgChip_code:
    "vui-components-conversationview researchOrgChip_code min-w-0 font-mono text-[var(--vui-font-xs)]",
  researchOrgChip_commit:
    "vui-components-conversationview researchOrgChip_commit min-w-0",
  researchOrgChip_danger:
    "vui-components-conversationview researchOrgChip_danger min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  researchOrgChip_done:
    "vui-components-conversationview researchOrgChip_done min-w-0",
  researchOrgChip_error:
    "vui-components-conversationview researchOrgChip_error min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  researchOrgChip_failed:
    "vui-components-conversationview researchOrgChip_failed min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  researchOrgChip_files:
    "vui-components-conversationview researchOrgChip_files min-w-0",
  researchOrgChip_idle:
    "vui-components-conversationview researchOrgChip_idle min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-tertiary)]",
  researchOrgChip_info:
    "vui-components-conversationview researchOrgChip_info min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  researchOrgChip_intent:
    "vui-components-conversationview researchOrgChip_intent min-w-0",
  researchOrgChip_logs:
    "vui-components-conversationview researchOrgChip_logs min-w-0",
  researchOrgChip_mental:
    "vui-components-conversationview researchOrgChip_mental min-w-0",
  researchOrgChip_meta:
    "vui-components-conversationview researchOrgChip_meta min-w-0 flex flex-wrap items-center gap-1.5",
  researchOrgChip_missing:
    "vui-components-conversationview researchOrgChip_missing min-w-0",
  researchOrgChip_muted:
    "vui-components-conversationview researchOrgChip_muted min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  researchOrgChip_neutral:
    "vui-components-conversationview researchOrgChip_neutral min-w-0",
  researchOrgChip_ok:
    "vui-components-conversationview researchOrgChip_ok min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  researchOrgChip_pending:
    "vui-components-conversationview researchOrgChip_pending min-w-0",
  researchOrgChip_ready:
    "vui-components-conversationview researchOrgChip_ready min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  researchOrgChip_running:
    "vui-components-conversationview researchOrgChip_running min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  researchOrgChip_status:
    "vui-components-conversationview researchOrgChip_status min-w-0",
  researchOrgChip_success:
    "vui-components-conversationview researchOrgChip_success min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  researchOrgChip_thought:
    "vui-components-conversationview researchOrgChip_thought min-w-0",
  researchOrgChip_tool:
    "vui-components-conversationview researchOrgChip_tool min-w-0 border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  researchOrgChip_verification:
    "vui-components-conversationview researchOrgChip_verification min-w-0",
  researchOrgChip_wake:
    "vui-components-conversationview researchOrgChip_wake min-w-0",
  researchOrgChip_warn:
    "vui-components-conversationview researchOrgChip_warn min-w-0",
  researchOrgChip_warning:
    "vui-components-conversationview researchOrgChip_warning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  responseBlock:
    "vui-components-conversationview responseBlock min-w-0",
  responseBody: assistantResponseBody,
  responseLabel:
    "vui-components-conversationview responseLabel min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] text-[var(--vui-font-md)]",
  responseSection: assistantResponseSection,
  responseSegment:
    "vui-components-conversationview responseSegment min-w-0",
  responseSegmentHeader:
    "vui-components-conversationview responseSegmentHeader min-w-0 flex flex-wrap items-center gap-1.5",
  responseSegmentLabel:
    "vui-components-conversationview responseSegmentLabel min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  responseSegmentList:
    "vui-components-conversationview responseSegmentList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  responseSegmentMeta:
    "vui-components-conversationview responseSegmentMeta min-w-0 flex flex-wrap items-center gap-1.5",
  responseSegmentPre:
    "vui-components-conversationview responseSegmentPre min-w-0 max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere]",
  responseSegment_active:
    "vui-components-conversationview responseSegment_active min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  responseSegment_answer:
    "vui-components-conversationview responseSegment_answer min-w-0 [&_.markdownBody]:max-w-[min(100%,128ch)] [&_.responseSegmentHeader]:hidden",
  responseSegment_blocked:
    "vui-components-conversationview responseSegment_blocked min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  responseSegment_code:
    "vui-components-conversationview responseSegment_code min-w-0 font-mono text-[var(--vui-font-xs)]",
  responseSegment_commit:
    "vui-components-conversationview responseSegment_commit min-w-0",
  responseSegment_danger:
    "vui-components-conversationview responseSegment_danger min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  responseSegment_done:
    "vui-components-conversationview responseSegment_done min-w-0",
  responseSegment_error:
    "vui-components-conversationview responseSegment_error min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  responseSegment_failed:
    "vui-components-conversationview responseSegment_failed min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  responseSegment_files:
    "vui-components-conversationview responseSegment_files min-w-0",
  responseSegment_idle:
    "vui-components-conversationview responseSegment_idle min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-tertiary)]",
  responseSegment_info:
    "vui-components-conversationview responseSegment_info min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  responseSegment_intent:
    "vui-components-conversationview responseSegment_intent min-w-0",
  responseSegment_logs:
    "vui-components-conversationview responseSegment_logs min-w-0",
  responseSegment_mental:
    "vui-components-conversationview responseSegment_mental min-w-0",
  responseSegment_meta:
    "vui-components-conversationview responseSegment_meta min-w-0 flex flex-wrap items-center gap-1.5",
  responseSegment_missing:
    "vui-components-conversationview responseSegment_missing min-w-0",
  responseSegment_muted:
    "vui-components-conversationview responseSegment_muted min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  responseSegment_neutral:
    "vui-components-conversationview responseSegment_neutral min-w-0",
  responseSegment_ok:
    "vui-components-conversationview responseSegment_ok min-w-0 border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-row)_70%,transparent)] text-[var(--fg-secondary)]",
  responseSegment_pending:
    "vui-components-conversationview responseSegment_pending min-w-0",
  responseSegment_ready:
    "vui-components-conversationview responseSegment_ready min-w-0 border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-row)_70%,transparent)] text-[var(--fg-secondary)]",
  responseSegment_running:
    "vui-components-conversationview responseSegment_running min-w-0 border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-row)_70%,transparent)] text-[var(--fg-secondary)]",
  responseSegment_status:
    "vui-components-conversationview responseSegment_status min-w-0",
  responseSegment_success:
    "vui-components-conversationview responseSegment_success min-w-0 border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-row)_70%,transparent)] text-[var(--fg-secondary)]",
  responseSegment_thought:
    "vui-components-conversationview responseSegment_thought min-w-0",
  responseSegment_tool:
    "vui-components-conversationview responseSegment_tool min-w-0 border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  responseSegment_verification:
    "vui-components-conversationview responseSegment_verification min-w-0",
  responseSegment_wake:
    "vui-components-conversationview responseSegment_wake min-w-0",
  responseSegment_warn:
    "vui-components-conversationview responseSegment_warn min-w-0",
  responseSegment_warning:
    "vui-components-conversationview responseSegment_warning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  responseToggle:
    "vui-components-conversationview responseToggle min-w-0 !grid !w-full grid-cols-[auto_auto_minmax(0,1fr)] !items-center !justify-start gap-x-1.5 !border-0 !bg-transparent !p-0 !text-left text-[var(--fg-secondary)] !shadow-none hover:!border-transparent hover:!bg-transparent hover:!shadow-none [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents",
  rolloutTraceDot:
    "vui-components-conversationview rolloutTraceDot mt-[0.45rem] size-1.5 shrink-0 rounded-full bg-current opacity-70",
  rolloutTraceItem:
    "vui-components-conversationview rolloutTraceItem min-w-0 flex items-start gap-1.5 text-[var(--vui-font-xs)] leading-[1.35] text-[var(--fg-tertiary)]",
  rolloutTraceItem_completed:
    "vui-components-conversationview rolloutTraceItem_completed min-w-0 text-[var(--fg-tertiary)]",
  rolloutTraceItem_degraded:
    "vui-components-conversationview rolloutTraceItem_degraded min-w-0 text-[var(--state-warning)]",
  rolloutTraceItem_failed:
    "vui-components-conversationview rolloutTraceItem_failed min-w-0 text-[var(--state-error)]",
  rolloutTraceItem_pending:
    "vui-components-conversationview rolloutTraceItem_pending min-w-0 text-[var(--fg-tertiary)]",
  rolloutTraceItem_running:
    "vui-components-conversationview rolloutTraceItem_running min-w-0 text-[var(--fg-secondary)]",
  rolloutTraceList:
    "vui-components-conversationview rolloutTraceList mt-2 grid min-w-0 gap-1 border-l border-[color-mix(in_srgb,var(--fg-tertiary)_22%,transparent)] bg-transparent pl-2 shadow-none",
  rolloutTraceMeta:
    "vui-components-conversationview rolloutTraceMeta min-w-0 text-[var(--fg-tertiary)] [overflow-wrap:anywhere]",
  rolloutTraceText:
    "vui-components-conversationview rolloutTraceText min-w-0 inline-flex max-w-full flex-wrap items-baseline gap-x-1.5 gap-y-0.5",
  rolloutTraceTitle:
    "vui-components-conversationview rolloutTraceTitle min-w-0 font-medium text-current",
  sectionBlock:
    "vui-components-conversationview sectionBlock min-w-0",
  sectionPanel:
    "vui-components-conversationview sectionPanel min-w-0 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-strong)_68%,transparent)] bg-[var(--vui-surface-raised)] p-2 shadow-none",
  sectionToggle:
    "vui-components-conversationview sectionToggle min-w-0",
  sendButton: composerSendActionButton,
  composerCodex: conversationComposerCodexShell,
  composerToolbar: composerToolbarShell,
  composerToolbarCodex: composerToolbarCodexShell,
  composerToolbarStart: "vui-components-conversationview composerToolbarStart flex min-w-0 items-center gap-2",
  composerToolbarEnd: "vui-components-conversationview composerToolbarEnd ml-auto flex min-w-0 items-center justify-end gap-2",
  inputCodex: "vui-components-conversationview inputCodex min-h-[48px] max-h-[220px] w-full resize-none overflow-y-auto !border-0 !bg-transparent !p-0 text-[var(--fg-primary)] !shadow-none focus:!ring-0",
  sessionMeta:
    "vui-components-conversationview sessionMeta min-w-0 flex flex-wrap items-center gap-1.5",
  statPill:
    "vui-components-conversationview statPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  statRow:
    "vui-components-conversationview statRow min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  statusRunningDot:
    "vui-components-conversationview statusRunningDot min-w-0 inline-block h-2 w-2 rounded-full bg-current border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  slashCommandSuggestionButton:
    "vui-components-conversationview slashCommandSuggestionButton flex min-h-8 w-full min-w-0 items-center gap-2 px-2 py-1 text-left text-[var(--vui-font-xs)] text-[var(--fg-secondary)] hover:bg-[var(--vui-control-muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--accent-cool)]",
  slashCommandSuggestionCode:
    "vui-components-conversationview slashCommandSuggestionCode shrink-0 rounded-[var(--radius-control)] bg-[var(--vui-control-muted)] px-1.5 py-0.5 font-semibold text-[var(--fg-primary)]",
  slashCommandSuggestionDescription:
    "vui-components-conversationview slashCommandSuggestionDescription min-w-0 truncate",
  slashCommandSuggestionOption:
    "vui-components-conversationview slashCommandSuggestionOption min-w-0",
  slashCommandSuggestions:
    "vui-components-conversationview slashCommandSuggestions min-w-0 overflow-hidden rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] shadow-[var(--vui-shadow-hairline)]",
  statusSpinner:
    "vui-components-conversationview statusSpinner min-w-0 animate-spin",
  stopButton:
    "vui-components-conversationview stopButton min-w-0 !border-[color-mix(in_srgb,var(--state-error)_34%,transparent)] !bg-[color-mix(in_srgb,var(--state-error)_9%,var(--vui-surface-row))] !text-[var(--state-error)] hover:!border-[color-mix(in_srgb,var(--state-error)_48%,transparent)] hover:!bg-[color-mix(in_srgb,var(--state-error)_14%,var(--vui-control-muted-hover))] hover:!text-[var(--state-error)] focus-visible:!ring-[color-mix(in_srgb,var(--state-error)_36%,transparent)] active:!border-[color-mix(in_srgb,var(--state-error)_58%,transparent)] active:!bg-[color-mix(in_srgb,var(--state-error)_18%,var(--vui-surface-row))] disabled:hover:!border-[color-mix(in_srgb,var(--state-error)_34%,transparent)] disabled:hover:!bg-[color-mix(in_srgb,var(--state-error)_9%,var(--vui-surface-row))] disabled:hover:!text-[var(--state-error)]",
  streamingCodeBlock:
    "vui-components-conversationview streamingCodeBlock min-w-0 font-mono text-[var(--vui-font-xs)]",
  streamingResponseText:
    "vui-components-conversationview streamingResponseText min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] text-[var(--vui-font-chat)] leading-[var(--vui-line-readable)]",
  summaryCard:
    "vui-components-conversationview summaryCard min-w-0 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-strong)_68%,transparent)] bg-[var(--vui-surface-raised)] p-2 flex flex-col gap-1 shadow-none",
  summaryGrid:
    "vui-components-conversationview summaryGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(min(100%,9rem),1fr))]",
  summaryLabel:
    "vui-components-conversationview summaryLabel min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  summaryValue:
    "vui-components-conversationview summaryValue min-w-0 whitespace-normal break-words [overflow-wrap:anywhere] text-[var(--vui-font-sm)] font-semibold leading-snug text-[var(--fg-primary)]",
  supplemental:
    "vui-components-conversationview supplemental min-w-0",
  surface:
    "vui-components-conversationview surface relative flex h-full max-h-full min-h-0 w-full min-w-0 flex-col overflow-hidden rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-strong)_74%,transparent)] bg-[var(--vui-surface-chat)] shadow-none",
  surfaceCompact:
    "vui-components-conversationview surfaceCompact rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--vui-border-strong)_70%,transparent)] bg-[var(--vui-surface-chat)] [&_.timeline]:bg-[var(--vui-surface-chat)] [&_.timeline]:pt-[9px] [&_.timeline]:pb-[11px] [&_.composer]:gap-[7px] [&_.composer]:px-2.5 [&_.composer]:pt-1.5 [&_.composer]:pb-2",
  thoughtMetaPill:
    "vui-components-conversationview thoughtMetaPill min-w-0 flex flex-wrap items-center gap-1.5 inline-flex min-h-6 w-fit max-w-full justify-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  thoughtMetaRow:
    "vui-components-conversationview thoughtMetaRow min-w-0 flex flex-wrap items-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  thoughtSectionHeader:
    "vui-components-conversationview thoughtSectionHeader min-w-0 flex flex-wrap items-center gap-1.5",
  thoughtSectionLabel:
    "vui-components-conversationview thoughtSectionLabel min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  thoughtText:
    "vui-components-conversationview thoughtText min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  thoughtTextBlock:
    "vui-components-conversationview thoughtTextBlock min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  timeline:
    "vui-components-conversationview timeline grid min-h-0 min-w-0 flex-1 content-start gap-[10px] overflow-y-auto overflow-x-hidden bg-[var(--vui-surface-chat)] px-[clamp(1rem,3vw,3rem)] py-4 [scrollbar-gutter:stable]",
  timelineAssistantTextCell:
    "vui-components-conversationview timelineAssistantTextCell min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] max-w-[min(100%,1360px)]",
  timelineCellDetailButton:
    "vui-components-conversationview timelineCellDetailButton min-w-0 inline-grid size-6 shrink-0 self-start place-items-center rounded-[var(--radius-control)] border border-transparent bg-transparent p-0 text-[var(--fg-tertiary)] hover:border-[var(--vui-border-subtle)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55",
  timelineCellHeader:
    "vui-components-conversationview timelineCellHeader min-w-0 overflow-visible !grid !w-full grid-cols-[20px_minmax(0,1fr)_24px] !items-start !justify-start gap-x-2 gap-y-1 !border-0 !bg-transparent !p-0 !text-left !shadow-none hover:border-transparent hover:bg-transparent hover:shadow-none hover:!border-transparent hover:!bg-transparent hover:!shadow-none [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents",
  timelineCellBody:
    "vui-components-conversationview timelineCellBody min-w-0 overflow-hidden text-left",
  timelineCellCompactTitleRow:
    "vui-components-conversationview timelineCellCompactTitleRow flex-nowrap overflow-hidden [&_.timelineCellTitle]:max-w-[40%] [&_.timelineCellTitle]:shrink-0 [&_.timelineCellTitle]:truncate [&_.timelineCellTitle]:whitespace-nowrap",
  timelineCellInlineSummary:
    "vui-components-conversationview timelineCellInlineSummary min-w-0 flex-1 truncate text-[var(--vui-font-sm)] font-normal leading-[1.42] text-[var(--fg-tertiary)]",
  timelineCellSeparator:
    "vui-components-conversationview timelineCellSeparator shrink-0 text-[var(--fg-tertiary)]",
  timelineCellTitleRow:
    "vui-components-conversationview timelineCellTitleRow inline-flex min-w-0 max-w-full flex-wrap items-baseline gap-2",
  timelineCellMeta:
    "vui-components-conversationview timelineCellMeta inline-flex min-w-0 shrink-0 align-baseline whitespace-nowrap text-[var(--vui-font-xs)] leading-[var(--vui-line-tight)] text-[var(--fg-tertiary)]",
  timelineCellPreview:
    "vui-components-conversationview timelineCellPreview min-w-0 border-0 bg-transparent p-0 text-[var(--vui-font-sm)] leading-[1.42] text-[var(--fg-secondary)] shadow-none grid min-h-0 content-start gap-1.5 overflow-hidden whitespace-normal break-words [overflow-wrap:anywhere] line-clamp-2",
  timelineCellTitle:
    "vui-components-conversationview timelineCellTitle min-w-0 whitespace-normal text-[var(--vui-font-sm)] font-semibold leading-[1.35] [overflow-wrap:anywhere]",
  timelineCommandError:
    "vui-components-conversationview timelineCommandError col-start-2 mt-0.5 min-w-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] px-2 py-1.5 text-[var(--vui-font-sm)] leading-[1.45] text-[var(--state-error)] whitespace-pre-wrap [overflow-wrap:anywhere]",
  timelineCommandList:
    "vui-components-conversationview timelineCommandList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  timelineCommandRow:
    "vui-components-conversationview timelineCommandRow min-w-0 grid grid-cols-[20px_minmax(0,1fr)] items-start gap-x-2 gap-y-1 border-b border-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)] bg-transparent py-2 text-[var(--vui-font-sm)] leading-[1.42] text-[var(--fg-secondary)] last:border-b-0",
  timelineHistoryButton:
    "vui-components-conversationview timelineHistoryButton min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55",
  timelineHistoryGate:
    "vui-components-conversationview timelineHistoryGate min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  timelineThoughtHeader:
    "vui-components-conversationview timelineThoughtHeader min-w-0 overflow-visible !grid !w-full grid-cols-[20px_minmax(0,1fr)_24px] !items-start !justify-start gap-x-2 gap-y-1 !border-0 !bg-transparent !p-0 !text-left !shadow-none hover:border-transparent hover:bg-transparent hover:shadow-none hover:!border-transparent hover:!bg-transparent hover:!shadow-none [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents",
  timelineOperationCell:
    "vui-components-conversationview timelineOperationCell min-w-0 grid min-h-0 content-start gap-1.5 overflow-visible text-[var(--fg-secondary)]",
  timelineOperationCell_pending:
    "vui-components-conversationview timelineOperationCell_pending min-w-0 grid min-h-0 content-start gap-1.5 overflow-visible text-[var(--fg-secondary)]",
  timelineOperationCell_running:
    "vui-components-conversationview timelineOperationCell_running min-w-0 grid min-h-0 content-start gap-1.5 overflow-visible text-[var(--fg-secondary)]",
  timelineOperationCell_failed:
    "vui-components-conversationview timelineOperationCell_failed min-w-0 grid min-h-0 content-start gap-1.5 overflow-visible border-0 bg-transparent p-0 text-[var(--fg-secondary)] [&_.operationIcon]:text-[var(--state-error)] [&_.timelineCellTitle]:text-[var(--state-error)]",
  timelineOperationCell_success:
    "vui-components-conversationview timelineOperationCell_success min-w-0 grid min-h-0 content-start gap-1.5 overflow-visible text-[var(--fg-secondary)]",
  timelineOperationCell_warning:
    "vui-components-conversationview timelineOperationCell_warning min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto text-[var(--state-warning)]",
  timelineOperationResult:
    "vui-components-conversationview timelineOperationResult min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  timelineThoughtCell:
    "vui-components-conversationview timelineThoughtCell min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  timelineThoughtText:
    "vui-components-conversationview timelineThoughtText min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] !block max-w-[min(100%,128ch)] whitespace-pre-wrap overflow-visible text-left border-0 bg-transparent",
  title:
    "vui-components-conversationview title min-w-0 text-[var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]",
  toolPill:
    "vui-components-conversationview toolPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)] border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  toolRow:
    "vui-components-conversationview toolRow min-w-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_22%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-warm)_5%,var(--vui-surface-panel))] px-2 py-1.5 text-[var(--accent-warm)] shadow-none",
  toolsBlock:
    "vui-components-conversationview toolsBlock min-w-0",
  toolsLabel:
    "vui-components-conversationview toolsLabel min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  ts:
    "vui-components-conversationview ts min-w-0",
  turnAvatar:
    "vui-components-conversationview turnAvatar mt-0.5 grid size-8 shrink-0 place-items-center overflow-hidden rounded-full bg-[var(--vui-control-muted)] text-[var(--fg-primary)] font-semibold ring-1 ring-inset ring-[var(--vui-border-strong)]",
  turnAvatarImage:
    "vui-components-conversationview turnAvatarImage block h-full w-full rounded-[inherit] object-cover",
  turnContent:
    "vui-components-conversationview turnContent grid min-w-0 gap-[5px]",
  turnEditBadge:
    "vui-components-conversationview turnEditBadge min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  turnEditing:
    "vui-components-conversationview turnEditing min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  turnError:
    "vui-components-conversationview turnError mx-auto grid w-[min(100%,760px)] min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_28%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_5%,var(--vui-surface-row))] px-3 py-2.5 text-[var(--state-error)] shadow-none",
  turnErrorDiagnostics:
    "vui-components-conversationview turnErrorDiagnostics min-w-0 text-[var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  turnErrorDiagnosticsBody:
    "vui-components-conversationview turnErrorDiagnosticsBody mt-1.5 grid min-w-0 gap-1 border-t border-[color-mix(in_srgb,var(--state-error)_18%,transparent)] pt-1.5",
  turnErrorDiagnosticsSummary:
    "vui-components-conversationview turnErrorDiagnosticsSummary w-fit cursor-pointer select-none font-medium text-[var(--fg-tertiary)] hover:text-[var(--fg-secondary)]",
  turnErrorDetail:
    "vui-components-conversationview turnErrorDetail min-w-0 whitespace-pre-wrap break-words text-[var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-tertiary)] [overflow-wrap:anywhere]",
  turnErrorLabel:
    "vui-components-conversationview turnErrorLabel min-w-0 w-fit text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--state-error)]",
  turnErrorNotice:
    "vui-components-conversationview turnErrorNotice grid w-[min(100%,920px)] max-w-full min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-2 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_7%,var(--vui-surface-row))] px-2.5 py-2 text-[var(--state-error)] shadow-none",
  turnErrorNoticeBody:
    "vui-components-conversationview turnErrorNoticeBody grid min-w-0 gap-1.5 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  turnErrorNoticeIcon:
    "vui-components-conversationview turnErrorNoticeIcon mt-0.5 min-w-0 shrink-0 text-[var(--state-error)]",
  turnErrorNoticeMeta:
    "vui-components-conversationview turnErrorNoticeMeta flex min-w-0 flex-wrap items-center gap-1.5 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--state-error)]",
  turnErrorNoticeText:
    "vui-components-conversationview turnErrorNoticeText min-w-0 whitespace-normal break-words text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [overflow-wrap:anywhere] [&_.markdownBody]:max-w-[min(100%,128ch)] [&_.markdownBody]:whitespace-normal [&_.markdownBody]:break-words [&_.markdownBody]:[overflow-wrap:anywhere]",
  turnErrorReasonList:
    "vui-components-conversationview turnErrorReasonList grid min-w-0 gap-1 border-t border-[color-mix(in_srgb,var(--state-error)_20%,transparent)] pt-1.5 text-[var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  turnErrorReasonRow:
    "vui-components-conversationview turnErrorReasonRow grid min-w-0 grid-cols-[max-content_minmax(0,1fr)] items-start gap-x-2 gap-y-0.5 [&_dd]:m-0 [&_dd]:min-w-0 [&_dd]:whitespace-pre-wrap [&_dd]:break-words [&_dd]:[overflow-wrap:anywhere] [&_dt]:font-semibold [&_dt]:text-[var(--fg-tertiary)]",
  turnErrorText:
    "vui-components-conversationview turnErrorText grid min-w-0 gap-1 whitespace-normal break-words text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
  turnErrorTurn:
    "vui-components-conversationview turnErrorTurn min-w-0 [&_.turnContent]:gap-1",
  turnErrorType:
    "vui-components-conversationview turnErrorType min-w-0 w-fit max-w-full rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--state-error)_10%,transparent)] px-1.5 py-0.5 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--state-error)]",
  turnIconButton:
    "vui-components-conversationview turnIconButton min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 inline-grid h-[var(--vui-control-height-sm)] min-h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)] place-items-center bg-[var(--vui-control-muted)] p-0 text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] shrink-0 text-[var(--fg-tertiary)]",
  turnIconButtonActive:
    "vui-components-conversationview turnIconButtonActive min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 shrink-0 text-[var(--fg-tertiary)] border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)] border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  turnMeta:
    "vui-components-conversationview turnMeta inline-flex min-w-0 items-center justify-start gap-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  turnMetaActions:
    "vui-components-conversationview turnMetaActions inline-flex min-w-0 items-center justify-start gap-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  turnMetaIdentity:
    "vui-components-conversationview turnMetaIdentity flex min-w-0 items-center gap-2",
  turnSpeaker:
    "vui-components-conversationview turnSpeaker min-w-0 truncate text-[var(--vui-font-md)] font-semibold leading-tight text-[var(--fg-primary)]",
  turnStatusLabel:
    "vui-components-conversationview turnStatusLabel min-w-0 shrink-0 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-tertiary)]",
  turnStatusNote:
    "vui-components-conversationview turnStatusNote min-w-0 inline-grid w-[min(100%,920px)] grid-cols-[auto_minmax(0,1fr)] items-start gap-2 border-l border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] bg-transparent py-1 pl-2.5 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  turnStatusText:
    "vui-components-conversationview turnStatusText min-w-0 max-w-[min(100%,128ch)] whitespace-normal [overflow-wrap:anywhere]",
  updateLine:
    "vui-components-conversationview updateLine min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2",
  userAttachment:
    "vui-components-conversationview userAttachment min-w-0",
  userAttachmentGrid:
    "vui-components-conversationview userAttachmentGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  userAttachmentImage:
    "vui-components-conversationview userAttachmentImage min-w-0",
  userAttachmentMeta:
    "vui-components-conversationview userAttachmentMeta min-w-0 flex flex-wrap items-center gap-1.5",
  userContextReferences:
    "vui-components-conversationview userContextReferences min-w-0 flex flex-wrap justify-end gap-1.5",
  userContextSection:
    "vui-components-conversationview userContextSection min-w-0 grid gap-2",
  userCard:
    "vui-components-conversationview userCard min-w-0 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-cool)_18%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_5%,var(--vui-surface-panel))] p-1.5 shadow-none",
  userMessageBody: userMessageBubble,
  userTurn:
    `vui-components-conversationview userTurn grid min-w-0 ${transcriptTurnRail} grid-cols-[minmax(0,1fr)_34px] gap-x-2.5 [&_.turnAvatar]:col-start-2 [&_.turnAvatar]:row-start-1 [&_.turnContent]:col-start-1 [&_.turnContent]:row-start-1 [&_.turnContent]:w-fit [&_.turnContent]:max-w-[min(70%,720px)] [&_.turnContent]:justify-self-end [&_.turnMeta]:justify-self-end [&_.turnMeta]:justify-end [&_.turnMeta]:text-right [&_.turnMetaActions]:justify-end [&_.turnMetaIdentity]:justify-end [&_.turnSpeaker]:hidden max-[719px]:[&_.turnContent]:max-w-[min(88%,36rem)]`,
};

export default styles;
