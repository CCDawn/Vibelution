import { type ComponentProps } from "react";

import { TeamSourceCollectionOverviewPanel } from "../TeamSourceCollectionOverviewPanel";

type TeamsSourceCollectionPanelProps = ComponentProps<typeof TeamSourceCollectionOverviewPanel>;

export function TeamsSourceCollectionPanel(props: TeamsSourceCollectionPanelProps) {
  return <TeamSourceCollectionOverviewPanel {...props} />;
}
