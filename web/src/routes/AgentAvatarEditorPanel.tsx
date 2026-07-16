import { useRef } from "react";

import type { AgentAvatarOptionsPayload } from "../api/types";
import { VButton, VContextualHint, VNativeButton, VNativeInput, VTooltip } from "../components/vui";
import styles from "./AgentAvatarEditorPanel.styles";

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
      <VTooltip content={copy.editAvatar}>
        <VNativeButton
          type="button"
          className={styles.detailAvatarButton}
          onClick={() => onOpenChange(!isOpen)}
          aria-expanded={isOpen}
          aria-label={copy.editAvatar}
        >
          {renderAgentAvatar(styles.detailAvatar, avatarImageUrl, avatarInitials)}
        </VNativeButton>
      </VTooltip>
      {isOpen ? (
        <section className={styles.avatarEditorPanel}>
          <div className={styles.avatarEditorHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.avatarEditorTitle}</p>
              <strong className="inline-flex items-center gap-1.5">
                {copy.editAvatar}
                <VContextualHint content={copy.avatarEditorHint} label={`${copy.avatarEditorTitle}说明`} />
              </strong>
            </div>
            <VTooltip content={lang === "zh" ? "关闭头像编辑" : "Close avatar editor"}>
              <VNativeButton type="button" className={styles.iconButton} onClick={() => onOpenChange(false)} aria-label={lang === "zh" ? "关闭" : "Close"}>
                ×
              </VNativeButton>
            </VTooltip>
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
                  <VTooltip key={option.path} content={option.filename} width="compact">
                    <VNativeButton
                      type="button"
                      className={selected ? `${styles.avatarOption} ${styles.avatarOptionSelected}` : styles.avatarOption}
                      onClick={() => onSelectAvatar(option.path)}
                      disabled={updatePending}
                      aria-label={option.filename}
                    >
                      <img src={option.url} alt="" />
                    </VNativeButton>
                  </VTooltip>
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
