import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../../../src/design/base.css";
import "../../../src/design/tokens.css";
import "../../../src/design/vui-provider-theme.css";
import "../../../src/design/vui-native-controls.css";
import "./preview.tailwind.css";
import { TeamChatPreview } from "./App";

const root = createRoot(document.getElementById("root")!);
root.render(<StrictMode><TeamChatPreview /></StrictMode>);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
