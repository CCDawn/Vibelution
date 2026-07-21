import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const outputDir = path.join(scriptDir, "outputs");
const outputPath = path.join(outputDir, "挑战杯报名信息与赛题提取模板.xlsx");

const fixedTitle = "面向前沿科学问题的AI假设生成与研究计划设计平台";
const officialPage = "https://university.aliyun.com/action/tzbjbgs2026";
const nadcNotice = "https://nadc.china-vo.org/article/20260624094452";

const workbook = Workbook.create();

function styleSheet(sheet, usedRange, widths) {
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(3);
  sheet.getRange(usedRange).format = {
    font: { size: 10, color: "#243447" },
    verticalAlignment: "top",
  };
  const lastRow = Number(usedRange.match(/\d+$/)?.[0] || 1);
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, lastRow, 1).format.columnWidth = width;
  });
}

function styleTitle(sheet, range, text, fill, textColor) {
  sheet.mergeCells(range);
  const title = sheet.getRange(range);
  title.values = [[text]];
  title.format = {
    fill,
    font: { bold: true, color: textColor, size: 16 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    rowHeight: 32,
  };
}

function styleHeader(range, fill, color) {
  range.format = {
    fill,
    font: { bold: true, color },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "medium", color: "#9FB3C8" },
    rowHeight: 24,
  };
}

function styleBody(range) {
  range.format = {
    wrapText: true,
    verticalAlignment: "top",
    borders: { preset: "all", style: "thin", color: "#D7E0E8" },
    rowHeight: 27,
  };
}

const registration = workbook.worksheets.add("报名信息模板");
const registrationRows = [
  ["字段", "填写内容", "状态", "隐私与使用说明"],
  ["对应榜单选题序号 / 题目编号", "XH-202619", "已确定", "公开赛题信息"],
  ["固定作品名称", fixedTitle, "已确定", "已经报名，不得改写或替换"],
  ["参赛定位", "赛道一 / 方向一 / A：科学假设生成与研究计划设计", "已确定", "B 类实验闭环作为代表性验证能力"],
  ["推报学院", "", "待填写", "内部材料；不要提交到公开代码仓库"],
  ["学生负责人", "", "待填写", "个人信息；只填写到受控报名材料"],
  ["学号", "", "待填写", "个人信息；只填写到受控报名材料"],
  ["学生负责人所在学院", "", "待填写", "内部材料"],
  ["学历", "", "待填写", "内部材料"],
  ["学生负责人联系方式", "", "待填写", "个人信息；不得出现在截图、日志或公开仓库"],
  ["指导教师", "", "待填写", "个人信息；正式提交前核对顺序"],
  ["指导教师所在学院", "", "待填写", "内部材料"],
  ["是否已在系统报名", "", "待核验", "只记录状态，不在仓库保存登录或凭证信息"],
  ["材料是否完成盖章", "", "待核验", "盖章件存放在受控目录，不进入普通源码目录"],
  ["初期研究情况", "已完成科研Agent流程、证据治理、候选假设、研究计划与多轮实验反馈能力建设；下一阶段集中补齐125个科学问题输出、阿里云百炼证明和正式提交包。", "待审核", "脱敏摘要，可根据报名系统字数限制压缩"],
  ["作品简介", "平台面向前沿科学问题，以Qwen系列模型和多Agent协作完成证据检索、科学假设生成、多维审查、研究计划设计及反馈修订，并由研究者在高杠杆节点审批。代表性实验用于验证计划可执行性和结果反馈能力。", "待审核", "不夸大自动科研或实验结论边界"],
];

styleTitle(registration, "A1:D1", "挑战杯报名信息脱敏模板", "#DCEAF5", "#173F5F");
registration.getRangeByIndexes(2, 0, registrationRows.length, 4).values = registrationRows;
styleHeader(registration.getRange("A3:D3"), "#DCEAF5", "#173F5F");
styleBody(registration.getRange(`A4:D${registrationRows.length + 2}`));
registration.getRange("A5:D6").format.rowHeight = 36;
registration.getRange("A17:D18").format.rowHeight = 62;
registration.getRange(`A4:A${registrationRows.length + 2}`).format = {
  fill: "#F4F8FB",
  font: { bold: true, color: "#173F5F" },
};
styleSheet(registration, `A1:D${registrationRows.length + 2}`, [95, 320, 70, 220]);

