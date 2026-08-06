import { useState } from "react";

import {
  TeamSourceEmptyState,
  TeamSourceFilterBar,
  TeamSourcePagination,
  TeamSourceResultItem,
  TeamSourceResultList,
  TeamSourceResultStats,
  TeamStatusLabel,
} from "../../../components/vui/product/team-management";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";

export function TeamSourceCatalog() {
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(1);

  return (
    <VuiPreviewSection title="Team Source">
      <VuiPreviewCard name="TeamSourceFilterBar" className="min-h-0">
        <div className="w-full"><TeamSourceFilterBar ariaLabel="资料筛选" onSelect={setFilter} options={[{ key: "all", label: "全部", count: 48, selected: filter === "all" }, { key: "review", label: "待复核", count: 3, selected: filter === "review" }]} /></div>
      </VuiPreviewCard>
      <VuiPreviewCard name="TeamSourceResultStats" className="min-h-0">
        <div className="w-full"><TeamSourceResultStats stats={[{ key: "candidate", label: "候选", value: 48 }, { key: "verified", label: "已核验", value: 42 }, { key: "conflict", label: "冲突", value: 3 }]} /></div>
      </VuiPreviewCard>
      <VuiPreviewCard name="TeamStatusLabel" className="min-h-0">
        <TeamStatusLabel tone="ready">已提炼</TeamStatusLabel>
      </VuiPreviewCard>
      <VuiPreviewCard name="TeamSourceResultList / TeamSourceResultItem" className="col-span-full min-h-0">
        <div className="w-full"><TeamSourceResultList ariaLabel="资料"><TeamSourceResultItem tone="ready" statusLabel="已提炼" title="园区能耗公开数据集 v3" meta={[]} source={{ label: "来源", value: "data.gov.cn", title: "公开数据集" }} /></TeamSourceResultList></div>
      </VuiPreviewCard>
      <VuiPreviewCard name="TeamSourcePagination" className="min-h-0">
        <div className="w-full"><TeamSourcePagination ariaLabel="分页" rangeLabel="1–20" page={page} pageCount={3} previousLabel="上一页" nextLabel="下一页" onPrevious={() => setPage((current) => Math.max(1, current - 1))} onNext={() => setPage((current) => Math.min(3, current + 1))} /></div>
      </VuiPreviewCard>
      <VuiPreviewCard name="TeamSourceEmptyState" className="col-span-full min-h-0">
        <TeamSourceEmptyState title="暂无资料" />
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
