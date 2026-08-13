import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { VButton } from "../../../components/vui";
import styles from "./NodeCommandSection.styles";

function offerReason(offer: CommandOffer): string {
  if (offer.available) return "";
  const code = offer.reasonCode || offer.blockerIds[0] || "command_unavailable";
  if (code === "retry_owns_recovery") return "当前节点已阻塞，请使用重试";
  if (code === "node_in_flight") return "当前节点已在执行";
  if (code === "node_already_succeeded") return "当前节点已完成";
  return code;
}

export function NodeCommandSection(props: {
  offers: CommandOffer[];
  busy: boolean;
  onOffer: (offer: CommandOffer) => Promise<void>;
}) {
  if (!props.offers.length) return null;
  return (
    <section data-vui="node-commands">
      <h4 className={styles.title}>操作</h4>
      <div className={styles.actions}>
        {props.offers.map((offer) => {
          const reason = offerReason(offer);
          return (
            <VButton
              key={`${offer.command}:${offer.idempotencyKey}`}
              type="button"
              variant={
                offer.payload?.decision === "accept" || offer.command === "start_node"
                  ? "primary"
                  : "ghost"
              }
              isDisabled={props.busy || Boolean(reason)}
              disabledReason={reason || undefined}
              aria-label={reason ? `${offer.label}：${reason}` : undefined}
              onClick={() => {
                void props.onOffer(offer).catch(() => undefined);
              }}
            >
              {offer.label}
            </VButton>
          );
        })}
      </div>
    </section>
  );
}
