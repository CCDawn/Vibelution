import { PanelRight, Play } from "lucide-react";

import type { AgentAvatarOptionsPayload } from "../api/types";
import { VButton, VNativeButton, VTooltip } from "../components/vui";
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
  inspectorLabel: string;
  inspectorOpen: boolean;
  runLabel: string;
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
  onToggleInspector: () => void;
  onRun?: () => void;
};

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
  inspectorLabel,
  inspectorOpen,
  runLabel,
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
  onToggleInspector,
  onRun,
}: AgentDetailHeaderPanelProps<TPane>) {
  // Keep roleTone in the stable component contract; identity now uses one quiet eyebrow.
  void roleTone;

  return (
    <div className={styles.detailHeaderFrame}>
      <section className={styles.detailHeader} aria-label={`${agentName} · ${title}`}>
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
            <span
              className={styles.detailHealthStatus}
              aria-label={`${healthLabel} · ${healthTitle}`}
            >
              <VTooltip content={healthTitle} width="wide">
                <span className={`${styles.issuePill} ${issueToneClass(healthTone)}`} tabIndex={0}>
                  {healthLabel}
                </span>
              </VTooltip>
            </span>
          </div>
        </div>

        <div className={styles.detailHeaderActions}>
          <VButton
            type="button"
            variant="ghost"
            icon={<PanelRight size={15} />}
            aria-pressed={inspectorOpen}
            onPress={onToggleInspector}
          >
            {inspectorLabel}
          </VButton>
          {onRun ? (
            <VButton
              type="button"
              variant="primary"
              icon={<Play size={15} />}
              onPress={onRun}
            >
              {runLabel}
            </VButton>
          ) : null}
        </div>
      </section>

      <nav className={styles.detailTabs} aria-label={title}>
        {panes.map((pane) => (
          <VNativeButton
            key={pane.id}
            type="button"
            className={activePane === pane.id ? styles.detailTabActive : styles.detailTab}
            onClick={() => onSelectPane(pane.id)}
          >
            <span>{pane.label}</span>
            {pane.count > 0 ? <strong>{pane.count}</strong> : null}
          </VNativeButton>
        ))}
      </nav>
    </div>
  );
}
