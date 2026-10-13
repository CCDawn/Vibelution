import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { VNativeButton, VHoverCard } from "../vui";
import { CONVERSATION_TURN_NAV_MIN_TURNS, type ConversationTurnNavEntry } from "./conversationTurnNavigation";
import styles from "./ConversationTurnNavigator.styles";

type ConversationTurnNavigatorProps = {
  entries: ConversationTurnNavEntry[];
  currentIndex: number;
  ariaLabel: string;
  onNavigate: (entry: ConversationTurnNavEntry) => void;
  /**
   * Localized hover fallback shown for running turns without final assistant
   * text yet; empty/omitted keeps the single-paragraph hover behavior.
   */
  runningAssistantPreview?: string;
};

/** ZCode-inspired left rail; the existing timeline remains the navigation authority. */
export function ConversationTurnNavigator(props: ConversationTurnNavigatorProps) {
  return props.entries.length < CONVERSATION_TURN_NAV_MIN_TURNS ? null : <TurnRail {...props} />;
}

function TurnRail({ entries, currentIndex, ariaLabel, onNavigate, runningAssistantPreview }: ConversationTurnNavigatorProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const virtualizer = useVirtualizer({
    count: entries.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 18,
    getItemKey: (index) => entries[index].turnIndex,
    overscan: 6,
    initialRect: { width: 36, height: 360 },
  });
  useEffect(() => {
    const rail = scrollRef.current;
    const reveal = () => {
      if (rail && rail.clientHeight > 0) virtualizer.scrollToIndex(Math.max(0, currentIndex), { align: "auto" });
    };
    reveal();
    // Re-reveal when a container query restores a formerly hidden rail.
    const observer = new ResizeObserver(reveal);
    if (rail) observer.observe(rail);
    return () => observer.disconnect();
  }, [currentIndex, entries.length, virtualizer]);

  return <nav className={styles.turnNavigatorRail} aria-label={ariaLabel} data-conversation-turn-navigator="1">
    <div ref={scrollRef} className={styles.turnNavigatorScroll} onPointerLeave={() => setHoverIndex(null)}>
      {/* Inline geometry is limited to react-virtual's spacer and offsets. */}
      <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((row) => {
          const entry = entries[row.index];
          const active = entry.turnIndex === currentIndex;
          const interactive = hoverIndex !== null;
          const distance = interactive ? Math.abs(row.index - hoverIndex) : Infinity;
          // ZCode mountain decay (conversationTurnNavigatorHelpers): d0 scaleX
          // 2.6/opacity 1 with the strong fg-primary mark, d1 1.7/0.86, d2
          // 1.25/0.72, else 0.58. Idle keeps only the scroll-active tone
          // (fg-primary + 0.9); running ticks never dim below 0.72.
          const emphasis = interactive
            ? distance === 0
              ? "scale-x-[2.6] opacity-100 text-[var(--fg-primary)]"
              : distance === 1
                ? "scale-x-[1.7] opacity-[0.86]"
                : distance === 2
                  ? "scale-x-[1.25] opacity-[0.72]"
                  : entry.isRunning ? "opacity-[0.72]" : "opacity-[0.58]"
            : active
              ? "opacity-[0.9]"
              : entry.isRunning ? "opacity-[0.72]" : "opacity-[0.58]";
          return <div key={row.key} className="absolute left-0 top-0 h-[18px] w-full" style={{ transform: `translateY(${row.start}px)` }}>
            <TurnRailItem entry={entry} active={active} emphasis={emphasis} index={row.index} total={entries.length}
              onNavigate={onNavigate} runningAssistantPreview={runningAssistantPreview}
              onFocusChange={(focused) => setHoverIndex(focused ? row.index : null)} />
          </div>;
        })}
      </div>
    </div>
  </nav>;
}

function TurnRailItem({ entry, active, emphasis, index, total, onNavigate, onFocusChange, runningAssistantPreview }: {
  entry: ConversationTurnNavEntry; active: boolean; emphasis: string;
  index: number; total: number;
  onNavigate: ConversationTurnNavigatorProps["onNavigate"];
  onFocusChange: (focused: boolean) => void;
  runningAssistantPreview?: string;
}) {
  const [open, setOpen] = useState(false);
  const user = entry.userPreviewText.trim();
  const assistant = entry.assistantPreviewText.trim();
  // Running turns without final text fall back to the localized running copy;
  // an absent/empty string keeps the previous no-second-paragraph behavior.
  const running = entry.isRunning && !assistant ? (runningAssistantPreview ?? "").trim() : "";
  const button = <VNativeButton className={`${styles.turnNavigatorDot} ${active ? styles.turnNavigatorDotActive : ""}`}
    onClick={() => onNavigate(entry)} aria-label={entry.label} aria-current={active ? "location" : undefined}
    aria-posinset={index + 1} aria-setsize={total} data-running={entry.isRunning ? "true" : "false"}
    onPointerEnter={() => onFocusChange(true)} onFocus={() => onFocusChange(true)} onBlur={() => onFocusChange(false)}>
    <span className={`${styles.turnNavigatorDotMark} ${emphasis}`} aria-hidden="true" />
  </VNativeButton>;
  if (!user && !assistant && !running) return button;
  // Only visible items mount. Controlled mode keeps the trigger stable on
  // first focus, preventing the initial click from being lost to remounting.
  return <VHoverCard side="right" align="start" sideOffset={10} open={open} onOpenChange={setOpen}
    content={<div className={styles.turnNavigatorHoverBody}>
      {user && <p className={styles.turnNavigatorHoverUser}>{user}</p>}
      {assistant && <p className={styles.turnNavigatorHoverAssistant}>{assistant}</p>}
      {running && <p className={styles.turnNavigatorHoverAssistant}>{running}</p>}
    </div>}>{button}</VHoverCard>;
}
