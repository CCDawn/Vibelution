import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";

import { VuiProvider } from "../../components/vui";
import "../base.css";
import "../tokens.css";
import "../vui-native-controls.css";
import "../vui-provider-theme.css";
import "./preview.tailwind.css";

import { VuiComponentPreviewApp } from "./VuiComponentPreviewApp";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MemoryRouter>
      <VuiProvider>
        <VuiComponentPreviewApp />
      </VuiProvider>
    </MemoryRouter>
  </StrictMode>,
);
