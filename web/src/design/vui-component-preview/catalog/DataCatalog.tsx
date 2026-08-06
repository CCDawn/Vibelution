import { VDenseTable, VLoadingValue, VMetricStrip, VSkeleton } from "../../../components/vui";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";

const rows = [{ id: "a", name: "知识包", state: "已验证" }];

export function DataCatalog() {
  return (
    <VuiPreviewSection title="Data">
      <VuiPreviewCard name="VMetricStrip" className="col-span-full min-h-0">
        <VMetricStrip ariaLabel="指标" metrics={[
          { label: "候选", value: "48" },
          { label: "已核验", value: "42", tone: "success" },
          { label: "冲突", value: "3", tone: "danger" },
        ]} />
      </VuiPreviewCard>
      <VuiPreviewCard name="VDenseTable" className="col-span-full min-h-0">
        <VDenseTable ariaLabel="资料" className="w-full" columns={[
          { id: "name", header: "名称", render: (row) => row.name },
          { id: "state", header: "状态", render: (row) => row.state },
        ]} rows={rows} getRowKey={(row) => row.id} />
      </VuiPreviewCard>
      <VuiPreviewCard name="VLoadingValue">
        <VLoadingValue label="加载中" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VSkeleton">
        <VSkeleton shape="line" className="w-44" />
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
