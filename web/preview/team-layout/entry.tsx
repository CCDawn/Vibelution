import { createRoot } from "react-dom/client";
import { StrictMode } from "react";
import "../../src/design/base.css";
import "../../src/design/tokens.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "./preview.css";
import { TeamLayoutPreview } from "./App";

const root = createRoot(document.getElementById("root")!);
root.render(<StrictMode><TeamLayoutPreview /></StrictMode>);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
