import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { VuiProvider } from "../../src/components/vui";
import { App } from "./App";
import "./preview.css";

createRoot(document.getElementById("root")!).render(<MemoryRouter><VuiProvider><App /></VuiProvider></MemoryRouter>);
