const root = document.documentElement;
const processToggle = document.querySelector("[data-process-toggle]");
const processStream = document.querySelector("[data-process-stream]");
const processLabel = document.querySelector("[data-process-label]");
const terminalEntry = document.querySelector("[data-terminal-entry]");
const terminalCopy = document.querySelector("[data-terminal-copy]");
const finalAnswer = document.querySelector("[data-final-answer]");
const stateControls = Array.from(document.querySelectorAll("[data-state-control]"));
const themeToggle = document.querySelector("[data-theme-toggle]");

const stateContent = {
  completed: {
    processLabel: "已处理 13s",
    terminalCopy: "整理了 8 个可信来源",
    terminalState: "",
    answer: "已完成资料检索。下面是根据可信来源整理的结论。",
    showAnswer: true,
  },
  running: {
    processLabel: "处理中 13s",
    terminalCopy: "正在整理搜索结果",
    terminalState: "is-running",
    answer: "",
    showAnswer: false,
  },
  failed: {
    processLabel: "处理已停止",
    terminalCopy: "Search failed: provider unavailable",
    terminalState: "is-failed",
    answer: "搜索服务暂时不可用，已保留前面的处理记录。",
    showAnswer: true,
  },
};

function renderState(state) {
  const content = stateContent[state];
  processLabel.textContent = content.processLabel;
  terminalCopy.textContent = content.terminalCopy;
  terminalEntry.className = `tool-entry ${content.terminalState}`.trim();
  finalAnswer.querySelector("p").textContent = content.answer;
  finalAnswer.hidden = !content.showAnswer;
  processToggle.setAttribute("aria-expanded", "true");
  processStream.hidden = false;

  stateControls.forEach((control) => {
    const selected = control.dataset.stateControl === state;
    control.classList.toggle("is-selected", selected);
    control.setAttribute("aria-pressed", String(selected));
  });
}

processToggle.addEventListener("click", () => {
  const expanded = processToggle.getAttribute("aria-expanded") === "true";
  processToggle.setAttribute("aria-expanded", String(!expanded));
  processStream.hidden = expanded;
});

stateControls.forEach((control) => {
  control.addEventListener("click", () => renderState(control.dataset.stateControl));
});

themeToggle.addEventListener("click", () => {
  const nextTheme = root.dataset.theme === "light" ? "dark" : "light";
  root.dataset.theme = nextTheme;
  themeToggle.textContent = nextTheme === "light" ? "深色" : "浅色";
});
