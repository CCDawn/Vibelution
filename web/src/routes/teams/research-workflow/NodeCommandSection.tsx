import { useState } from "react";

import type { NodeCommandCapability } from "../../../api/types/researchWorkflow";
import { VButton } from "../../../components/vui";
import { commandLabel, disableReasonFor } from "./nodeCommandAdapter";
import { EvidenceRemediationDialog } from "./EvidenceRemediationDialog";
import styles from "./NodeCommandSection.styles";

export function NodeCommandSection(props: {
  capabilities: NodeCommandCapability[];
  busy: boolean;
  onCommand: (command: string, payload?: Record<string, unknown>) => Promise<void>;
}) {
  const [remediationOpen, setRemediationOpen] = useState(false);
  const commands = props.capabilities.filter((item) => item.command !== "open_session");
  if (!commands.length) return null;
  const remediationCapability = commands.find(
    (item) => item.command === "fork_evidence_remediation",
  ) ?? null;
  return (
    <section data-vui="node-commands">
      <h4 className={styles.title}>操作</h4>
      <div className={styles.actions}>
        {commands.map((capability) => {
          const reason = disableReasonFor(capability);
          return (
            <VButton
              key={capability.command}
              type="button"
              variant={capability.command.startsWith("accept") ? "primary" : "ghost"}
              isDisabled={props.busy || Boolean(reason)}
              disabledReason={reason || undefined}
              aria-label={reason ? `${commandLabel(capability.command)}：${reason}` : undefined}
              onClick={() => {
                if (capability.command === "fork_evidence_remediation") {
                  setRemediationOpen(true);
                  return;
                }
                void props.onCommand(capability.command).catch(() => undefined);
              }}
            >
              {commandLabel(capability.command)}
            </VButton>
          );
        })}
      </div>
      <EvidenceRemediationDialog
        open={remediationOpen}
        capability={remediationCapability}
        busy={props.busy}
        onOpenChange={setRemediationOpen}
        onSubmit={(payload) => props.onCommand("fork_evidence_remediation", payload)}
      />
    </section>
  );
}
