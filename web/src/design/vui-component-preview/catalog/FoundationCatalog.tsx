import { ArrowRight, Plus, RefreshCw } from "lucide-react";

import {
  VButton,
  VChip,
  VIconButton,
  VMetricChip,
  VPanel,
  VStatusChip,
  VSurface,
} from "../../../components/vui";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";

export function FoundationCatalog() {
  return (
    <VuiPreviewSection title="Foundation">
      <VuiPreviewCard name="VButton">
        <VButton variant="primary" trailingIcon={<ArrowRight size={15} />}>继续</VButton>
        <VButton variant="secondary">取消</VButton>
      </VuiPreviewCard>
      <VuiPreviewCard name="VIconButton">
        <VIconButton label="刷新" icon={<RefreshCw size={16} />} />
        <VIconButton label="新建" icon={<Plus size={16} />} />
      </VuiPreviewCard>
      <VuiPreviewCard name="VChip / VStatusChip">
        <VChip tone="accent">当前</VChip>
        <VStatusChip tone="success">完成</VStatusChip>
      </VuiPreviewCard>
      <VuiPreviewCard name="VMetricChip">
        <VMetricChip label="已验证" value="48" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VSurface / VPanel">
        <VSurface tone="inset" className="w-full max-w-44 py-4 font-medium text-vui-fg-primary">Card</VSurface>
        <VPanel className="w-full max-w-44 py-4 font-medium text-vui-fg-primary">Panel</VPanel>
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
