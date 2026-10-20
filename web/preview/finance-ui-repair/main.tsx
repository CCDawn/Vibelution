import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { VuiProvider } from "../../src/components/vui";
import { App } from "./App";
import { quoteFixture } from "./NumericAcceptance";
import "./preview.css";
// Isolated fixtures only: no API transport, native sessions or account writes.
window.fetch = async (input, init) => {
  const url = new URL(input instanceof Request ? input.url : String(input), location.href);
  const method = init?.method ?? (input instanceof Request ? input.method : "GET");
  if (method === "GET" && url.pathname === "/api/control-token") {
    // Dummy fixture consumed only by the intercepted local quote request.
    return new Response(JSON.stringify({ header: "x-preview-only", controlToken: "isolated-preview-no-authority" }), { headers: { "Content-Type": "application/json" } });
  }
  if (method === "GET" && url.pathname === "/api/financial-market/quotes") {
    return new Response(JSON.stringify(quoteFixture()), { headers: { "Content-Type": "application/json" } });
  }
  throw new Error("Preview has no backend connection");
};
createRoot(document.getElementById("root")!).render(<MemoryRouter><VuiProvider><App /></VuiProvider></MemoryRouter>);
