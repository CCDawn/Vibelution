import {
  VButton,
  VDenseRow,
  VDenseToolbar,
  VEmbeddedPanel,
  VHStack,
  VRouteHeader,
  VStateRow,
  VStack,
} from "../../../components/vui";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";

export function AestheticCatalog() {
  return (
    <VuiPreviewSection title="Aesthetic">
      <VuiPreviewCard name="VRouteHeader" className="col-span-full min-h-0">
        <div className="w-full"><VRouteHeader title="项目设置" actions={<VButton variant="primary">保存</VButton>} /></div>
      </VuiPreviewCard>
      <VuiPreviewCard name="VStack">
        <VStack className="w-full max-w-48"><strong>知识包</strong><strong>实验协议</strong></VStack>
      </VuiPreviewCard>
      <VuiPreviewCard name="VHStack">
        <VHStack><strong>知识包</strong><VButton variant="secondary">查看</VButton></VHStack>
      </VuiPreviewCard>
      <VuiPreviewCard name="VDenseToolbar" className="min-h-0">
        <VDenseToolbar ariaLabel="操作"><VButton variant="secondary">筛选</VButton><VButton variant="primary">保存</VButton></VDenseToolbar>
      </VuiPreviewCard>
      <VuiPreviewCard name="VDenseRow" className="min-h-0">
        <VDenseRow className="w-full max-w-64 text-center font-semibold">知识包</VDenseRow>
      </VuiPreviewCard>
      <VuiPreviewCard name="VEmbeddedPanel" className="min-h-0">
        <VEmbeddedPanel ariaLabel="知识包" className="w-full max-w-64 py-4 text-center font-semibold">知识包</VEmbeddedPanel>
      </VuiPreviewCard>
      <VuiPreviewCard name="VStateRow" className="min-h-0">
        <VStateRow tone="warning" className="w-full max-w-64 text-center font-semibold">待复核</VStateRow>
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
