import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import { redirectToCanonicalWorkbenchHost } from "./app/canonicalWorkbenchHost";
import { VibelutionHeroProvider } from "./components/vui/renderers/heroui/HeroProvider";
import "./design/tokens.css";
import "./design/base.css";
import "./design/tailwind.css";
import "./design/heroui-theme.css";

if (!redirectToCanonicalWorkbenchHost()) {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <VibelutionHeroProvider>
        <App />
      </VibelutionHeroProvider>
    </React.StrictMode>,
  );
}
