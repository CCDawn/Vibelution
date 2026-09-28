/**
 * 预览入口：只挂预览应用；生产样式按生产 main.tsx 同序导入（只读引用，零改动）。
 * Tailwind 入口用本预览自己的 preview.tailwind.css（生产 tailwind.css 的 @source
 * 不含 preview 目录，令牌类不会为预览代码生成）。
 * fontScaleTokens.css 最后导入：在 :root 上以 calc(基准±Npx) 重写主字阶（唯一改写点），
 * 颜色/圆角/行高/字重等其余令牌全部照抄生产 tokens.css，不在此重复。
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { VuiProvider } from "../../../src/components/vui/VuiProvider";
import { PreviewApp } from "./PreviewApp";
import "../../../src/design/tokens.css";
import "../../../src/design/base.css";
import "../../../src/design/vui-provider-theme.css";
import "../../../src/design/vui-native-controls.css";
import "./preview.tailwind.css";
import "./fontScaleTokens.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <VuiProvider>
      <PreviewApp />
    </VuiProvider>
  </StrictMode>,
);
