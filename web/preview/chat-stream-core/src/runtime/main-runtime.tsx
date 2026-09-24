import React from "react";
import ReactDOM from "react-dom/client";

// Same stylesheet chain the production app boots with, resolved read-only from
// web/src through the preview vite dev server (fs.allow covers web/).
import "../../../../src/design/tokens.css";
import "../../../../src/design/base.css";
import "../../../../src/design/tailwind.css";
import "../../../../src/design/vui-provider-theme.css";
import "../../../../src/design/vui-native-controls.css";
import "../../../../src/design/workbench-shell.css";
import { RuntimeScene } from "./RuntimeScene";

window.addEventListener("error", (event) => {
  const errors = (window as unknown as Record<string, unknown[]>).__consoleErrors as string[] | undefined;
  if (errors) {
    errors.push(`error: ${String(event.message)}`);
  }
});

ReactDOM.createRoot(document.getElementById("runtime-root")!).render(
  <React.StrictMode>
    <RuntimeScene />
  </React.StrictMode>,
);
