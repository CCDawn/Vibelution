import { createRoot } from "react-dom/client";
import { VuiProvider } from "../../src/components/vui/VuiProvider";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "./preview.tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "../../src/design/workbench-frame.css";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(<VuiProvider><App/></VuiProvider>);
