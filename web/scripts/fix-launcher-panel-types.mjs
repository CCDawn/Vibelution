import { readFileSync, writeFileSync } from "node:fs";

const path = "src/routes/TeamResearchStageLauncherPanel.tsx";
let t = readFileSync(path, "utf8");

t = t.replace(/\(method\) =>/g, "(method: any) =>");
t = t.replace(/\(adapter\) =>/g, "(adapter: any) =>");
t = t.replace(
  /setPreferredExperimentMethod\(event\.target\.value as ExperimentMethodId\)/g,
  'setPreferredExperimentMethod(event.target.value as ExperimentMethodId | "")',
);
t = t.replace(
  /setPreferredExperimentMethod\(method\.methodId\)/g,
  "setPreferredExperimentMethod(method.methodId as ExperimentMethodId)",
);
// ResearchProjectSwitcher currentExperimentMethod may need cast
t = t.replace(
  /currentExperimentMethod=\{preferredExperimentMethod\}/g,
  "currentExperimentMethod={preferredExperimentMethod as ExperimentMethodId | \"\"}",
);

writeFileSync(path, t);
console.log("fixed type annotations");
