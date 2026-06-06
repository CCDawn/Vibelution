import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import { redirectToCanonicalWorkbenchHost } from "./app/canonicalWorkbenchHost";
import "./design/tokens.css";
import "./design/base.css";

if (!redirectToCanonicalWorkbenchHost()) {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
