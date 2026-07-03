import { type ComponentProps } from "react";

import { AgentModeMembershipPanel } from "./AgentModeMembershipPanel";
import { AgentReferencesPanel } from "./AgentReferencesPanel";

type AgentConfigReferencesPanePanelProps = {
  modeMembership: ComponentProps<typeof AgentModeMembershipPanel> | null;
  references: ComponentProps<typeof AgentReferencesPanel> | null;
};

export function AgentConfigReferencesPanePanel({
  modeMembership,
  references,
}: AgentConfigReferencesPanePanelProps) {
  return (
    <>
      {modeMembership ? <AgentModeMembershipPanel {...modeMembership} /> : null}
      {references ? <AgentReferencesPanel {...references} /> : null}
    </>
  );
}
