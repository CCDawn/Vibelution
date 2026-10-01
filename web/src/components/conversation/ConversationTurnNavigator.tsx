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
};

/** ZCode-inspired left rail; the existing timeline remains the navigation authority. */
export function ConversationTurnNavigator(props: ConversationTurnNavigatorProps) {
  return props.entries.length < CONVERSATION_TURN_NAV_MIN_TURNS ? null : <TurnRail {...props} />;
}

function TurnRail({ entries, currentIndex, ariaLabel, onNavigate }: ConversationTurnNavigatorProps) {
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
          const distance = hoverIndex === null ? Infinity : Math.abs(row.index - hoverIndex);
          const emphasis = distance === 0 ? "scale-x-[2.6] opacity-100" : distance === 1 ? "scale-x-[1.7] opacity-80" : distance === 2 ? "scale-x-[1.25] opacity-65" : active ? "opacity-100" : "opacity-40";
          return <div key={row.key} className="absolute left-0 top-0 h-[18px] w-full" style={{ transform: `translateY(${row.start}px)` }}>
            <TurnRailItem entry={entry} active={active} emphasis={emphasis} onNavigate={onNavigate}
              onFocusChange={(focused) => setHoverIndex(focused ? row.index : null)} />
          </div>;
        })}
      </div>
    </div>
  </nav>;
}

function TurnRailItem({ entry, active, emphasis, onNavigate, onFocusChange }: {
  entry: ConversationTurnNavEntry; active: boolean; emphasis: string;
  onNavigate: ConversationTurnNavigatorProps["onNavigate"];
  onFocusChange: (focused: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const user = entry.userPreviewText.trim();
  const assistant = entry.assistantPreviewText.trim();
  const button = <VNativeButton className={`${styles.turnNavigatorDot} ${active ? styles.turnNavigatorDotActive : ""}`}
    onClick={() => onNavigate(entry)} aria-label={entry.label} aria-current={active ? "true" : undefined}
    onPointerEnter={() => onFocusChange(true)} onFocus={() => onFocusChange(true)} onBlur={() => onFocusChange(false)}>
    <span className={`${styles.turnNavigatorDotMark} ${emphasis}`} aria-hidden="true" />
  </VNativeButton>;
  if (!user && !assistant) return button;
  // Only visible items mount. Controlled mode keeps the trigger stable on
  // first focus, preventing the initial click from being lost to remounting.
  return <VHoverCard side="right" align="start" sideOffset={10} open={open} onOpenChange={setOpen}
    content={<div className={styles.turnNavigatorHoverBody}>
      {user && <p className={styles.turnNavigatorHoverUser}>{user}</p>}
      {assistant && <p className={styles.turnNavigatorHoverAssistant}>{assistant}</p>}
    </div>}>{button}</VHoverCard>;
}
