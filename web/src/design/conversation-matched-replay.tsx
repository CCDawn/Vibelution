import { type ComponentProps, useCallback, useEffect, useRef, useState } from "react";
import type { ConfigBootstrap } from "../api/types";
import { ConversationView } from "../components/conversation/ConversationView";
import { VButton } from "../components/vui";
import { matchedConversationMessage, matchedScenario, matchedStage } from "./conversation-matched-scenario";
import styles from "./conversation-projection-preview.styles";

type ReplayTheme = "light" | "dark";
type MatchedReplayControl = {
  setStage: (id: string) => void;
  setTheme: (theme: ReplayTheme) => void;
  reset: (id?: string) => void;
  play: () => void;
  snapshot: () => { scenarioId: string; stageId: string; theme: ReplayTheme; startedAtMs: number; elapsedMs: number; playing: boolean };
};
declare global { interface Window { __conversationMatchedReplay?: MatchedReplayControl; } }

const localConfig: ConfigBootstrap = {
  hash: "matched-local-fixture", language: "zh", runtimeProfile: "preview", defaultMode: "chat",
  defaultRoute: "chat", intakeMode: "manual", modeAvailability: { chat: true, self_evolution: false, supervised_evolution: false },
  domainAvailability: { chat: true, evolution: false, config: false }, modelLibraryCount: 0,
  modelLabels: {}, modelImageInputSupport: {}, themeBackgroundImagePath: "", themeBackgroundImageUrl: "",
  themeBackgroundReadability: "standard",
};
// Reuse the production host seam; fake session ids must never reach product auth or curation.
const localRuntime: NonNullable<ComponentProps<typeof ConversationView>["runtimeApi"]> = {
  cacheKey: "matched-local-fixture",
  fetchConfigBootstrap: async () => localConfig,
  fetchMessageCuration: async (sessionId) => ({ sessionId, captureEnabled: false, items: [], countsByModel: [] }),
  setMessageCuration: async () => { throw new Error("The matched replay is read-only"); },
};

/** Isolated fixture playback; never connects to a product session or writes its preferences. */
export function MatchedConversationReplay() {
  const query = new URLSearchParams(location.search);
  const requested = query.get("stage") || "thinking";
  const initialStage = matchedScenario.stages.some((stage) => stage.id === requested) ? requested : "thinking";
  const [stageId, setStageId] = useState(initialStage);
  const [theme, setTheme] = useState<ReplayTheme>(query.get("theme") === "dark" ? "dark" : "light");
  const [startedAtMs, setStartedAtMs] = useState(() => Date.now() - matchedStage(initialStage).elapsedMs);
  const [generation, setGeneration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timers = useRef<number[]>([]);
  const stage = matchedStage(stageId);
  const clearTimers = useCallback(() => {
    timers.current.forEach((id) => window.clearTimeout(id));
    timers.current = [];
    setPlaying(false);
  }, []);
  useEffect(() => () => timers.current.forEach((id) => window.clearTimeout(id)), []);
  useEffect(() => {
    const previous = document.documentElement.dataset.theme;
    document.documentElement.dataset.theme = theme;
    return () => {
      if (previous === undefined) delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = previous;
    };
  }, [theme]);
  const chooseStage = useCallback((id: string) => {
    const next = matchedStage(id);
    clearTimers();
    setStartedAtMs(Date.now() - next.elapsedMs);
    setStageId(id);
  }, [clearTimers]);
  const reset = useCallback((id = "thinking") => {
    chooseStage(id);
    setGeneration((value) => value + 1);
  }, [chooseStage]);
  const play = useCallback(() => {
    clearTimers();
    setGeneration((value) => value + 1);
    setStartedAtMs(Date.now());
    setStageId("thinking");
    setPlaying(true);
    timers.current = matchedScenario.autoSequence.filter((item) => item.atMs > 0).map((item) => window.setTimeout(() => {
      setStageId(item.stageId);
      if (item.stageId === "completed") setPlaying(false);
    }, item.atMs));
  }, [clearTimers]);
  useEffect(() => {
    const controls: MatchedReplayControl = {
      setStage: chooseStage, setTheme, reset, play,
      snapshot: () => ({ scenarioId: matchedScenario.id, stageId, theme, startedAtMs,
        elapsedMs: stage.isStreaming ? Math.max(0, Date.now() - startedAtMs) : stage.elapsedMs, playing }),
    };
    window.__conversationMatchedReplay = controls;
    return () => { if (window.__conversationMatchedReplay === controls) delete window.__conversationMatchedReplay; };
  }, [chooseStage, reset, play, stageId, theme, startedAtMs, stage, playing]);
  const sessionId = `${matchedScenario.id}-${generation}`;
  const message = matchedConversationMessage(stageId, startedAtMs, sessionId);
  return <main className={styles.page} data-matched-replay="vibelution" data-stage={stageId} data-theme={theme}>
    <nav className={styles.controls} aria-label="同数据回放控制">
      {matchedScenario.stages.map((item) => <VButton key={item.id} onPress={() => chooseStage(item.id)}>{item.label}</VButton>)}
      <VButton onPress={play}>自动推进 12 秒</VButton>
      <VButton onPress={() => reset()}>重置展开选择</VButton>
      <VButton onPress={() => setTheme((value) => value === "light" ? "dark" : "light")}>{theme === "light" ? "浅色" : "深色"}</VButton>
      <span className={styles.caption}>同一 JSON 合成数据 · 生产 ConversationView · 不连接产品会话</span>
    </nav>
    <section className={styles.proof} data-testid="matched-proof" data-stage={stageId}>
      {/* Empty host scope keeps expand choices in memory and disables session-backed queries. */}
      <ConversationView key={sessionId} runtimeApi={localRuntime} sessionId="" title="同场景展示核对"
        phase={stage.isStreaming ? "responding" : "ready"}
        messages={[{ id: "matched-user", role: "user", content: matchedScenario.userText, timestamp: message.timestamp }, message]}
        assistantDisplayName="个人助理" assistantAvatarFallback="助"
        showHeader={false} showSessionOverview={false} showMentalSnapshots={false} showComposer={false}
        density="default" composerVariant="codex" processDisplayMode="trace"
        autoScrollToLatest={false} composerValue="" composerPlaceholder="" composerDisabled={false} composerPending={false}
        defaultFileContext="workspace" onComposerChange={() => undefined} onSubmit={() => undefined} onStop={() => undefined} />
    </section>
  </main>;
}
