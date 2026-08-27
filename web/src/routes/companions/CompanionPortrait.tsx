import type { VirtualHumanCompanion } from "../../api/types";
import { companionInitials } from "./companionPresentation";
import styles from "./companions.styles";

export function CompanionPortrait({
  companion,
  className = "",
  compact = false,
}: {
  companion: VirtualHumanCompanion;
  className?: string;
  compact?: boolean;
}) {
  const portraitClassName = [
    compact ? styles.avatar : styles.portrait,
    className,
  ].filter(Boolean).join(" ");
  return (
    <span
      className={portraitClassName}
      role="img"
      aria-label={`${companion.displayName} · ${companionInitials(companion)}`}
      data-companion-portrait={compact ? "avatar" : "portrait"}
    >
      {companion.avatarImageUrl ? (
        <img src={companion.avatarImageUrl} alt="" className={styles.portraitImage} />
      ) : (
        <span className={styles.portraitInitials}>{companionInitials(companion)}</span>
      )}
      <span className={styles.portraitGlow} aria-hidden="true" />
      <span className={styles.onlineDot} aria-hidden="true" />
    </span>
  );
}
