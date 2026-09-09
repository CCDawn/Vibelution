import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";

import type { PetAnimationState, PetActivityTone } from "../../api/types/petActivity";
import { useShellI18n } from "../../i18n/useShellI18n";
import { whaleRigStateForPetAnimation } from "./desktopPetCharacterModel";
import type { Live2dStatus } from "./live2dContract";
import styles from "./WhaleRigCharacter.styles";

type WhaleRigCharacterProps = {
  animationState: PetAnimationState;
  name: string;
  tone: PetActivityTone;
};

type WhaleRigEvent = {
  type?: unknown;
  error?: unknown;
};

const WHALE_RIG_URL = "/desktop-pet/whale-rig/index.html?embed=1";

function targetOrigin(): string {
  return window.location.origin === "null" ? "*" : window.location.origin;
}

export function WhaleRigCharacter({ animationState, name, tone }: WhaleRigCharacterProps) {
  const { lang } = useShellI18n();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const readyRef = useRef(false);
  const latestState = useRef(animationState);
  latestState.current = animationState;
  const [status, setStatus] = useState<Live2dStatus>("loading");

  function post(message: Record<string, unknown>) {
    frameRef.current?.contentWindow?.postMessage(message, targetOrigin());
  }

  function postState(state: PetAnimationState) {
    post({ type: "dafeiyu-state", state: whaleRigStateForPetAnimation(state) });
  }

  useEffect(() => {
    function receive(event: MessageEvent<WhaleRigEvent>) {
      if (event.source !== frameRef.current?.contentWindow) {
        return;
      }
      if (event.data?.type === "dafeiyu-rig-ready") {
        readyRef.current = true;
        setStatus("ready");
        postState(latestState.current);
        post({
          type: "dafeiyu-motion-preference",
          reduced: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        });
      } else if (event.data?.type === "dafeiyu-rig-error") {
        setStatus("error");
      }
    }
    window.addEventListener("message", receive);
    return () => {
      readyRef.current = false;
      window.removeEventListener("message", receive);
    };
  }, []);

  useEffect(() => {
    if (readyRef.current) {
      postState(animationState);
    }
  }, [animationState]);

  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    function syncMotionPreference() {
      if (readyRef.current) {
        post({ type: "dafeiyu-motion-preference", reduced: motion.matches });
      }
    }
    motion.addEventListener("change", syncMotionPreference);
    return () => motion.removeEventListener("change", syncMotionPreference);
  }, []);

  function followPointer(event: ReactPointerEvent<HTMLSpanElement>) {
    if (event.buttons !== 0 || !readyRef.current) {
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    post({
      type: "dafeiyu-pointer",
      inside: true,
      x: Math.max(-1, Math.min(1, ((event.clientX - rect.left) / rect.width) * 2 - 1)),
      y: Math.max(-1, Math.min(1, ((event.clientY - rect.top) / rect.height) * 2 - 1)),
    });
  }

  function stopFollowingPointer() {
    if (readyRef.current) {
      post({ type: "dafeiyu-pointer", inside: false });
    }
  }

  const message = status === "error"
    ? (lang === "zh" ? "大肥鲸加载失败，请重新打开桌宠" : "The whale failed to load. Reopen the pet.")
    : (lang === "zh" ? "正在加载大肥鲸…" : "Loading the whale…");

  return (
    <span
      className={styles.root}
      data-animation-state={animationState}
      data-character="dafeiyu"
      data-tone={tone}
      data-renderer="anime-2-5d-rig"
      data-renderer-status={status}
      onPointerMove={followPointer}
      onPointerLeave={stopFollowingPointer}
    >
      <span className={styles.halo} aria-hidden="true" />
      <iframe
        ref={frameRef}
        className={styles.frame}
        src={WHALE_RIG_URL}
        title={`${name} 2.5D 桌面伙伴`}
        sandbox="allow-scripts allow-same-origin"
        tabIndex={-1}
      />
      {status !== "ready" ? <span className={styles.message} role="status">{message}</span> : null}
      <span className={styles.credit} title="大肥鱼分层模型与 Anime2.5DRig：Hello-Lv-tu / hakoniwa；本地授权原型。">大肥鲸 · Hello-Lv-tu</span>
    </span>
  );
}
