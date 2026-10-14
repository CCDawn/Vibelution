import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { FinanceDesktopTabsPreview } from "./main";
import { FinanceToolPreviewState } from "./tools";

const root = createRoot(document.getElementById("root")!);
root.render(<StrictMode><FinanceToolPreviewState><FinanceDesktopTabsPreview /></FinanceToolPreviewState></StrictMode>);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
