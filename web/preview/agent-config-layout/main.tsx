import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { VuiProvider } from "../../src/components/vui";
import { App } from "./App";
import "./preview.css";

// Preview is entirely local: no API client, credentials, real prompts, or model calls.
window.fetch = async () => { throw new Error("This isolated preview has no backend connection"); };
const root: Root = import.meta.hot?.data.root ?? createRoot(document.getElementById("root")!);
root.render(<MemoryRouter><VuiProvider><App/></VuiProvider></MemoryRouter>);
if (import.meta.hot) import.meta.hot.dispose(data => { data.root = root; });