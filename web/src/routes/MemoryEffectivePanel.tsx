import type { ReactNode } from "react";

import styles from "./MemoryRoute.styles";

export type MemoryEffectiveCardView = {
  id: string;
  title: string;
  count: number;
  memoryList: ReactNode;
};

export type MemoryEffectivePanelCopy = {
  whereMemoryWorks: string;
};

type MemoryEffectivePanelProps = {
  copy: MemoryEffectivePanelCopy;
  matrixPanel: ReactNode;
  warningStrip: ReactNode;
  cards: MemoryEffectiveCardView[];
};

export function MemoryEffectivePanel({ copy, matrixPanel, warningStrip, cards }: MemoryEffectivePanelProps) {
  return (
    <>
      {matrixPanel}
      {warningStrip}
      <div className={styles.effectiveGrid}>
        {cards.map((card) => (
          <section key={card.id} className={styles.overviewPanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.whereMemoryWorks}</p>
                <h2>{card.title}</h2>
              </div>
              <span className={styles.countPill}>{card.count}</span>
            </div>
            {card.memoryList}
          </section>
        ))}
      </div>
    </>
  );
}
