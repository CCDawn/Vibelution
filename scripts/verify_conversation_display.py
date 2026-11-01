"""Capture and verify the real ConversationView with deterministic, isolated inputs.

Run Vite in the task's web directory, then pass its loopback preview URL. All API
requests are intercepted; this script never opens or writes a product session.
Use --record-only for an unfixed baseline, and distinct --label values for A/B.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


FROZEN_CLOCK = """{
  const RealDate = Date;
  const now = RealDate.parse('2026-11-01T09:00:12Z');
  globalThis.Date = class extends RealDate {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  };
}"""
SNAPSHOT = """root => {
  const cells = [...root.querySelectorAll('[data-codex-transcript-cell-kind]')];
  const tools = cells.filter(x => x.dataset.codexTranscriptCellKind === 'tool_call');
  const answers = cells.filter(x => x.dataset.codexTranscriptCellPhase === 'final_answer');
  const rails = [...root.querySelectorAll(
    '.turnStatusNote,.codexTranscriptErrorCell,.operationDetails,.operationDetailValue,' +
    '.rolloutTraceList,.vui-components-conversationactiveturnstatusnote[role="status"],' +
    '[data-conversation-running-tasks]')].filter(x => x.getClientRects().length > 0);
  return {
    tools: tools.map(x => ({key: x.dataset.conversationPartKey, status: x.dataset.codexTranscriptCellStatus})),
    answers: answers.map(x => x.innerText.trim()),
    answerInsideProcess: answers.some(x => x.closest('[data-codex-process-disclosure]')),
    stateLines: rails.filter(x => parseFloat(getComputedStyle(x).borderLeftWidth) > 0).map(x => x.className),
    visibleStateContainers: rails.length,
    overflow: root.scrollWidth > root.clientWidth || document.documentElement.scrollWidth > innerWidth,
    hasReasoning: root.textContent.includes('先检查会话投影'),
    hasConcreteError: root.textContent.includes('测试文件暂不可用，请检查路径后重试。'),
  };
}"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Vite URL ending in /conversation-projection-preview.html")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--browser-executable", help="Existing Chromium/Chrome/Edge executable")
    parser.add_argument("--label", default="after")
    parser.add_argument("--record-only", action="store_true")
    parser.add_argument("--scenes", nargs="+", choices=["running", "completed-collapsed", "completed-expanded", "completed-reloaded", "failed", "stopped", "compact-failed", "waiting", "disconnected", "background", "compact-disconnected", "dark-running", "dark-failed"], help="Capture only these named scenes; omit for the complete matrix")
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.path != "/conversation-projection-preview.html":
        parser.error("Only the isolated loopback conversation preview is supported")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.label):
        parser.error("label must contain only letters, numbers, hyphens or underscores")
    from playwright.sync_api import sync_playwright

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    api_pattern = re.compile(r"^https?://[^/]+/api/")
    results: list[dict] = []
    errors: list[str] = []
    intercepted: list[str] = []
    with sync_playwright() as playwright:
        launch = {"executable_path": args.browser_executable} if args.browser_executable else {"channel": "msedge"}
        browser = playwright.chromium.launch(headless=True, **launch)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            page.emulate_media(reduced_motion="reduce")
            page.add_init_script(FROZEN_CLOCK)
            page.on("pageerror", lambda error: errors.append(str(error)[:500]))
            page.on("console", lambda message: errors.append(message.text[:500]) if message.type == "error" else None)

            def stub_api(route):
                intercepted.append(route.request.method)
                path = urlparse(route.request.url).path
                if path == "/api/control-token":
                    route.fulfill(json={"controlToken": "visual-fixture-token"})
                elif path == "/api/runtime-tasks":
                    background = "scene=background" in page.url and "status=ended" not in route.request.url
                    task = {"taskId": "visual-background", "kind": "child_session", "status": "running", "title": "并行检查样式", "parentSessionId": "visual-conversation", "startedAt": "2026-11-01T09:00:00Z"}
                    route.fulfill(json={"revision": "visual-1", "running": [task] if background else [], "ended": {"items": [], "total": 0, "nextCursor": ""}})
                else:
                    route.fulfill(json={"items": [], "zh": {}, "en": {}})

            page.route(api_pattern, stub_api)

            def capture(name: str, scene: str, *, expanded: bool = True, theme: str = "light", compact: bool = False, reload: bool = False) -> dict | None:
                if args.scenes and name not in args.scenes:
                    return None
                page.set_viewport_size({"width": 390 if compact else 1440, "height": 1000})
                page.goto(f"{base_url}?scene={scene}", wait_until="domcontentloaded")
                if reload:
                    page.reload(wait_until="domcontentloaded")
                proof = page.get_by_test_id("conversation-proof")
                if scene == "waiting":
                    proof.locator('.vui-components-conversationactiveturnstatusnote[role="status"]').wait_for()
                else:
                    proof.locator("[data-codex-transcript-surface]").first.wait_for()
                if scene == "disconnected":
                    proof.locator('.vui-components-conversationactiveturnstatusnote[role="status"]').wait_for()
                if scene == "background":
                    proof.locator("[data-conversation-running-tasks]").wait_for()
                page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                disclosure = proof.locator("[data-codex-process-disclosure]").first
                if expanded and disclosure.count() and disclosure.get_attribute("data-codex-process-expanded") == "false":
                    disclosure.locator(":scope > summary").click()
                if expanded:
                    for summary in proof.locator('details[data-codex-transcript-cell-kind="tool_call"]:not([open]) > summary').all():
                        summary.click()
                page.wait_for_timeout(250)
                state = proof.evaluate(SNAPSHOT)
                checks = {"noStateLines": not state["stateLines"], "noOverflow": not state["overflow"], "answerOutsideProcess": not state["answerInsideProcess"]}
                if expanded:
                    expected = {"running": ["running", "running"], "disconnected": ["running", "running"], "waiting": [], "background": ["completed", "completed"], "completed": ["completed", "completed"], "failed": ["failed", "completed"], "stopped": ["cancelled", "cancelled"]}
                    checks["toolLifecycles"] = [tool["status"] for tool in state["tools"]] == expected[scene]
                    if scene != "waiting":
                        checks["reasoningPreserved"] = state["hasReasoning"]
                if scene in {"waiting", "disconnected", "background"}:
                    checks["stateContainerPresent"] = state["visibleStateContainers"] > 0
                if scene == "completed":
                    checks["oneFinalAnswer"] = len(state["answers"]) == 1
                if scene == "failed" and expanded:
                    checks["concreteError"] = state["hasConcreteError"]
                image = output / f"{args.label}-{name}.png"
                page.screenshot(path=str(image), full_page=True, animations="disabled")
                result = {"name": name, "image": image.name, "checks": checks, "state": state}
                results.append(result)
                print(json.dumps({"scene": name, "checks": checks}), flush=True)
                return state

            capture("running", "running")
            capture("completed-collapsed", "completed", expanded=False)
            completed = capture("completed-expanded", "completed")
            reopened = capture("completed-reloaded", "completed", reload=True)
            if completed is not None and reopened is not None:
                results[-1]["checks"]["reloadParity"] = (completed["tools"], completed["answers"]) == (reopened["tools"], reopened["answers"])
            capture("failed", "failed")
            capture("stopped", "stopped")
            capture("compact-failed", "failed", compact=True)
            capture("waiting", "waiting")
            capture("disconnected", "disconnected")
            capture("background", "background")
            capture("compact-disconnected", "disconnected", compact=True)
            capture("dark-running", "running", theme="dark")
            capture("dark-failed", "failed", theme="dark")
        finally:
            browser.close()
    passed = bool(results) and not errors and all(all(result["checks"].values()) for result in results)
    manifest = {"url": base_url, "syntheticInputs": True, "productionComponent": "ConversationView", "allApiRequestsIntercepted": True, "interceptedRequests": len(intercepted), "errors": errors, "passed": passed, "results": results}
    (output / f"{args.label}-evidence.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "recordOnly": args.record_only, "outputDir": str(output)}))
    return 0 if passed or args.record_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
