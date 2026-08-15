import { execSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";

const cur = readFileSync("src/routes/TeamsRoute.tsx");
console.log("current 知识搜集操作台", cur.indexOf(Buffer.from("知识搜集操作台", "utf8")));

const hash = execSync("git rev-parse 5ef076c85^:web/src/routes/TeamsRoute.tsx", { encoding: "utf8" }).trim();
console.log("blob", hash);
const blob = execSync(`git cat-file -p ${hash}`);
writeFileSync(".tmp-teams-pre8h.tsx", blob);
console.log("blob len", blob.length);
console.log("pre8h 知识搜集操作台", blob.indexOf(Buffer.from("知识搜集操作台", "utf8")));
console.log("pre8h 证据链", blob.indexOf(Buffer.from("证据链", "utf8")));
console.log("pre8h 资料", blob.indexOf(Buffer.from("资料", "utf8")));
console.log("pre8h launcher", blob.indexOf(Buffer.from("renderResearchStageLauncher", "utf8")));

const s = blob.toString("utf8");
const j = s.indexOf('normalizedRole.includes("source")');
console.log("sample", JSON.stringify(s.slice(j, j + 200)));
