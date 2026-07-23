import { useState } from "react";
import { Archive, ShieldCheck, Trash2 } from "lucide-react";

import { VButton, VConfirmDialog, VTooltip } from "../components/vui";
import styles from "./AgentArchiveZonePanel.styles";

export type AgentArchiveZonePanelCopy = {
  archiveAgent: string;
  archiveAgentTitle: string;
  archiveAgentHint: string;
  archivingAgent: string;
  archiveConfirm: string;
  purgeAgent: string;
  purgeAgentTitle: string;
  purgeAgentHint: string;
  purgingAgent: string;
  purgeConfirm: string;
  archiveProtection: string;
  archiveProtectionTitle: string;
  archiveProtectionHint: string;
  protectedAgent: string;
  cancelCreate: string;
};

type ConfirmKind = "archive" | "purge" | null;

type AgentArchiveZonePanelProps = {
  copy: AgentArchiveZonePanelCopy;
  /** Used to interpolate {name} in confirm copy. */
  agentName: string;
  status: string;
  isProtected: boolean;
  canArchive: boolean;
  canPurge: boolean;
  isArchivePending: boolean;
  isPurgePending: boolean;
  onArchive: () => void;
  onPurge: () => void;
};

export function AgentArchiveZonePanel({
  copy,
  agentName,
  status,
  isProtected,
  canArchive,
  canPurge,
  isArchivePending,
  isPurgePending,
  onArchive,
  onPurge,
}: AgentArchiveZonePanelProps) {
  const [confirmKind, setConfirmKind] = useState<ConfirmKind>(null);
  const isArchived = status === "archived";
  const title = isProtected ? copy.archiveProtectionHint : isArchived ? copy.purgeAgentHint : copy.archiveAgentHint;
  const eyebrow = isProtected ? copy.archiveProtectionTitle : isArchived ? copy.purgeAgentTitle : copy.archiveAgentTitle;
  const heading = isProtected ? copy.archiveProtection : isArchived ? copy.purgeAgent : copy.archiveAgent;

  const confirmOpen = confirmKind !== null;
  const confirmDescription = (confirmKind === "purge" ? copy.purgeConfirm : copy.archiveConfirm).replace(
    "{name}",
    agentName,
  );

  return (
    <>
      <VTooltip content={title} width="wide">
        <section
          className={isProtected ? styles.protectedZone : styles.dangerZone}
          tabIndex={0}
          aria-label={`${heading} · ${title}`}
        >
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{eyebrow}</p>
              <h3>{heading}</h3>
            </div>
            {isProtected ? <ShieldCheck size={16} /> : <Trash2 size={16} />}
          </div>
          {isProtected ? (
            <span className={styles.cleanPill}>{copy.protectedAgent}</span>
          ) : (
            <div className={styles.editorActions}>
              {!isArchived ? (
                <VButton
                  type="button"
                  variant="secondary"
                  icon={<Archive size={15} />}
                  isDisabled={!canArchive || isArchivePending}
                  onPress={() => setConfirmKind("archive")}
                >
                  {isArchivePending ? copy.archivingAgent : copy.archiveAgent}
                </VButton>
              ) : null}
              <VButton
                type="button"
                variant="danger"
                icon={<Trash2 size={15} />}
                isDisabled={!canPurge || isPurgePending}
                onPress={() => setConfirmKind("purge")}
              >
                {isPurgePending ? copy.purgingAgent : copy.purgeAgent}
              </VButton>
            </div>
          )}
        </section>
      </VTooltip>

      <VConfirmDialog
        open={confirmOpen}
        onOpenChange={(open) => {
          if (!open) {
            setConfirmKind(null);
          }
        }}
        title={confirmKind === "purge" ? copy.purgeAgent : copy.archiveAgent}
        description={confirmDescription}
        tone={confirmKind === "purge" ? "danger" : "neutral"}
        confirmLabel={confirmKind === "purge" ? copy.purgeAgent : copy.archiveAgent}
        cancelLabel={copy.cancelCreate}
        confirmPending={confirmKind === "purge" ? isPurgePending : isArchivePending}
        onConfirm={() => {
          if (confirmKind === "purge") {
            onPurge();
          } else if (confirmKind === "archive") {
            onArchive();
          }
          setConfirmKind(null);
        }}
      />
    </>
  );
}
