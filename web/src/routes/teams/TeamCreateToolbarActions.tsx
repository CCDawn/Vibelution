/**
 * Teams toolbar "new team" action: opens TeamCreateDialog and hands the
 * created team to the shell (which switches to it). Self-contained mount —
 * the toolbar only renders <TeamCreateToolbarActions />.
 */
import { useRef, useState } from "react";
import { Plus } from "lucide-react";

import type { Team } from "../../api/types";
import { VButton } from "../../components/vui";
import { TeamCreateDialog } from "./TeamCreateDialog";
import { useTeamCreateActions } from "./useTeamCreateActions";
import styles from "./TeamCreateToolbarActions.styles";

export type TeamCreateToolbarActionsProps = {
  lang: "zh" | "en";
  /** Called with the created team so the shell can select it. */
  onTeamCreated?: (team: Team) => void;
};

export function TeamCreateToolbarActions({ lang, onTeamCreated }: TeamCreateToolbarActionsProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const create = useTeamCreateActions({ onTeamCreated });

  const closeAndReset = () => {
    setOpen(false);
    create.reset();
  };

  const label = lang === "zh" ? "新建团队" : "New team";

  return (
    <>
      <div className={styles.actions} data-vui-region="team-create-actions">
        <VButton
          ref={triggerRef}
          type="button"
          variant="ghost"
          density="compact"
          icon={<Plus size={14} aria-hidden="true" />}
          aria-label={label}
          title={label}
          onClick={() => setOpen(true)}
        >
          {label}
        </VButton>
      </div>
      <TeamCreateDialog
        open={open}
        lang={lang}
        triggerRef={triggerRef}
        pending={create.pending}
        errorMessage={create.errorMessage}
        outcome={create.outcome}
        onSubmit={(input) => create.submit(input)}
        onGoToTeam={closeAndReset}
        onClose={closeAndReset}
      />
    </>
  );
}
