import { Archive, ShieldCheck, Trash2 } from "lucide-react";

import { VButton } from "../components/vui";
import styles from "./AgentsRoute.styles";

export type AgentArchiveZonePanelCopy = {
  archiveAgent: string;
  archiveAgentTitle: string;
  archiveAgentHint: string;
  archivingAgent: string;
  purgeAgent: string;
  purgeAgentTitle: string;
  purgeAgentHint: string;
  purgingAgent: string;
  archiveProtection: string;
  archiveProtectionTitle: string;
  archiveProtectionHint: string;
  protectedAgent: string;
};

type AgentArchiveZonePanelProps = {
  copy: AgentArchiveZonePanelCopy;
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
  status,
  isProtected,
  canArchive,
  canPurge,
  isArchivePending,
  isPurgePending,
  onArchive,
  onPurge,
}: AgentArchiveZonePanelProps) {
  const isArchived = status === "archived";
  const title = isProtected ? copy.archiveProtectionHint : isArchived ? copy.purgeAgentHint : copy.archiveAgentHint;
  const eyebrow = isProtected ? copy.archiveProtectionTitle : isArchived ? copy.purgeAgentTitle : copy.archiveAgentTitle;
  const heading = isProtected ? copy.archiveProtection : isArchived ? copy.purgeAgent : copy.archiveAgent;

  return (
    <section className={isProtected ? styles.protectedZone : styles.dangerZone} title={title}>
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
              onPress={onArchive}
            >
              {isArchivePending ? copy.archivingAgent : copy.archiveAgent}
            </VButton>
          ) : null}
          <VButton
            type="button"
            variant="danger"
            icon={<Trash2 size={15} />}
            isDisabled={!canPurge || isPurgePending}
            onPress={onPurge}
          >
            {isPurgePending ? copy.purgingAgent : copy.purgeAgent}
          </VButton>
        </div>
      )}
    </section>
  );
}
