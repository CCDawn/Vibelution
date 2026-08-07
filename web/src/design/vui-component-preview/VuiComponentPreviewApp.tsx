import { useEffect, useState } from "react";

import { DataCatalog } from "./catalog/DataCatalog";
import { AestheticCatalog } from "./catalog/AestheticCatalog";
import { AgentCatalog } from "./catalog/AgentCatalog";
import { FormsCatalog } from "./catalog/FormsCatalog";
import { FoundationCatalog } from "./catalog/FoundationCatalog";
import { InteractiveCatalog } from "./catalog/InteractiveCatalog";
import { NativeFormsCatalog } from "./catalog/NativeFormsCatalog";
import { RecipeCatalog } from "./catalog/RecipeCatalog";
import { StructureCatalog } from "./catalog/StructureCatalog";
import { TeamCatalog } from "./catalog/TeamCatalog";
import { TeamSourceCatalog } from "./catalog/TeamSourceCatalog";
import { WorkflowCatalog } from "./catalog/WorkflowCatalog";
import { VuiPreviewHeader } from "./VuiPreviewHeader";

export function VuiComponentPreviewApp() {
  const [theme, setTheme] = useState<"dark" | "light">("light");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  return (
    <main
      data-vui-preview
      className="min-h-screen bg-vui-bg-canvas px-5 py-5 text-vui-fg-primary sm:px-8 lg:px-12"
    >
      <div className="mx-auto grid w-full max-w-[92rem] gap-10">
        <VuiPreviewHeader theme={theme} onToggleTheme={() => setTheme((current) => current === "light" ? "dark" : "light")} />
        <FoundationCatalog />
        <InteractiveCatalog />
        <FormsCatalog />
        <NativeFormsCatalog />
        <DataCatalog />
        <StructureCatalog />
        <AestheticCatalog />
        <RecipeCatalog />
        <AgentCatalog />
        <TeamCatalog />
        <TeamSourceCatalog />
        <WorkflowCatalog />
      </div>
    </main>
  );
}
