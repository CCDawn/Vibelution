import styles from "./ConversationTokenSpeedIndicator.styles";

export type ConversationTokenSpeedIndicatorProps = {
  tokensPerSecond: number | null;
  lang: "zh" | "en";
};

/** Read-only estimate. The 0–200 dial is a scale, not a load percentage. */
export function ConversationTokenSpeedIndicator({ tokensPerSecond, lang }: ConversationTokenSpeedIndicatorProps) {
  const speed = tokensPerSecond != null && Number.isFinite(tokensPerSecond) && tokensPerSecond >= 0
    ? tokensPerSecond : null;
  const value = speed == null ? "—" : `≈${speed.toFixed(1)}`;
  const label = lang === "zh" ? `当前生成速度 ${value} tok/s` : `Current generation speed ${value} tok/s`;
  return (
      <span className={styles.root} role="img" aria-label={label} data-testid="conversation-token-speed">
        <svg viewBox="0 0 28 20" width="28" height="20" aria-hidden="true" className={styles.dial}>
          <path d="M3 16a11 11 0 0 1 22 0" fill="none" stroke="currentColor" strokeWidth="2" opacity=".25" />
          <path d="M3 16h2M6.2 8.2l1.4 1.4M14 5v2M21.8 8.2l-1.4 1.4M23 16h2" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <g transform={`rotate(${Math.min(speed ?? 0, 200) / 200 * 180},14,16)`}>
            <path d="M14 16H5.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" opacity={speed == null ? ".3" : "1"} />
          </g>
          <circle cx="14" cy="16" r="1.8" fill="currentColor" />
        </svg>
        <span className={styles.value}>{value} <span className={styles.unit}>tok/s</span></span>
      </span>
  );
}
