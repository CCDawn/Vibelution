import { useState } from "react";

import { VCheckbox, VFieldRow, VInput, VSelect, VTextarea } from "../../../components/vui";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";

export function FormsCatalog() {
  const [checked, setChecked] = useState(true);
  const [value, setValue] = useState("知识采集");

  return (
    <VuiPreviewSection title="Forms">
      <VuiPreviewCard name="VInput">
        <VInput aria-label="名称" value={value} onChange={(event) => setValue(event.target.value)} className="max-w-64" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VSelect">
        <VSelect aria-label="阶段" className="max-w-64" defaultSelectedKey="collect" options={[
          { id: "collect", label: "知识采集" },
          { id: "design", label: "实验设计" },
        ]} />
      </VuiPreviewCard>
      <VuiPreviewCard name="VCheckbox">
        <VCheckbox isSelected={checked} onChange={setChecked} aria-label="已确认" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VTextarea">
        <VTextarea aria-label="说明" defaultValue="异常召回率提高至少 8%。" minRows={2} className="max-w-72" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VFieldRow">
        <VFieldRow label="实验名称" htmlFor="preview-field">
          <VInput id="preview-field" defaultValue="园区能耗公开数据集" className="max-w-64" />
        </VFieldRow>
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
