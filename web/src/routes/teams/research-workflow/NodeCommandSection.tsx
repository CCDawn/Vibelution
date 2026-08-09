import type { NodeCommandCapability } from "../../../api/types/researchWorkflow";
import { VButton } from "../../../components/vui";
import { commandLabel, disableReasonFor } from "./nodeCommandAdapter";
import styles from "./NodeCommandSection.styles";

export function NodeCommandSection(props: {
  capabilities: NodeCommandCapability[];
  busy: boolean;
  onCommand: (command: string) => void;
}) {
  const commands = props.capabilities.filter((item) => item.command !== "open_session");
  if (!commands.length) return null;
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
              onClick={() => props.onCommand(capability.command)}
            >
              {commandLabel(capability.command)}
            </VButton>
          );
        })}
      </div>
    </section>
  );
}
