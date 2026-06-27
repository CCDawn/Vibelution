import { readFileSync } from "node:fs";

export type DesktopPublicProductEntry = {
  id: string;
  label: string;
  path: string;
  target: string;
  windowProvider: string;
  shortcutAllowed: boolean;
  publicProductEntry: boolean;
};

export type DesktopCatalogEntry = {
  id: string;
  path?: string;
  provider?: string;
  target?: string;
  publicProductEntry: boolean;
};

export type DesktopDeepLinkEntry = {
  route: string;
  action: string;
  publicProductEntry: boolean;
};

export type DesktopEntryCatalog = {
  schemaVersion: number;
  publicProductEntries: DesktopPublicProductEntry[];
  operatorEntries: DesktopCatalogEntry[];
  fallbackProviders: DesktopCatalogEntry[];
  forbiddenProductEntries: DesktopCatalogEntry[];
  deepLinks: DesktopDeepLinkEntry[];
};

export type DeepLinkRegistrationPlan = {
  schemaVersion: 1;
  protocol: "vibelution";
  enabled: boolean;
  executablePath: string;
  publicEntryId: string;
  publicRoutes: string[];
  rejectedRoutes: string[];
  reason: "" | "missing_executable_path";
};

export type DeepLinkRegistrationReason =
  | DeepLinkRegistrationPlan["reason"]
  | "catalog_unavailable"
  | "development_registration_disabled"
  | "disabled_by_env"
  | "electron_registration_failed"
  | "smoke_registration_disabled"
  | "unsupported_platform";

export type DeepLinkRegistrationResult = {
  schemaVersion: 1;
  protocol: "vibelution";
  attempted: boolean;
  registered: boolean;
  reason: DeepLinkRegistrationReason;
};

export type DeepLinkRegistrationInput = {
  platform: NodeJS.Platform | string;
  executablePath: string;
};

export type DeepLinkProtocolRegistrar = {
  isPackaged: boolean;
  setAsDefaultProtocolClient: (protocol: string, path?: string, args?: string[]) => boolean;
};

export type DeepLinkProtocolRegistrationInput = {
  app: DeepLinkProtocolRegistrar;
  env: NodeJS.ProcessEnv | Record<string, string | undefined>;
  platform: NodeJS.Platform | string;
  smoke: boolean;
};

const VIBELUTION_PROTOCOL = "vibelution";
const PUBLIC_LAUNCHER_FOCUS_ROUTE = "vibelution://launcher/focus";

export function readDesktopEntryCatalog(catalogPath: string): DesktopEntryCatalog {
  return JSON.parse(readFileSync(catalogPath, "utf8")) as DesktopEntryCatalog;
}

export function buildDeepLinkRegistrationPlan(
  catalog: DesktopEntryCatalog,
  input: DeepLinkRegistrationInput
): DeepLinkRegistrationPlan {
  const publicEntry = selectShortcutAllowedPublicEntry(catalog);
  const { publicRoutes, rejectedRoutes } = selectDeepLinkRoutes(catalog);
  const executablePath = String(input.executablePath || "").trim();
  return {
    schemaVersion: 1,
    protocol: VIBELUTION_PROTOCOL,
    enabled: Boolean(executablePath),
    executablePath,
    publicEntryId: publicEntry.id,
    publicRoutes,
    rejectedRoutes,
    reason: executablePath ? "" : "missing_executable_path"
  };
}

export function registerDeepLinkProtocolIfAllowed(
  plan: DeepLinkRegistrationPlan,
  input: DeepLinkProtocolRegistrationInput
): DeepLinkRegistrationResult {
  if (input.smoke) {
    return skippedDeepLinkRegistration(plan, "smoke_registration_disabled");
  }
  if (input.env.VIBELUTION_ELECTRON_REGISTER_DEEP_LINKS === "0") {
    return skippedDeepLinkRegistration(plan, "disabled_by_env");
  }
  if (!input.app.isPackaged) {
    return skippedDeepLinkRegistration(plan, "development_registration_disabled");
  }
  if (input.platform !== "win32") {
    return skippedDeepLinkRegistration(plan, "unsupported_platform");
  }
  if (!plan.enabled) {
    return skippedDeepLinkRegistration(plan, plan.reason);
  }

  try {
    const registered = input.app.setAsDefaultProtocolClient(plan.protocol, plan.executablePath, []);
    return {
      schemaVersion: 1,
      protocol: plan.protocol,
      attempted: true,
      registered,
      reason: registered ? "" : "electron_registration_failed"
    };
  } catch {
    return {
      schemaVersion: 1,
      protocol: plan.protocol,
      attempted: true,
      registered: false,
      reason: "electron_registration_failed"
    };
  }
}

export function skippedDeepLinkRegistration(
  plan: Pick<DeepLinkRegistrationPlan, "protocol">,
  reason: DeepLinkRegistrationReason
): DeepLinkRegistrationResult {
  return {
    schemaVersion: 1,
    protocol: plan.protocol,
    attempted: false,
    registered: false,
    reason
  };
}

function selectShortcutAllowedPublicEntry(catalog: DesktopEntryCatalog): DesktopPublicProductEntry {
  if (catalog.schemaVersion !== 1) {
    throw new Error("desktop entry catalog schemaVersion must be 1");
  }
  const entries = (catalog.publicProductEntries || []).filter(
    (entry) => entry.publicProductEntry === true && entry.shortcutAllowed === true
  );
  if (entries.length !== 1) {
    throw new Error("deep-link registration requires exactly one shortcut-allowed public product entry");
  }
  const [entry] = entries;
  if (entry.target !== "launcher") {
    throw new Error("deep-link registration public product entry must target launcher");
  }
  if (entry.windowProvider !== "electron") {
    throw new Error("deep-link registration public product entry must use the electron window provider");
  }
  return entry;
}

function selectDeepLinkRoutes(catalog: DesktopEntryCatalog): { publicRoutes: string[]; rejectedRoutes: string[] } {
  const deepLinks = catalog.deepLinks || [];
  const publicRoutes = deepLinks.filter((entry) => entry.publicProductEntry === true).map((entry) => entry.route);
  if (publicRoutes.length !== 1 || publicRoutes[0] !== PUBLIC_LAUNCHER_FOCUS_ROUTE) {
    throw new Error("only launcher focus can be a public deep link");
  }
  assertVibelutionRoute(publicRoutes[0]);
  return {
    publicRoutes,
    rejectedRoutes: deepLinks.filter((entry) => entry.publicProductEntry !== true).map((entry) => entry.route)
  };
}

function assertVibelutionRoute(route: string): void {
  const protocol = new URL(route).protocol.replace(/:$/, "");
  if (protocol !== VIBELUTION_PROTOCOL) {
    throw new Error(`unsupported deep-link protocol in registration policy: ${protocol}`);
  }
}
