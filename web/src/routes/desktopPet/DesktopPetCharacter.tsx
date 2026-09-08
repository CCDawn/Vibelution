import type { PetAnimationState, PetActivityTone } from "../../api/types/petActivity";
import styles from "./DesktopPetCharacter.styles";

type DesktopPetCharacterProps = {
  animationState: PetAnimationState;
  imageSrc: string;
  name: string;
  tone: PetActivityTone;
};

export function DesktopPetCharacter({ animationState, imageSrc, name, tone }: DesktopPetCharacterProps) {
  return (
    <span
      className={styles.root}
      data-animation-state={animationState}
      data-tone={tone}
      data-renderer="image-v1"
    >
      <span className={styles.halo} aria-hidden="true" />
      <img
        className={styles.image}
        src={imageSrc}
        alt={`${name} 桌面伙伴`}
        draggable={false}
      />
    </span>
  );
}
