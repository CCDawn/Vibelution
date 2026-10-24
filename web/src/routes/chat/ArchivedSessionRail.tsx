/**
 * Flat archived-session column. Replaces the live directory while the
 * archive view is on. Opening a row uses the same session; unarchive and
 * delete stay separate actions.
 */
import { useState, type ReactNode } from "react";
import { ArchiveRestore, Trash2 } from "lucide-react";

import type { SessionSummary } from "../../api/types";
import { VButton, VConfirmDialog, VIconButton, VStateSurface } from "../../components/vui";
import type { TranslationKey } from "../../i18n/dictionary";
import {
  sortArchivedSessions,
  visibleArchivedSessions,
} from "./archivedSessionRailModel";
import { sessionBlocksMutation } from "../sessionActivityState";
import styles from "./ArchivedSessionRail.styles";
import type { SessionListSortBy } from "./sessionListPreferences";

type ArchivedSessionRailProps = {
  sessions: readonly SessionSummary[];
  totalCount: number;
  sortBy: SessionListSortBy;
  loading: boolean;
  archivePendingSessionId: string;
  archivePendingSessionIds?: ReadonlySet<string>;
  deletePendingSessionId: string;
  deleteAllPending: boolean;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  onUnarchive: (session: SessionSummary) => void;
  onDelete: (session: SessionSummary) => void;
  onDeleteAll: () => void;
  renderSessions: (
    sessions: SessionSummary[],
    renderTrailingActions: (session: SessionSummary) => ReactNode,
  ) => ReactNode;
};

export function ArchivedSessionRail({
  sessions,
  totalCount,
  sortBy,
  loading,
  archivePendingSessionId,
  archivePendingSessionIds,
  deletePendingSessionId,
  deleteAllPending,
  onUnarchive,
  onDelete,
  onDeleteAll,
  t,
  renderSessions,
}: ArchivedSessionRailProps) {
  const [expanded, setExpanded] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SessionSummary | null>(null);
  const [deleteAllOpen, setDeleteAllOpen] = useState(false);
  const sorted = sortArchivedSessions(sessions, sortBy);
  const visible = visibleArchivedSessions(sorted, expanded);
  const count = Math.max(totalCount, sorted.length);
  const hiddenCount = Math.max(0, sorted.length - visible.length);

  return (
    <section className={styles.section} data-vui="archived-session-rail" aria-label={t("archivedSessionsGroup")}>
      <div className={styles.toolbar}>
        <p className={styles.count}>
          {t("archivedSessionCount")} {count}
        </p>
        <VButton
          type="button"
          variant="danger"
          density="compact"
          isDisabled={loading || deleteAllPending || count === 0}
          onPress={() => setDeleteAllOpen(true)}
        >
          {t("deleteAllArchivedSessions")}
        </VButton>
      </div>
      {loading && sorted.length === 0 ? (
        <VStateSurface tone="loading" title={t("loadingSession")} />
      ) : sorted.length === 0 ? (
        <VStateSurface tone="empty" title={t("noArchivedSessions")} />
      ) : renderSessions(visible, (session) => {
          const busy = sessionBlocksMutation(session);
          const unarchivePending = archivePendingSessionIds?.has(session.id) ?? archivePendingSessionId === session.id;
          const deletePending = deletePendingSessionId === session.id;
          return (
            <>
              <VIconButton
                type="button"
                label={t("unarchiveSession")}
                tooltip={t("unarchiveSession")}
                isDisabled={busy || unarchivePending}
                onPress={() => onUnarchive(session)}
                icon={<ArchiveRestore size={15} aria-hidden="true" />}
              />
              <VIconButton
                type="button"
                label={busy ? t("deleteSessionBusy") : t("deleteArchivedSession")}
                tooltip={busy ? t("deleteSessionBusy") : t("deleteArchivedSession")}
                isDisabled={busy || deletePending || deleteAllPending}
                onPress={() => setDeleteTarget(session)}
                icon={<Trash2 size={15} aria-hidden="true" />}
              />
            </>
          );
        })
      }
      {hiddenCount > 0 ? (
        <VButton
          type="button"
          variant="secondary"
          density="compact"
          onPress={() => setExpanded(true)}
        >
          {t("showMoreArchivedSessions")}
        </VButton>
      ) : null}
      <VConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null);
          }
        }}
        title={t("deleteArchivedSessionConfirm")}
        description={t("deleteArchivedSessionDescription")}
        tone="danger"
        size="sm"
        confirmLabel={t("deleteArchivedSession")}
        cancelLabel={t("archiveDialogCancel")}
        confirmPending={Boolean(deleteTarget && deletePendingSessionId === deleteTarget.id)}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) {
            onDelete(deleteTarget);
          }
          setDeleteTarget(null);
        }}
      />
      <VConfirmDialog
        open={deleteAllOpen}
        onOpenChange={setDeleteAllOpen}
        title={t("deleteAllArchivedSessionsConfirm")}
        description={t("deleteAllArchivedSessionsDescription")}
        tone="danger"
        size="sm"
        confirmLabel={t("deleteAllArchivedSessions")}
        cancelLabel={t("archiveDialogCancel")}
        confirmPending={deleteAllPending}
        onCancel={() => setDeleteAllOpen(false)}
        onConfirm={() => {
          setDeleteAllOpen(false);
          onDeleteAll();
        }}
      />
    </section>
  );
}
