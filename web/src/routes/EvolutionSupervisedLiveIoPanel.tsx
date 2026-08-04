import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";

import { PaneHeightResizeHandle } from "../components/layout/PaneHeightResizeHandle";
import { VSurface, VTooltip } from "../components/vui";
import styles from "./EvolutionRoute.styles";

export type EvolutionSupervisedLiveIoPanelProps = {
  eyebrow: string;
  title: string;
  titleTooltip?: string;
  statusPills: string[];
  body: ReactNode;
  height: number;
  heightMin: number;
  heightMax: number;
  heightDragging: boolean;
  heightResizeLabel: string;
  onHeightPointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onHeightKeyDown: (event: ReactKeyboardEvent<HTMLDivElement>) => void;
};

/**
 * Live workspace center column: header chrome + body (plan / approval / conversation) + height resize.
 */
export function EvolutionSupervisedLiveIoPanel({
  eyebrow,
  title,
  titleTooltip,
  statusPills,
  body,
  height,
  heightMin,
  heightMax,
  heightDragging,
  heightResizeLabel,
  onHeightPointerDown,
  onHeightKeyDown,
}: EvolutionSupervisedLiveIoPanelProps) {
  return (
    <VSurface
      as="section"
      className={`${styles.surface} ${styles.ioSurface} ${styles.dashboardIo}`}
      elevation="panel"
      padding="none"
      tone="panel"
      data-vui-region="evolution-supervised-live-io"
    >
      <div className={styles.surfaceHeaderCompact}>
        <div>
          <p className={styles.eyebrow}>{eyebrow}</p>
          {titleTooltip ? (
            <VTooltip content={titleTooltip} width="wide">
              <h2 className={`${styles.sectionTitle} ${styles.truncateText}`} tabIndex={0}>
                {title}
              </h2>
            </VTooltip>
          ) : (
            <h2 className={`${styles.sectionTitle} ${styles.truncateText}`}>{title}</h2>
          )}
        </div>
        <div className={styles.liveStatusRow}>
          {statusPills.map((pill) => (
            <span key={pill} className={styles.secondaryPill}>{pill}</span>
          ))}
        </div>
      </div>

      <div className={styles.liveIoPane}>{body}</div>

      <PaneHeightResizeHandle
        label={heightResizeLabel}
        valueNow={height}
        valueMin={heightMin}
        valueMax={heightMax}
        active={heightDragging}
        className={styles.liveIoResizeHandle}
        onPointerDown={onHeightPointerDown}
        onKeyDown={onHeightKeyDown}
      />
    </VSurface>
  );
}
