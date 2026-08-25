export async function startOrFocusWorkbenchFromProductEntry(input: {
  startLifecycle: () => Promise<{
    accepted?: boolean;
    message?: string;
    code?: string;
  }>;
}): Promise<"started"> {
  // A reachable HTTP endpoint only proves that *some* prior backend is alive.
  // Product-entry opens must always pass through the lifecycle owner so it can
  // verify the active release before deciding whether focus is safe.
  const result = await input.startLifecycle();
  if (result.accepted === false) {
    throw new Error(result.message || result.code || "Workbench startup was not accepted.");
  }
  return "started";
}
