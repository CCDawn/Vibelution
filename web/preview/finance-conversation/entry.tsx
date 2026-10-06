import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { FinanceConversationPreview } from "./main";

const root = createRoot(document.getElementById("root")!);
root.render(<StrictMode><FinanceConversationPreview /></StrictMode>);

if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
