import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../base.css";
import "../tokens.css";
import "../vui-provider-theme.css";
import "../vui-native-controls.css";
import "./preview.tailwind.css";
import { TeamChatPreview } from "./App";

const root = createRoot(document.getElementById("root")!);
root.render(<StrictMode><TeamChatPreview /></StrictMode>);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
