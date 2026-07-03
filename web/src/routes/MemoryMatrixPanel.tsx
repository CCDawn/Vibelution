import { VButton } from "../components/vui";
import styles from "./MemoryRoute.styles";

export type MemoryMatrixChannel = "conversation" | "research" | "self_evolution" | "supervised_evolution" | "explicit_read";

export type MemoryMatrixCardView = {
  id: string;
  channel: MemoryMatrixChannel;
  title: string;
  hint: string;
  itemCount: number;
  promptCount: number;
};

export type MemoryMatrixPanelCopy = {
  perceptionMatrix: string;
  matrixItems: string;
  matrixPrompt: string;
};

type MemoryMatrixPanelProps = {
  copy: MemoryMatrixPanelCopy;
  title: string;
  activeChannel: MemoryMatrixChannel | "";
  activeChannelLabel: string;
  generatedAt: string;
  cards: MemoryMatrixCardView[];
  onSelectChannel: (channel: MemoryMatrixChannel) => void;
};

export function MemoryMatrixPanel({
  copy,
  title,
  activeChannel,
  activeChannelLabel,
  generatedAt,
  cards,
  onSelectChannel,
}: MemoryMatrixPanelProps) {
  return (
    <section className={styles.matrixPanel} aria-label={copy.perceptionMatrix}>
      <div className={styles.matrixHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.perceptionMatrix}</p>
          <h2>{title}</h2>
        </div>
        <div className={styles.matrixHeaderMeta}>
          {activeChannelLabel ? <span className={styles.activeChannelPill}>{activeChannelLabel}</span> : null}
          {generatedAt ? <span className={styles.countPill}>{generatedAt}</span> : null}
        </div>
      </div>
      <div className={styles.matrixGrid}>
        {cards.map((card) => (
          <VButton
            key={card.id}
            type="button"
            className={
              activeChannel === card.channel
                ? `${styles.matrixCard} ${styles.matrixCardButton} ${styles.matrixCardActive}`
                : `${styles.matrixCard} ${styles.matrixCardButton}`
            }
            onClick={() => onSelectChannel(card.channel)}
            aria-pressed={activeChannel === card.channel}
          >
            <div>
              <strong>{card.title}</strong>
              <span>{card.hint}</span>
            </div>
            <dl>
              <div>
                <dt>{copy.matrixItems}</dt>
                <dd>{card.itemCount}</dd>
              </div>
              <div>
                <dt>{copy.matrixPrompt}</dt>
                <dd>{card.promptCount}</dd>
              </div>
            </dl>
          </VButton>
        ))}
      </div>
    </section>
  );
}
