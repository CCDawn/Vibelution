import { useState } from "react";

import { VCheckbox, VFieldRow, VInput, VSelect, VSettingsGroupCard, VSettingsRow, VSwitch, VTextarea } from "../../../components/vui";
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
      <VuiPreviewCard name="VSwitch">
        <VSwitch isSelected={checked} onChange={setChecked} aria-label="自动重试" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VTextarea">
        <VTextarea aria-label="说明" defaultValue="异常召回率提高至少 8%。" minRows={2} className="max-w-72" />
      </VuiPreviewCard>
      <VuiPreviewCard name="VFieldRow">
        <VFieldRow label="实验名称" htmlFor="preview-field">
          <VInput id="preview-field" defaultValue="园区能耗公开数据集" className="max-w-64" />
        </VFieldRow>
      </VuiPreviewCard>
      <VuiPreviewCard name="VSettingsGroupCard">
        <VSettingsGroupCard className="w-full max-w-xl">
          <VSettingsRow
            label="启用上下文压缩"
            description="上下文接近上限时自动压缩较早内容。"
            control={<VCheckbox isSelected={checked} onChange={setChecked} aria-label="启用上下文压缩" />}
          />
          <VSettingsRow
            label="压缩触发阈值"
            description="上下文超过该值触发全量压缩。"
            controlLayout="wide"
            control={<VInput aria-label="压缩触发阈值" defaultValue="16000" className="w-24" />}
          />
        </VSettingsGroupCard>
      </VuiPreviewCard>
      <VuiPreviewCard name="VSettingsRow">
        <VSettingsRow
          label="各级摘要字数"
          description="light/standard/deep/emergency 四级各自的字数上限。"
          control={<span className="max-w-40 truncate">4 个层级</span>}
          footer={<VTextarea aria-label="各级摘要字数" defaultValue={'{ "light": 500 }'} minRows={2} className="max-w-xl" />}
        />
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