const requirements = workbook.worksheets.add("赛题当前要求");
const requirementRows = [
  ["类别", "要求", "当前项目状态", "处理决定", "来源"],
  ["作品名称", fixedTitle, "已固定", "所有对外材料统一使用", officialPage],
  ["参赛主线", "方向 A：科学假设生成与研究计划设计", "已锁定", "实验反馈作为验证能力，不替代 A 交付", officialPage],
  ["125题交付", "选择方向 A 时提交全部125个科学问题的输出结果文档", "清单与协议已建立", "先完成百炼接入和1题样例，再按每批5题生成正式结果", officialPage],
  ["模型", "使用Qwen系列模型", "有本地Qwen记录", "补正式模型标识和调用链证明", officialPage],
  ["平台证明", "通过阿里云百炼或官方推荐工具形成可核验调用证据", "缺百炼截图", "保留脱敏截图、调用日志和模型配置", officialPage],
  ["主文档", "PPT/PDF不超过20页；按更严格口径以PDF提交", "未收束", "围绕评分项压缩为单一主文档", officialPage],
  ["测试API", "提供可调用测试API", "待固化", "提供评审可调用入口、样例和限流说明", officialPage],
  ["交互前端", "提供可交互前端页面入口", "已有产品基础", "固化评审路径并消除旧标题", officialPage],
  ["测试案例", "提供代表性输入、输出结果", "实验结果已存在", "选2至3个深度案例并保留边界和失败记录", officialPage],
  ["技术材料", "详细技术报告、源码、工作流、上下文工程和数据来源", "分散存在", "建立提交索引和复现说明", nadcNotice],
  ["演示视频", "10分钟以内，可选", "未制作", "主材料稳定后制作", officialPage],
  ["提交截止", "2026-09-05前", "进行中", "提交前再次核对官网和答疑群", nadcNotice],
];

styleTitle(requirements, "A1:E1", "赛题当前硬约束与项目对齐", "#DCEFE7", "#245B47");
requirements.getRangeByIndexes(2, 0, requirementRows.length, 5).values = requirementRows;
styleHeader(requirements.getRange("A3:E3"), "#DCEFE7", "#245B47");
styleBody(requirements.getRange(`A4:E${requirementRows.length + 2}`));
requirements.getRange(`A4:E${requirementRows.length + 2}`).format.rowHeight = 42;
requirements.getRange(`A4:A${requirementRows.length + 2}`).format = {
  fill: "#F1F8F4",
  font: { bold: true, color: "#245B47" },
};
styleSheet(requirements, `A1:E${requirementRows.length + 2}`, [70, 240, 100, 205, 170]);

const checklist = workbook.worksheets.add("提交清单");
const checklistRows = [
  ["优先级", "交付物", "是否必需", "状态", "证据位置 / 负责人备注"],
  ["P0", "固定作品名全局一致性", "必需", "进行中", "挑战杯/README.md 为唯一事实源"],
  ["P0", "125个科学问题规范化清单", "必需", "已完成", "挑战杯/data/science_125_questions.json"],
  ["P0", "125题批处理任务账本和逐题输出", "必需", "未开始", "按125题执行协议.md分25批推进"],
  ["P0", "阿里云百炼/Qwen正式调用证明", "必需", "未开始", ""],
  ["P1", "2至3个代表性深度案例", "必需", "进行中", "Stage 3实验可作为一个验证案例"],
  ["P1", "可调用测试API", "必需", "未开始", ""],
  ["P1", "可交互前端入口", "必需", "进行中", ""],
  ["P1", "20页以内正式PDF", "必需", "未开始", ""],
  ["P1", "源码与复现说明", "必需", "进行中", ""],
  ["P1", "代表性输入输出结果", "必需", "进行中", ""],
  ["P2", "10分钟以内演示视频", "可选", "未开始", ""],
  ["P2", "盖章报名表和提交附件", "必需", "待核验", "真实文件只存受控目录"],
  ["P2", "网盘链接、提取码和上传时间截图", "必需", "未开始", "正式提交前生成"],
];

styleTitle(checklist, "A1:E1", "挑战杯提交清单（脱敏）", "#F5E8CB", "#6B4B16");
checklist.getRangeByIndexes(2, 0, checklistRows.length, 5).values = checklistRows;
styleHeader(checklist.getRange("A3:E3"), "#F5E8CB", "#6B4B16");
styleBody(checklist.getRange(`A4:E${checklistRows.length + 2}`));
checklist.getRange(`A4:E${checklistRows.length + 2}`).format.rowHeight = 30;
checklist.getRange(`A4:A${checklistRows.length + 2}`).format = {
  fill: "#FBF7ED",
  font: { bold: true, color: "#6B4B16" },
  horizontalAlignment: "center",
};
styleSheet(checklist, `A1:E${checklistRows.length + 2}`, [55, 210, 75, 75, 260]);

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(outputPath);
