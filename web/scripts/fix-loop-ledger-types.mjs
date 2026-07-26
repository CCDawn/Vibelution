import { readFileSync, writeFileSync } from "node:fs";

function fixAnys(path) {
  let t = readFileSync(path, "utf8");
  t = t.replace(/\.(map|find|filter|some|every)\(\(([a-zA-Z_][a-zA-Z0-9_]*)\) =>/g, ".$1(($2: any) =>");
  writeFileSync(path, t);
  console.log("fixed anys", path);
}

let ledger = readFileSync("src/routes/TeamExperimentPlanningLedgerPanel.tsx", "utf8");
if (!ledger.includes("Send")) {
  ledger = ledger.replace(
    'import { AlertTriangle, CheckCircle2, Save } from "lucide-react";',
    'import { AlertTriangle, CheckCircle2, Save, Send } from "lucide-react";',
  );
}
// preferredExperimentMethod may be plain string from route state
ledger = ledger.replace(
  "preferredExperimentMethod || undefined)",
  "(preferredExperimentMethod as ExperimentMethodId | \"\") || undefined)",
);
writeFileSync("src/routes/TeamExperimentPlanningLedgerPanel.tsx", ledger);
console.log("ledger imports/cast");

fixAnys("src/routes/TeamResearchLoopPanel.tsx");
fixAnys("src/routes/TeamExperimentPlanningLedgerPanel.tsx");
