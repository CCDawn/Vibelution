/**
 * 预览入口：只挂预览应用；生产样式按生产 main.tsx 同序导入（只读引用，零改动）。
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { VuiProvider } from "../../../src/components/vui/VuiProvider";
import { PreviewApp } from "./PreviewApp";
import "../../../src/design/tokens.css";
import "../../../src/design/base.css";
import "../../../src/design/tailwind.css";
import "../../../src/design/vui-provider-theme.css";
import "../../../src/design/vui-native-controls.css";
import "./preview.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <VuiProvider>
      <PreviewApp />
    </VuiProvider>
  </StrictMode>,
);
