import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { InvestmentPreview } from "./main";
const root = createRoot(document.getElementById("root")!);
root.render(<StrictMode><InvestmentPreview /></StrictMode>);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
