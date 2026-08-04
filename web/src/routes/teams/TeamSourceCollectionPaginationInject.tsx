/**
 * SC inject: stage-scoped pagination for candidate/record lists.
 */
import type { MouseEvent as ReactMouseEvent } from "react";

import { TeamSourceCollectionPagination } from "../TeamSourceCollectionResultControls";
import { SOURCE_COLLECTION_RESULT_PAGE_SIZE } from "./source-collection/presentationModel";
import { resolveSourceCollectionPaginationView } from "./source-collection/injectModel";
import type { SourceCollectionStageModuleId } from "./source-collection/stageProjection";

export type TeamSourceCollectionPaginationInjectProps = {
  lang: "zh" | "en";
  stageId: SourceCollectionStageModuleId;
  total: number;
  page: number;
  pageSize?: number;
  onPageChange: (stageId: SourceCollectionStageModuleId, page: number) => void;
  onContain?: (event: ReactMouseEvent<HTMLDivElement>) => void;
};

export function TeamSourceCollectionPaginationInject({
  lang,
  stageId,
  total,
  page,
  pageSize = SOURCE_COLLECTION_RESULT_PAGE_SIZE,
  onPageChange,
  onContain,
}: TeamSourceCollectionPaginationInjectProps) {
  const view = resolveSourceCollectionPaginationView({
    total,
    page,
    pageSize,
  });
  if (!view) {
    return null;
  }
  return (
    <TeamSourceCollectionPagination
      lang={lang}
      total={view.total}
      page={view.page}
      pageSize={view.pageSize}
      onPageChange={(nextPage: number) => onPageChange(stageId, nextPage)}
      onContain={onContain}
    />
  );
}
