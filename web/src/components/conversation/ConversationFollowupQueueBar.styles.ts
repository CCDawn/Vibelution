const styles = {
  // ZCode-style two-part tooltip content: strong title line + muted description.
  tooltipContent: "block",
  tooltipTitle: "block text-vui-xs font-semibold text-vui-fg-primary",
  tooltipDescription: "block text-vui-xs text-vui-fg-secondary",
  // Explicit drag handle (a VButton) on reorderable rows: always visible so the
  // draggable affordance is discoverable, and the row itself never drags.
  followupQueueDragHandle:
    "vui-components-conversationview followupQueueDragHandle shrink-0 cursor-grab !grid !h-3.5 !w-3.5 !min-h-0 !min-w-0 place-items-center !rounded-[4px] !border-0 !bg-transparent !p-0 !shadow-none !text-[var(--fg-tertiary)] transition-colors duration-150 hover:!bg-[var(--vui-row-hover-bg)] hover:!text-[var(--fg-secondary)] active:cursor-grabbing focus-visible:!ring-2 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_var(--vui-alpha-line),transparent)]",
  // Drag source dims while carried; the hovered drop target shows an insertion
  // line on the edge the item will land against (above when moving up, below
  // when moving down).
  followupQueueRowDragSource:
    "vui-components-conversationview followupQueueRowDragSource opacity-45",
  followupQueueRowDropBefore:
    "vui-components-conversationview followupQueueRowDropBefore bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] shadow-[inset_0_2px_0_0_var(--accent-cool)]",
  followupQueueRowDropAfter:
    "vui-components-conversationview followupQueueRowDropAfter bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] shadow-[inset_0_-2px_0_0_var(--accent-cool)]",
  // While a drag is active, freeze hover feedback on every row so rows under
  // the pointer do not flash hover actions mid-reorder.
  followupQueueRowDragLock:
    "vui-components-conversationview followupQueueRowDragLock hover:!bg-transparent",
  followupQueueRowActionsDragLock:
    "vui-components-conversationview followupQueueRowActionsDragLock group-hover:!opacity-0",
  // Send-now pin: the promoted row is leaving next; tint the chip with the
  // same cool accent the queue already reserves for insertion/priority cues.
  followupQueueChipSendNow:
    "vui-components-conversationview followupQueueChipSendNow inline-flex shrink-0 items-center gap-0.5 rounded-[5px] border border-[color-mix(in_srgb,var(--accent-cool)_45%,transparent)] px-1 text-vui-2xs font-semibold leading-tight text-[var(--accent-cool)]",
} as const;

export default styles;
