import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import { redirectToCanonicalWorkbenchHost } from "./app/canonicalWorkbenchHost";
import { VuiProvider } from "./components/vui/VuiProvider";
import "./design/tokens.css";
import "./design/base.css";
import "./design/tailwind.css";
import "./design/vui-provider-theme.css";
import "./design/vui-native-controls.css";
import "./design/workbench-shell.css";

if (!redirectToCanonicalWorkbenchHost()) {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <VuiProvider>
        <App />
      </VuiProvider>
    </React.StrictMode>,
  );
}
