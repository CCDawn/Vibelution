/**
 * SC inject shell: search brief config only.
 * Flow progression is owned by the right-rail stage primary only.
 * Project reset actions live under the right-rail stage workspace (below stage card).
 * Reset success / draft hydration remain route-owned via callbacks on the reset host.
 */
import type { ReactNode } from "react";

import { TeamSourceCollectionSearchBriefInject } from "./TeamSourceCollectionSearchBriefInject";
import type { SourceCollectionDraft } from "./source-collection/presentationModel";

export type TeamSourceCollectionSearchBriefShellProps = {
  lang: "zh" | "en";
  draft: SourceCollectionDraft;
  modeFields: ReactNode;
  hasExistingRun: boolean;
  onDraftChange: (patch: Partial<SourceCollectionDraft>) => void;
};

export function TeamSourceCollectionSearchBriefShell({
  lang,
  draft,
  modeFields,
  hasExistingRun,
  onDraftChange,
}: TeamSourceCollectionSearchBriefShellProps) {
  return (
    <TeamSourceCollectionSearchBriefInject
      lang={lang}
      draft={draft}
      modeFields={modeFields}
      hasExistingRun={hasExistingRun}
      onDraftChange={onDraftChange}
    />
  );
}
