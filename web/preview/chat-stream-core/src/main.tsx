import React from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./app.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("preview root missing");
}
createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
