import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const inputPath = path.join(scriptDir, "outputs", "挑战杯报名信息与赛题提取表.xlsx");
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const sheet = workbook.worksheets.getItem("报名填报信息");
const used = sheet.getUsedRange();
const values = used.values;

const fieldValues = new Map([
  ["对应榜单\n选题序号", "44（案例）"],
  ["对应榜单选题序号", "44（案例）"],
  ["推报学院", "计算机学院"],
  ["揭榜作品名称", "AI Agent 驱动的动态攻防推演靶场平台"],
  ["初期研究情况", "对任务进行分解，划分为平台架构设计、AI攻防智能体、环境构建与仿真、数据采集与评估四个方向，并组织开展国内外相关研究现状调研工作"],
  ["学生负责人", "许郭"],
  ["学号", "232050348"],
  ["学生负责人所在学院", "计算机学院"],
  ["学历", "研究生在读"],
  ["学生负责人联系方式", "19855532778"],
  ["指导教师（按照顺序写全）", "陈信、俞东进、王东京"],
  ["指导教师\n所在学院", "计算机学院"],
  ["指导教师所在学院", "计算机学院"],
  ["是否已在系统报名", "是"],
  ["材料是否完成盖章", "是"],
]);

function normalize(value) {
  return String(value ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\s+/g, "")
    .trim();
}

const normalizedMap = new Map(
  [...fieldValues.entries()].map(([key, value]) => [normalize(key), value]),
);

for (let r = 0; r < values.length; r++) {
  for (let c = 0; c < values[r].length; c++) {
    const key = normalize(values[r][c]);
    if (normalizedMap.has(key)) {
      const target = sheet.getCell(r + 1, c);
      target.values = [[normalizedMap.get(key)]];
      target.format = {
        wrapText: true,
        verticalAlignment: "top",
        horizontalAlignment: "center",
      };
    }
  }
}

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(inputPath);
