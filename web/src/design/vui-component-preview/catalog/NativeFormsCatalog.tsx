import { useState } from "react";

import {
  VNativeInput,
  VNativeSelect,
  VNativeTextarea,
  VStringSelect,
} from "../../../components/vui";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";

export function NativeFormsCatalog() {
  const [stage, setStage] = useState("collect");

  return (
    <VuiPreviewSection title="Native Forms">
      <VuiPreviewCard name="VNativeInput">
        <VNativeInput aria-label="项目名称" defaultValue="园区能耗" className="max-w-64" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VNativeSelect">
        <VNativeSelect aria-label="阶段" defaultValue="collect" className="max-w-64">
          <option value="collect">知识采集</option>
          <option value="design">实验设计</option>
        </VNativeSelect>
      </VuiPreviewCard>
      <VuiPreviewCard name="VNativeTextarea">
        <VNativeTextarea aria-label="备注" defaultValue="异常召回率提高至少 8%。" minRows={2} className="max-w-72" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VStringSelect">
        <VStringSelect
          ariaLabel="阶段"
          className="max-w-64"
          value={stage}
          onValueChange={setStage}
          options={[{ value: "collect", label: "知识采集" }, { value: "design", label: "实验设计" }]}
        />
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
