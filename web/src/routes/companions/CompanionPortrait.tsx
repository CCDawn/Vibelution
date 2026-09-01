import { useEffect, useMemo, useState, type CSSProperties } from "react";

import type { VirtualHumanCompanion } from "../../api/types";
// Chat and the lobby share this portrait; importing the route entry here keeps
// companion rail utilities in the native Chat CSS graph as well.
import "../../design/route-css/companions.tailwind.css";
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
  const embodiment = companion.snapshot.causal?.embodiment;
  const expressionId = embodiment?.expressionId || "neutral";
  const motionPreset = embodiment?.motionPreset || "still";
  const sceneKey = embodiment?.sceneKey || "home-day";
  const blinkMinMs = embodiment?.blinkProfile?.minIntervalMs || 2800;
  const blinkMaxMs = embodiment?.blinkProfile?.maxIntervalMs || 6200;
  const blinkDurationMs = Math.max(2800, Math.min(7600, Math.round((blinkMinMs + blinkMaxMs) / 2)));
  const expressionAssetRef = embodiment?.assetRefs?.expression || "";
  const backgroundAssetRef = compact ? "" : (embodiment?.assetRefs?.background || "");
  const imageCandidates = useMemo(
    () => [...new Set([expressionAssetRef, companion.avatarImageUrl].filter(Boolean))],
    [companion.avatarImageUrl, expressionAssetRef],
  );
  const [failedAssetRefs, setFailedAssetRefs] = useState<string[]>([]);

  useEffect(() => {
    setFailedAssetRefs([]);
  }, [backgroundAssetRef, companion.agentId, expressionAssetRef]);

  const imageUrl = imageCandidates.find((candidate) => !failedAssetRefs.includes(candidate)) || "";
  const backgroundUrl = backgroundAssetRef && !failedAssetRefs.includes(backgroundAssetRef)
    ? backgroundAssetRef
    : "";
  const portraitClassName = [
    compact ? styles.avatar : styles.portrait,
    className,
  ].filter(Boolean).join(" ");
  const imageClassName = compact ? styles.avatarImage : styles.portraitImage;
  return (
    <span
      className={portraitClassName}
      role="img"
      aria-label={`${companion.displayName} · ${companionInitials(companion)}`}
      data-companion-portrait={compact ? "avatar" : "portrait"}
      data-expression-id={expressionId}
      data-motion-preset={motionPreset}
      data-scene-key={sceneKey}
      data-companion-blink={embodiment?.blinkProfile?.enabled ? "true" : "false"}
      data-embodiment-fallback={embodiment?.fallbackReason || undefined}
      style={{ "--companion-blink-duration": `${blinkDurationMs}ms` } as CSSProperties}
    >
      {backgroundUrl ? (
        <img
          src={backgroundUrl}
          alt=""
          className={styles.portraitSceneImage}
          aria-hidden="true"
          onError={() => setFailedAssetRefs((current) => [...new Set([...current, backgroundUrl])])}
        />
      ) : null}
      {imageUrl ? (
        <span className={styles.portraitFigure} data-companion-figure="true">
          <img
            src={imageUrl}
            alt=""
            className={imageClassName}
            onError={() => setFailedAssetRefs((current) => [...new Set([...current, imageUrl])])}
          />
        </span>
      ) : (
        <span className={styles.portraitInitials}>{companionInitials(companion)}</span>
      )}
      <span className={styles.portraitGlow} aria-hidden="true" />
      <span className={styles.portraitBlink} data-companion-eyelids="true" aria-hidden="true">
        <i />
        <i />
      </span>
      <span className={styles.onlineDot} aria-hidden="true" />
    </span>
  );
}
