import { useEffect, useRef, useState } from "react";
import type { PetAnimationState, PetActivityTone } from "../../api/types/petActivity";
import { useShellI18n } from "../../i18n/useShellI18n";
import type { DesktopPetCharacterId } from "./desktopPetCharacterModel";
import { loadLive2d } from "./loadLive2d";
import type { Live2dController, Live2dStatus } from "./live2dContract";
import { WhaleRigCharacter } from "./WhaleRigCharacter";
import styles from "./DesktopPetCharacter.styles";

type DesktopPetCharacterProps = {
  animationState: PetAnimationState;
  characterId: DesktopPetCharacterId;
  name: string;
  tone: PetActivityTone;
};

type XiaoLuoCharacterProps = Omit<DesktopPetCharacterProps, "characterId">;

function XiaoLuoCharacter({ animationState, name, tone }: XiaoLuoCharacterProps) {
  const { lang } = useShellI18n();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const controllerRef = useRef<Live2dController | null>(null);
  const latestState = useRef(animationState);
  latestState.current = animationState;
  const [status, setStatus] = useState<Live2dStatus>("loading");
  useEffect(() => {
    let active = true;
    setStatus("loading");
    void loadLive2d().then((runtime) => {
      if (!active || !canvasRef.current) return;
      controllerRef.current = runtime.createLive2dController(canvasRef.current, latestState.current, (next) => {
        if (active) setStatus(next);
      });
    }).catch(() => { if (active) setStatus("error"); });
    return () => { active = false; controllerRef.current?.dispose(); controllerRef.current = null; };
  }, []);
  useEffect(() => { controllerRef.current?.setState(animationState); }, [animationState]);
  const message = status === "error"
    ? (lang === "zh" ? "Live2D 加载失败，请重新打开桌宠" : "Live2D failed to load. Reopen the pet.")
    : (lang === "zh" ? "正在加载 Live2D…" : "Loading Live2D…");
  return (
    <span
      className={styles.root}
      data-animation-state={animationState}
      data-tone={tone}
      data-renderer="live2d"
      data-renderer-status={status}
    >
      <span className={styles.halo} aria-hidden="true" />
      <canvas ref={canvasRef} className={styles.canvas} aria-label={`${name} Live2D 桌面伙伴`} />
      {status !== "ready" ? <span className={styles.message} role="status">{message}</span> : null}
      <span className={styles.credit} title="小洛模型：火爆鸡王；洛天依：上海禾念。用户已确认取得使用许可。">小洛 · 火爆鸡王</span>
    </span>
  );
}

export function DesktopPetCharacter({
  animationState,
  characterId,
  name,
  tone,
}: DesktopPetCharacterProps) {
  if (characterId === "dafeiyu") {
    return <WhaleRigCharacter animationState={animationState} name={name} tone={tone} />;
  }
  return <XiaoLuoCharacter animationState={animationState} name={name} tone={tone} />;
}
