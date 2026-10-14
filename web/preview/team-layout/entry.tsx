import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { loadDictionaryDomains } from "../../src/i18n/loadDictionaryDomains";
import { dictionaryDomainsQueryKey, normalizeDictionaryDomains } from "../../src/i18n/dictionaryDomainIds";
import { queryKeys } from "../../src/api/queryKeys";
import { StrictMode } from "react";
import "../../src/design/base.css";
import "../../src/design/tokens.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "./preview.css";
import { TeamLayoutPreview } from "./App";

const queryClient = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false, refetchOnWindowFocus: false, refetchOnMount: false } } });
queryClient.setQueryData(queryKeys.configPublic(), { language: "zh", modelLabels: {} });
const dictionary = await loadDictionaryDomains();
for (const domains of [normalizeDictionaryDomains(undefined), normalizeDictionaryDomains(["core"]), normalizeDictionaryDomains(["chat"]), normalizeDictionaryDomains(["teams"])]) {
  queryClient.setQueryData(["i18n", "dictionary-domains", dictionaryDomainsQueryKey(domains)], dictionary);
}
const root = createRoot(document.getElementById("root")!);
root.render(<StrictMode><QueryClientProvider client={queryClient}><BrowserRouter><TeamLayoutPreview /></BrowserRouter></QueryClientProvider></StrictMode>);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
