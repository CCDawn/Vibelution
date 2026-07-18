import type { AgentAvatarOptionsPayload } from "../api/types";
import { VNativeButton, VTooltip } from "../components/vui";
import {
  AgentAvatarEditorPanel,
  type AgentAvatarEditorPanelCopy,
} from "./AgentAvatarEditorPanel";
import styles from "./AgentDetailHeaderPanel.styles";

export type AgentDetailHeaderPaneView<TPane extends string = string> = {
  id: TPane;
  label: string;
  count: number;
};

type AgentDetailHeaderPanelProps<TPane extends string> = {
  copy: AgentAvatarEditorPanelCopy;
  lang: "zh" | "en";
  title: string;
  agentName: string;
  roleLabel: string;
  roleTone: string;
  healthTitle: string;
  healthTone: string;
  healthLabel: string;
  panes: AgentDetailHeaderPaneView<TPane>[];
  activePane: TPane;
  isAvatarEditorOpen: boolean;
  avatarImageUrl: string | undefined;
  avatarImagePath: string | undefined;
  avatarInitials: string;
  avatarOptions: AgentAvatarOptionsPayload | undefined;
  avatarOptionsPending: boolean;
  avatarUploadPending: boolean;
  avatarUpdatePending: boolean;
  onAvatarEditorOpenChange: (open: boolean) => void;
  onUploadAvatar: (file: File | undefined) => void;
  onResetAvatar: () => void;
  onSelectAvatar: (avatarImagePath: string) => void;
  onSelectPane: (pane: TPane) => void;
};

function roleToneClass(tone: string) {
  const toneKey = `agentRoleTag_${tone}` as keyof typeof styles;
  return styles[toneKey] || styles.agentRoleTag_general;
}

function issueToneClass(tone: string) {
  const toneKey = `issue_${tone}` as keyof typeof styles;
  return styles[toneKey] || styles.issue_info;
}

export function AgentDetailHeaderPanel<TPane extends string>({
  copy,
  lang,
  title,
  agentName,
  roleLabel,
  roleTone,
  healthTitle,
  healthTone,
  healthLabel,
  panes,
  activePane,
  isAvatarEditorOpen,
  avatarImageUrl,
  avatarImagePath,
  avatarInitials,
  avatarOptions,
  avatarOptionsPending,
  avatarUploadPending,
  avatarUpdatePending,
  onAvatarEditorOpenChange,
  onUploadAvatar,
  onResetAvatar,
  onSelectAvatar,
  onSelectPane,
}: AgentDetailHeaderPanelProps<TPane>) {
  return (
    <>
      <VTooltip content={title} width="wide">
        <section className={styles.detailHeader} tabIndex={0} aria-label={`${agentName} · ${title}`}>
          <div className={styles.detailIdentity}>
            <AgentAvatarEditorPanel
              copy={copy}
              lang={lang}
              isOpen={isAvatarEditorOpen}
              avatarImageUrl={avatarImageUrl}
              avatarImagePath={avatarImagePath}
              avatarInitials={avatarInitials}
              avatarOptions={avatarOptions}
              avatarOptionsPending={avatarOptionsPending}
              uploadPending={avatarUploadPending}
              updatePending={avatarUpdatePending}
              onOpenChange={onAvatarEditorOpenChange}
              onUploadAvatar={onUploadAvatar}
              onResetAvatar={onResetAvatar}
              onSelectAvatar={onSelectAvatar}
            />
            <div className={styles.detailIdentityCopy}>
              <p className={styles.panelEyebrow}>{roleLabel}</p>
              <h2>{agentName}</h2>
              <span className={`${styles.agentRoleTag} ${roleToneClass(roleTone)}`}>
                {roleLabel}
              </span>
            </div>
          </div>
          <div className={styles.detailHeaderActions}>
            <VTooltip content={healthTitle} width="wide">
              <span className={styles.detailHealthStatus} tabIndex={0} aria-label={`${healthLabel} · ${healthTitle}`}>
                <span className={`${styles.issuePill} ${issueToneClass(healthTone)}`}>
                  {healthLabel}
                </span>
              </span>
            </VTooltip>
          </div>
        </section>
      </VTooltip>

      <nav className={styles.detailTabs} aria-label={title}>
        {panes.map((pane) => (
          <VNativeButton
            key={pane.id}
            type="button"
            className={activePane === pane.id ? styles.detailTabActive : styles.detailTab}
            onClick={() => onSelectPane(pane.id)}
          >
            <span>{pane.label}</span>
            <strong>{pane.count}</strong>
          </VNativeButton>
        ))}
      </nav>
    </>
  );
}
