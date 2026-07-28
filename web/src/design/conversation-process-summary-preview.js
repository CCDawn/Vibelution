const scenarioButtons = [...document.querySelectorAll("[data-scenario]")];
const scenarioPanels = [...document.querySelectorAll("[data-scenario-panel]")];
const collapseAllButton = document.querySelector("#collapse-all");

function activateScenario(scenario) {
  for (const button of scenarioButtons) {
    const active = button.dataset.scenario === scenario;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  }

  for (const panel of scenarioPanels) {
    const active = panel.dataset.scenarioPanel === scenario;
    panel.hidden = !active;
  }
}

for (const button of scenarioButtons) {
  button.addEventListener("click", () => activateScenario(button.dataset.scenario));
}

collapseAllButton?.addEventListener("click", () => {
  const visiblePanel = scenarioPanels.find((panel) => !panel.hidden);
  for (const disclosure of visiblePanel?.querySelectorAll("details") ?? []) {
    disclosure.open = false;
  }
});
