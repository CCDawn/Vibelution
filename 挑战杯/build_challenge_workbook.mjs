import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const outputDir = path.join(scriptDir, "outputs");
await fs.mkdir(outputDir, { recursive: true });

const workbook = Workbook.create();

const registration = workbook.worksheets.add("报名填报信息");
registration.showGridLines = false;

registration.getRange("A1:D1").values = [["挑战杯揭榜挂帅报名信息表", "", "", ""]];
registration.mergeCells("A1:D1");
registration.getRange("A1:D1").format = {
  fill: "#1F4E79",
  font: { bold: true, color: "#FFFFFF", size: 16 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
registration.getRange("A1:D1").format.rowHeightPx = 34;

const regRows = [
  ["字段", "填写内容", "状态", "备注"],
  ["对应榜单选题序号 / 题目编号", "XH-202619", "已确定", "来自赛题 PDF"],
  ["发榜单位", "浙江阿里巴巴云计算有限公司", "已确定", "来自赛题 PDF"],
  ["参赛题目名称", "基于国产开源大模型的AI Scientist的研发与应用", "已确定", "来自赛题 PDF"],
  ["推报学院", "计算机学院", "已确定", "来自用户提供信息"],
  ["揭榜作品名称 / 作品名称", "AI Agent 驱动的动态攻防推演靶场平台", "已确定", "来自用户提供信息"],
  ["学生负责人", "许郭", "已确定", "来自用户提供信息"],
  ["学号", "232050348", "已确定", "来自用户提供信息"],
  ["学生负责人所在学院", "计算机学院", "已确定", "来自用户提供信息"],
  ["学历", "研究生在读", "已确定", "来自用户提供信息"],
  ["学生负责人联系方式", "19855532778", "已确定", "来自用户提供信息"],
  ["指导教师（按照顺序写全）", "陈信、俞东进、王东京", "已确定", "来自用户提供信息"],
  ["指导教师所在学院", "计算机学院", "已确定", "来自用户提供信息"],
  ["是否已在系统报名", "是", "已确定", "来自用户提供信息"],
  ["材料是否完成盖章", "是", "已确定", "来自用户提供信息"],
  [
    "初期研究情况",
    "已围绕“基于国产开源大模型的AI Scientist研发与应用”开展初步调研，结合团队原有AI Agent动态攻防推演靶场基础，将研究方向聚焦于网络安全领域的科学假设生成与验证。前期已对任务进行分解，划分为系统架构设计、多智能体协作机制、攻防场景构建与仿真、数据采集与评估四个方向，并组织开展国内外AI Scientist、多智能体系统、网络攻防推演及安全数据分析相关研究现状调研工作。",
    "建议填写",
    "可根据系统字数限制压缩",
  ],
  [
    "作品简介 / 项目简介",
    "本作品面向网络安全攻防推演场景，基于国产开源大模型及多智能体系统，构建具备问题理解、知识整合、关联发现与可验证假设生成能力的AI Scientist原型平台。平台通过对漏洞情报、攻防日志、靶场行为数据和安全文献进行融合分析，自动生成可验证的攻防假设、风险机制解释与实验验证方案，并在动态靶场环境中进行仿真验证，形成从数据输入到科学假设输出再到攻防实验验证的智能闭环。",
    "建议填写",
    "如系统有该字段可用",
  ],
  [
    "研究基础 / 已有成果 / 项目基础",
    "团队已具备AI Agent系统设计、网络攻防靶场构建、日志数据采集分析和大模型应用开发基础。前期围绕动态攻防推演平台完成了初步方案设计，明确了平台架构、智能体分工、攻防环境构建、数据采集与评估等核心模块，为进一步基于Qwen系列模型和阿里云百炼平台构建AI Scientist系统奠定了基础。",
    "建议填写",
    "如系统有该字段可用",
  ],
];

registration.getRangeByIndexes(2, 0, regRows.length, 4).values = regRows;
registration.getRange("A3:D3").format = {
  fill: "#D9EAF7",
  font: { bold: true, color: "#17365D" },
  horizontalAlignment: "center",
};
registration.getRange(`A3:D${regRows.length + 2}`).format.borders = {
  preset: "all",
  style: "thin",
  color: "#B7C9D6",
};
registration.getRange(`A4:A${regRows.length + 2}`).format = {
  fill: "#F3F7FA",
  font: { bold: true },
  verticalAlignment: "top",
};
registration.getRange(`B4:D${regRows.length + 2}`).format = {
  wrapText: true,
  verticalAlignment: "top",
};
registration.getRange("A:A").format.columnWidthPx = 210;
registration.getRange("B:B").format.columnWidthPx = 560;
registration.getRange("C:C").format.columnWidthPx = 90;
registration.getRange("D:D").format.columnWidthPx = 210;
registration.getRange(`A3:D${regRows.length + 2}`).format.autofitRows();
registration.freezePanes.freezeRows(3);

const topic = workbook.worksheets.add("赛题提取信息");
topic.showGridLines = false;
topic.getRange("A1:D1").values = [["赛题 XH-202619 核心信息提取", "", "", ""]];
topic.mergeCells("A1:D1");
topic.getRange("A1:D1").format = {
  fill: "#375623",
  font: { bold: true, color: "#FFFFFF", size: 16 },
  horizontalAlignment: "center",
};

const topicRows = [
  ["类别", "项目", "内容", "备注"],
  ["基本信息", "题目编号", "XH-202619", ""],
  ["基本信息", "发榜单位", "浙江阿里巴巴云计算有限公司", ""],
  ["基本信息", "题目名称", "基于国产开源大模型的AI Scientist的研发与应用", ""],
  ["核心任务", "任务闭环", "数据/文献输入 -> 问题理解 -> 知识整合 -> 关联发现 -> 可验证科学假设输出", ""],
  ["技术要求", "基座模型", "必须基于千问开源模型（Qwen）系列", ""],
  ["技术要求", "开发平台", "需通过阿里云百炼平台调用模型API并提供调用凭证/截图", ""],
  ["技术要求", "微调", "允许基于下游任务、领域数据的SFT", ""],
  ["能力项", "文献挖掘与事实提取", "结合选题结构化信息，提取关键科学事实，避免断章取义", ""],
  ["能力项", "逻辑驱动的假设生成", "利用归纳与演绎推理，基于已知事实生成初步假设", ""],
  ["能力项", "论证可行与多轮迭代", "确保引用真实可靠、假设具备可行路径，并多轮迭代完善提案", ""],
  ["能力项", "智能体思辨与人在回路", "构建可交互、具备教学意义的人机协作流程", ""],
  ["提交材料", "技术方案文档", "PDF≤20页，包含研究问题与解决方法、AI Scientist架构、真实案例、源代码等", ""],
  ["提交材料", "附加提交", "可交互前端页面、10分钟内演示视频", "可选"],
  ["评分标准", "科学价值", "40分：核心假设创新性与自洽性、方案可落地验证性", ""],
  ["评分标准", "技术深度", "30分：多智能体协作设计、多模态科学数据处理成效", ""],
  ["评分标准", "应用潜力", "30分：场景支撑、论文/专利转化潜力、代码与结果可复现性", ""],
  ["时间节点", "报名时间", "2026年5月30日-6月30日", ""],
  ["时间节点", "作品提交", "2026年9月5日前", ""],
  ["时间节点", "初审", "2026年9月20日前", ""],
  ["时间节点", "终审擂台赛", "2026年11月", ""],
  ["联系方式", "联络人", "左老师，xiaoan.zj@alibaba-inc.com，钉钉群号：162255026342", "工作日9:30-18:00"],
];

topic.getRangeByIndexes(2, 0, topicRows.length, 4).values = topicRows;
topic.getRange("A3:D3").format = {
  fill: "#E2F0D9",
  font: { bold: true, color: "#375623" },
  horizontalAlignment: "center",
};
topic.getRange(`A3:D${topicRows.length + 2}`).format.borders = {
  preset: "all",
  style: "thin",
  color: "#C7D7BD",
};
topic.getRange(`A4:B${topicRows.length + 2}`).format = {
  fill: "#F5FAF2",
  font: { bold: true },
  verticalAlignment: "top",
};
topic.getRange(`C4:D${topicRows.length + 2}`).format = {
  wrapText: true,
  verticalAlignment: "top",
};
topic.getRange("A:A").format.columnWidthPx = 120;
topic.getRange("B:B").format.columnWidthPx = 180;
topic.getRange("C:C").format.columnWidthPx = 580;
topic.getRange("D:D").format.columnWidthPx = 190;
topic.getRange(`A3:D${topicRows.length + 2}`).format.autofitRows();
topic.freezePanes.freezeRows(3);

const checklist = workbook.worksheets.add("待补清单");
checklist.showGridLines = false;
checklist.getRange("A1:D1").values = [["后续待补充/核对事项", "", "", ""]];
checklist.mergeCells("A1:D1");
checklist.getRange("A1:D1").format = {
  fill: "#7F6000",
  font: { bold: true, color: "#FFFFFF", size: 16 },
  horizontalAlignment: "center",
};
const todoRows = [
  ["事项", "当前状态", "建议动作", "截止/备注"],
  ["团队成员完整名单", "待补", "补充所有成员姓名、学号、学院、联系方式", "每队不超过10人"],
  ["阿里云百炼调用凭证/截图", "待准备", "注册/配置百炼平台并保存调用截图", "技术方案需提供"],
  ["技术方案PDF", "待撰写", "控制在20页以内", "作品提交材料"],
  ["源代码仓库/压缩包", "待整理", "整理多智能体工作流核心代码和上下文工程设计", "作品提交材料"],
  ["真实案例", "待设计", "输出满足赛题字段规范的科学假设与研究计划案例", "评分关键"],
  ["可交互前端", "可选", "如时间允许，搭建演示页面", "加分展示"],
  ["演示视频", "可选", "制作10分钟内演示视频", "推荐提交"],
  ["盖章报名表PDF", "需核对", "确保与系统填报信息严格一致", "9月5日前随作品提交"],
  ["夸克网盘链接与截图", "待提交前准备", "上传压缩包并记录分享链接、提取码、含上传时间截图", "9月5日前"],
];
checklist.getRangeByIndexes(2, 0, todoRows.length, 4).values = todoRows;
checklist.getRange("A3:D3").format = {
  fill: "#FFF2CC",
  font: { bold: true, color: "#7F6000" },
  horizontalAlignment: "center",
};
checklist.getRange(`A3:D${todoRows.length + 2}`).format.borders = {
  preset: "all",
  style: "thin",
  color: "#D6B656",
};
checklist.getRange(`A4:D${todoRows.length + 2}`).format = {
  wrapText: true,
  verticalAlignment: "top",
};
checklist.getRange("A:A").format.columnWidthPx = 210;
checklist.getRange("B:B").format.columnWidthPx = 120;
checklist.getRange("C:C").format.columnWidthPx = 430;
checklist.getRange("D:D").format.columnWidthPx = 180;
checklist.getRange(`A3:D${todoRows.length + 2}`).format.autofitRows();
checklist.freezePanes.freezeRows(3);

for (const sheet of [registration, topic, checklist]) {
  sheet.getRange("A1:D1").format.rowHeightPx = 34;
}

const preview = await workbook.render({
  sheetName: "报名填报信息",
  range: "A1:D20",
  scale: 1,
  format: "png",
});
await fs.writeFile(path.join(outputDir, "报名填报信息预览.png"), new Uint8Array(await preview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(path.join(outputDir, "挑战杯报名信息与赛题提取表.xlsx"));
