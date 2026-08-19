import { useState } from "react";

import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { VButton } from "../../../components/vui";
import { researchWorkflowErrorInlineText } from "../researchWorkflowErrorModel";
import styles from "./NodeCommandSection.styles";

function offerReason(offer: CommandOffer, isZh: boolean): string {
  if (offer.available) return "";
  const code = offer.reasonCode || offer.blockerIds[0] || "command_unavailable";
  if (code === "retry_owns_recovery") return isZh ? "当前节点已阻塞，请使用重试" : "Node is blocked; use retry";
  if (code === "node_in_flight") return isZh ? "当前节点已在执行" : "Node is already running";
  if (code === "node_already_succeeded") return isZh ? "当前节点已完成" : "Node already completed";
  return code;
}

export function NodeCommandSection(props: {
  offers: CommandOffer[];
  busy: boolean;
  onOffer: (offer: CommandOffer) => Promise<void>;
  lang?: "zh" | "en";
}) {
  const [actionError, setActionError] = useState<string | null>(null);
  const isZh = props.lang !== "en";
  if (!props.offers.length) return null;
  return (
    <section data-vui="node-commands">
      <h4 className={styles.title}>{isZh ? "操作" : "Actions"}</h4>
      <div className={styles.actions}>
        {props.offers.map((offer) => {
          const reason = offerReason(offer, isZh);
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
                setActionError(null);
                void props.onOffer(offer).catch((error: unknown) => {
                  setActionError(error instanceof Error ? error.message : String(error));
                });
              }}
            >
              {offer.label}
            </VButton>
          );
        })}
      </div>
      {actionError ? (
        <p className={styles.error} role="alert">
          {researchWorkflowErrorInlineText(actionError)}
        </p>
      ) : null}
    </section>
  );
}
