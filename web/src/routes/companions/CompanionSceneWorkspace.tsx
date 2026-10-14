import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, BookOpen, MapPin, Settings } from "lucide-react";

import type { ConversationMessage, VirtualHumanCompanion } from "../../api/types";
import { ConversationShareExportButton } from "../../components/conversation/ConversationShareExportButton";
import { VButton, VDialog, VRouteLinkButton, VSessionWorkbenchPage, VSurface } from "../../components/vui";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import { CompanionConversationHeader } from "./CompanionConversationHeader";
import { CompanionLifeRail } from "./CompanionLifeRail";
import { CompanionPortrait } from "./CompanionPortrait";
import { companionLocationLabel, companionReturnTarget, formatCompanionLocalTime } from "./companionPresentation";
import { selectCompanionScene } from "./companionScene";
import styles from "./CompanionSceneWorkspace.styles";

/** Companion-only presentation. Native Session remains the transcript/composer owner. */
export function CompanionSceneWorkspace({ companion, conversation, sessionId, messages, lang, onOpenLifeSteward, onReturnToConversation }: {
  companion: VirtualHumanCompanion;
  conversation: ReactNode;
  sessionId?: string;
  messages: ConversationMessage[];
  lang: "zh" | "en";
  onOpenLifeSteward: (sessionId: string) => void;
  onReturnToConversation?: () => void;
}) {
  const [lifeOpen, setLifeOpen] = useState(false);
  const conversationRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = conversationRef.current;
    if (!root) return;
    const placeholder = lang === "zh" ? "发送消息…" : "Send a message…";
    // Native empty-session examples also override composerPlaceholder when
    // suggestions are disabled. Adapt that display attribute only; the native
    // editor continues to own value, events, attachments and submission.
    const originals = new Map<HTMLTextAreaElement, string | null>();
    const apply = () => {
      originals.forEach((_original, input) => { if (!root.contains(input)) originals.delete(input); });
      root.querySelectorAll<HTMLTextAreaElement>(".composerFieldCodex textarea").forEach(input => {
        if (input.getAttribute("placeholder") === placeholder) return;
        originals.set(input, input.getAttribute("placeholder"));
        input.setAttribute("placeholder", placeholder);
      });
    };
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ["placeholder"] });
    return () => { observer.disconnect(); originals.forEach((original, input) => { if (original === null) input.removeAttribute("placeholder"); else input.setAttribute("placeholder", original); }); };
  }, [lang]);
  const [failedImages, setFailedImages] = useState<string[]>([]);
  const scene = selectCompanionScene(companion.snapshot);
  const authorizedBackground = companion.snapshot.causal?.embodiment?.assetRefs?.background || "";
  const candidates = [...new Set([authorizedBackground, scene.backgroundUrl].filter((value): value is string => Boolean(value)))];
  const background = candidates.find(value => !failedImages.includes(value));
  useEffect(() => { setFailedImages([]); }, [companion.agentId, authorizedBackground, scene.backgroundUrl]);
  const place = companionLocationLabel(companion.snapshot.state?.currentLocation, lang);
  const movingTo = companion.snapshot.state?.locationStatus === "moving" ? companion.snapshot.state.movingTo : "";
  return (
    <VSessionWorkbenchPage
      fill hostAsRoot domainRecipe="companion-scene-workspace"
      className={styles.workspace}
      data-companion-scene={scene.key}
      data-theme="dark"
      ariaLabel={lang === "zh" ? `${companion.displayName} 的空间` : `${companion.displayName}'s space`}
      overlay={<>
        {background ? <img className={styles.background} src={background} alt="" aria-hidden="true" onError={() => setFailedImages(current => [...new Set([...current, background])])} /> : null}
        <CompanionPortrait companion={companion} className={styles.portrait} />
        <header className={styles.header}>
          <VRouteLinkButton to="/companions" variant="ghost" aria-label={lang === "zh" ? "返回人物大厅" : "Back to companion lobby"} icon={<ArrowLeft size={18} aria-hidden="true" />} />
          <CompanionConversationHeader companion={companion} lang={lang} />
          <div className={styles.location}><MapPin size={15} aria-hidden="true" /><span>{place}{movingTo ? ` → ${companionLocationLabel(movingTo, lang)}` : ""}</span><time>{formatCompanionLocalTime(companion.snapshot, lang)}</time></div>
          {onReturnToConversation ? <VButton variant="ghost" onPress={onReturnToConversation}>{lang === "zh" ? "返回对话" : "Back to chat"}</VButton> : null}
          <VButton variant="ghost" icon={<BookOpen size={17} aria-hidden="true" />} aria-haspopup="dialog" aria-expanded={lifeOpen} onPress={() => setLifeOpen(true)}>{lang === "zh" ? "生活" : "Life"}</VButton>
          <VRouteLinkButton to={agentCenterConfigRoute({ agentId: companion.agentId, pane: "config", returnTo: companionReturnTarget(companion), returnLabel: companion.displayName })} variant="ghost" aria-label={lang === "zh" ? "人物设置" : "Person settings"} icon={<Settings size={17} aria-hidden="true" />} />
          {sessionId ? <ConversationShareExportButton sessionId={sessionId} messages={messages} language={lang} presentation="menu" isDisabled={messages.length === 0} /> : null}
        </header>
      </>}
      session={<VSurface className={styles.conversation} tone="glass" padding="none" ariaLabel={lang === "zh" ? "人物对话" : "Companion conversation"}><div ref={conversationRef} className={styles.nativeHost}>{conversation}</div></VSurface>}
    >
      <VDialog open={lifeOpen} onOpenChange={setLifeOpen} title={lang === "zh" ? "生活" : "Life"} description={place} className={styles.lifeDialog}>
        <CompanionLifeRail className={styles.lifeContent} collapsed={false} overlayOpen={false} companion={companion} state="ready" lang={lang} onOpenLifeSteward={(id) => { setLifeOpen(false); onOpenLifeSteward(id); }} />
      </VDialog>
    </VSessionWorkbenchPage>
  );
}
