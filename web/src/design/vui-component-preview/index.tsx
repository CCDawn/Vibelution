import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { VuiProvider } from "../../components/vui";
import "../base.css";
import "../tokens.css";
import "../vui-native-controls.css";
import "../vui-provider-theme.css";
import "./preview.tailwind.css";

import { VuiComponentPreviewApp } from "./VuiComponentPreviewApp";

// Catalogs use deterministic example props. Query-backed child components still
// need their normal context, but this isolated page must not read a live backend.
const previewQueryClient = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={previewQueryClient}>
      <MemoryRouter>
        <VuiProvider>
          <VuiComponentPreviewApp />
        </VuiProvider>
      </MemoryRouter>
    </QueryClientProvider>
  </StrictMode>,
);
