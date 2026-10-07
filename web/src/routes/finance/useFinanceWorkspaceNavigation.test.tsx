// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { createMemoryRouter, RouterProvider, useLocation, useNavigate } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { parseFinanceWorkspaceNavigation, serializeFinanceWorkspaceNavigation, useFinanceWorkspaceNavigation } from "./useFinanceWorkspaceNavigation";
import { useChatRouteSelection } from "../chat/useChatRouteSelection";
vi.mock("../../app/userActionTelemetry", () => ({ postUserActionObservation: vi.fn() }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
it("normalizes unknown view keys without changing native session or unrelated query parameters", () => {
  const search = "?session=native&returnTo=%2Fagents&finance_area=invalid&finance_tab=bad&finance_prepare=1&finance_report_session=s";
  const value = parseFinanceWorkspaceNavigation(search);
  expect(value).toMatchObject({ area: "workspace", tab: "research", preparing: false, selectedReport: null });
  const params = new URLSearchParams(serializeFinanceWorkspaceNavigation(search, { ...value, area: "reports", selectedReport: { sessionId: "s", turnId: "t" } }));
  expect(params.get("session")).toBe("native");
  expect(params.get("returnTo")).toBe("/agents");
  expect(parseFinanceWorkspaceNavigation(params.toString()).selectedReport).toEqual({ sessionId: "s", turnId: "t" });
});

it("recovers deep links and back/forward, composes same-event updates, and preserves native session changes", async () => {
  function Probe() {
    const view = useFinanceWorkspaceNavigation(), native = useChatRouteSelection();
    const location = useLocation(), navigate = useNavigate();
    return <><output>{JSON.stringify({ ...view, update: undefined, showSession: undefined, search: location.search })}</output>
      <button onClick={() => { view.update({ area: "review" }); view.update({ reviewTab: "cases" }); }}>Review</button>
      <button onClick={() => { native.openSession("new-session"); view.showSession("new-session"); }}>Session</button>
      <button onClick={() => navigate(-1)}>Back</button><button onClick={() => navigate(1)}>Forward</button></>;
  }
  const router = createMemoryRouter([{ path: "/finance", element: <Probe /> }], { initialEntries: ["/finance?session=old&finance_area=reports&finance_report_session=report-session&finance_report_turn=report-turn"] });
  const host = document.createElement("div"), root = createRoot(host); document.body.append(host);
  const click = async (text: string) => act(async () => [...host.querySelectorAll("button")].find(button => button.textContent === text)!.click());
  const value = () => JSON.parse(host.querySelector("output")!.textContent!);
  try {
    await act(async () => root.render(<RouterProvider router={router} />));
    expect(value()).toMatchObject({ area: "reports", selectedReport: { sessionId: "report-session", turnId: "report-turn" } });
    await click("Review");
    expect(value()).toMatchObject({ area: "review", reviewTab: "cases" });
    await click("Back");
    expect(value()).toMatchObject({ area: "reports", reviewTab: "trades" });
    await click("Forward");
    expect(value().reviewTab).toBe("cases");
    await click("Session");
    expect(value()).toMatchObject({ area: "workspace", tab: "research", preparing: false, selectedReport: null });
    expect(new URLSearchParams(value().search).get("session")).toBe("new-session");
  } finally { await act(async () => root.unmount()); router.dispose(); host.remove(); }
});
