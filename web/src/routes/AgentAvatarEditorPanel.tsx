import { useRef } from "react";

import type { AgentAvatarOptionsPayload } from "../api/types";
import { VButton, VNativeButton, VNativeInput } from "../components/vui";
import styles from "./AgentsRoute.styles";

export type AgentAvatarEditorPanelCopy = {
  editAvatar: string;
  avatarEditorHint: string;
  avatarEditorTitle: string;
  uploadAvatar: string;
  uploadingAvatar: string;
  resetDefaultAvatar: string;
  resettingAvatar: string;
  avatarLibrary: string;
  avatarLibraryLoading: string;
  avatarLibraryEmpty: string;
};

type AgentAvatarEditorPanelProps = {
  copy: AgentAvatarEditorPanelCopy;
  lang: "zh" | "en";
  isOpen: boolean;
  avatarImageUrl: string | undefined;
  avatarImagePath: string | undefined;
  avatarInitials: string;
  avatarOptions: AgentAvatarOptionsPayload | undefined;
  avatarOptionsPending: boolean;
  uploadPending: boolean;
  updatePending: boolean;
  onOpenChange: (open: boolean) => void;
  onUploadAvatar: (file: File | undefined) => void;
  onResetAvatar: () => void;
  onSelectAvatar: (avatarImagePath: string) => void;
};

function renderAgentAvatar(className: string, imageUrl: string | undefined, fallback: string) {
  return (
    <span className={className} aria-hidden="true">
      {imageUrl ? <img src={imageUrl} alt="" className={styles.agentAvatarImage} /> : fallback}
    </span>
  );
}

export function AgentAvatarEditorPanel({
  copy,
  lang,
  isOpen,
  avatarImageUrl,
  avatarImagePath,
  avatarInitials,
  avatarOptions,
  avatarOptionsPending,
  uploadPending,
  updatePending,
  onOpenChange,
  onUploadAvatar,
  onResetAvatar,
  onSelectAvatar,
}: AgentAvatarEditorPanelProps) {
  const avatarInputRef = useRef<HTMLInputElement | null>(null);

  return (
    <div className={styles.avatarEditorAnchor}>
      <VNativeButton
        type="button"
        className={styles.detailAvatarButton}
        onClick={() => onOpenChange(!isOpen)}
        aria-expanded={isOpen}
        aria-label={copy.editAvatar}
        title={copy.editAvatar}
      >
        {renderAgentAvatar(styles.detailAvatar, avatarImageUrl, avatarInitials)}
      </VNativeButton>
      {isOpen ? (
        <section className={styles.avatarEditorPanel} title={copy.avatarEditorHint}>
          <div className={styles.avatarEditorHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.avatarEditorTitle}</p>
              <strong>{copy.editAvatar}</strong>
            </div>
            <VNativeButton type="button" className={styles.iconButton} onClick={() => onOpenChange(false)} aria-label={lang === "zh" ? "关闭" : "Close"}>
              ×
            </VNativeButton>
          </div>
          <div className={styles.avatarEditorActions}>
            <VNativeInput
              ref={avatarInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              disabled={uploadPending}
              onChange={(event) => {
                onUploadAvatar(event.target.files?.[0]);
                event.currentTarget.value = "";
              }}
            />
            <VButton type="button" variant="secondary" isDisabled={uploadPending} onPress={() => avatarInputRef.current?.click()}>
              {uploadPending ? copy.uploadingAvatar : copy.uploadAvatar}
            </VButton>
            <VButton type="button" variant="secondary" isDisabled={updatePending} onPress={onResetAvatar}>
              {updatePending ? copy.resettingAvatar : copy.resetDefaultAvatar}
            </VButton>
          </div>
          <div className={styles.avatarLibraryHeader}>
            <span>{copy.avatarLibrary}</span>
            <small>{avatarOptions?.count ?? 0}</small>
          </div>
          {avatarOptionsPending ? (
            <p className={styles.contextLine}>{copy.avatarLibraryLoading}</p>
          ) : avatarOptions?.options.length ? (
            <div className={styles.avatarOptionGrid}>
              {avatarOptions.options.map((option) => {
                const selected = option.path === avatarImagePath;
                return (
                  <VNativeButton
                    key={option.path}
                    type="button"
                    className={selected ? `${styles.avatarOption} ${styles.avatarOptionSelected}` : styles.avatarOption}
                    onClick={() => onSelectAvatar(option.path)}
                    disabled={updatePending}
                    title={option.filename}
                  >
                    <img src={option.url} alt="" />
                  </VNativeButton>
                );
              })}
            </div>
          ) : (
            <p className={styles.contextLine}>{copy.avatarLibraryEmpty}</p>
          )}
        </section>
      ) : null}
    </div>
  );
}
