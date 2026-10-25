import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import { redirectToCanonicalWorkbenchHost } from "./app/canonicalWorkbenchHost";
import { setBrowserTelemetryStartupPending } from "./app/browserTelemetry";
import { VuiProvider } from "./components/vui/VuiProvider";
import "./design/tokens.css";
import "./design/base.css";
import "./design/tailwind.css";
import "./design/vui-provider-theme.css";
import "./design/vui-native-controls.css";
import "./design/workbench-shell.css";
import "./design/workbench-frame.css";

if (!redirectToCanonicalWorkbenchHost()) {
  // Hold routine delivery before React effects can post their first route event.
  // Launcher and assistant windows have separate startup owners.
  if (!/^\/(?:launcher|launcher-assistant|desktop-assistant|desktop-pet)(?:\/|$)/.test(window.location.pathname)) {
    setBrowserTelemetryStartupPending(true);
  }
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <VuiProvider>
        <App />
      </VuiProvider>
    </React.StrictMode>,
  );
}
