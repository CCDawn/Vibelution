import {
  VBoardWorkbenchPage,
  VButton,
  VCanvasWorkbenchPage,
  VDenseOpsPage,
  VDenseRow,
  VEmbeddedPanel,
  VListDetailPage,
  VPage,
  VSettingsFormPage,
  VSessionWorkbenchPage,
  VSplitWorkspace,
  VTrackWorkbenchPage,
  VWorkbenchPage,
} from "../../../components/vui";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";

const panelClassName = "grid min-h-16 content-center px-2 text-center text-sm font-semibold";

export function RecipeCatalog() {
  return (
    <VuiPreviewSection title="Recipes">
      <VuiPreviewCard name="VPage" className="min-h-0">
        <VPage ariaLabel="项目设置" className="w-full"><VDenseRow className="text-center font-semibold">项目设置</VDenseRow></VPage>
      </VuiPreviewCard>
      <VuiPreviewCard name="VWorkbenchPage" className="min-h-0">
        <VWorkbenchPage ariaLabel="知识包" fill={false} className="w-full"><VDenseRow className="text-center font-semibold">知识包</VDenseRow></VWorkbenchPage>
      </VuiPreviewCard>
      <VuiPreviewCard name="VDenseOpsPage" className="col-span-full min-h-0">
        <VDenseOpsPage
          ariaLabel="运行队列"
          title="运行队列"
          fill={false}
          className="w-full"
          toolbar={<VButton variant="secondary">筛选</VButton>}
        >
          <VDenseRow className="text-center font-semibold">实验协议</VDenseRow>
        </VDenseOpsPage>
      </VuiPreviewCard>
      <VuiPreviewCard name="VListDetailPage" className="col-span-full min-h-0">
        <VListDetailPage
          ariaLabel="知识包"
          title="知识包"
          fill={false}
          className="w-full"
          workspaceClassName="h-24"
          list={<VEmbeddedPanel ariaLabel="列表" className={panelClassName}>列表</VEmbeddedPanel>}
          detail={<VEmbeddedPanel ariaLabel="详情" className={panelClassName}>详情</VEmbeddedPanel>}
        />
      </VuiPreviewCard>
      <VuiPreviewCard name="VSettingsFormPage" className="col-span-full min-h-0">
        <VSettingsFormPage
          ariaLabel="项目设置"
          title="项目设置"
          className="h-44 w-full"
          bodyClassName="px-2 py-2"
          footerClassName="px-2"
          footer={<VButton variant="primary">保存</VButton>}
        >
          <VDenseRow className="text-center font-semibold">实验协议</VDenseRow>
        </VSettingsFormPage>
      </VuiPreviewCard>
      <VuiPreviewCard name="VBoardWorkbenchPage" className="col-span-full min-h-0">
        <VBoardWorkbenchPage
          ariaLabel="阶段看板"
          title="阶段看板"
          hideHeader
          className="h-44 w-full"
          rail={<VEmbeddedPanel ariaLabel="阶段" className={panelClassName}>阶段</VEmbeddedPanel>}
          board={<VEmbeddedPanel ariaLabel="知识采集" className={panelClassName}>知识采集</VEmbeddedPanel>}
        />
      </VuiPreviewCard>
      <VuiPreviewCard name="VCanvasWorkbenchPage" className="col-span-full min-h-0">
        <VCanvasWorkbenchPage
          ariaLabel="关系图"
          title="关系图"
          hideHeader
          className="h-44 w-full"
          rail={<VEmbeddedPanel ariaLabel="节点" className={panelClassName}>节点</VEmbeddedPanel>}
          canvas={<VEmbeddedPanel ariaLabel="关系图" className={panelClassName}>关系图</VEmbeddedPanel>}
          inspector={<VEmbeddedPanel ariaLabel="检查器" className={panelClassName}>检查器</VEmbeddedPanel>}
        />
      </VuiPreviewCard>
      <VuiPreviewCard name="VTrackWorkbenchPage" className="col-span-full min-h-0">
        <VTrackWorkbenchPage
          ariaLabel="研究执行"
          fill={false}
          className="w-full"
          header={{ title: "研究执行" }}
        >
          <VDenseRow className="text-center font-semibold">实验协议</VDenseRow>
        </VTrackWorkbenchPage>
      </VuiPreviewCard>
      <VuiPreviewCard name="VSessionWorkbenchPage" className="col-span-full min-h-0">
        <VSessionWorkbenchPage
          ariaLabel="研究会话"
          hostClassName="grid h-24 w-full grid-cols-[1fr_2fr_1fr] gap-2"
          indexRail={<VEmbeddedPanel ariaLabel="会话" className={panelClassName}>会话</VEmbeddedPanel>}
          session={<VEmbeddedPanel ariaLabel="研究" className={panelClassName}>研究</VEmbeddedPanel>}
          statusRail={<VEmbeddedPanel ariaLabel="状态" className={panelClassName}>状态</VEmbeddedPanel>}
        />
      </VuiPreviewCard>
      <VuiPreviewCard name="VSplitWorkspace" className="col-span-full min-h-0">
        <VSplitWorkspace
          className="h-24 w-full"
          sidebar={<VEmbeddedPanel ariaLabel="列表" className={panelClassName}>列表</VEmbeddedPanel>}
          main={<VEmbeddedPanel ariaLabel="详情" className={panelClassName}>详情</VEmbeddedPanel>}
          aside={<VEmbeddedPanel ariaLabel="检查器" className={panelClassName}>检查器</VEmbeddedPanel>}
        />
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
