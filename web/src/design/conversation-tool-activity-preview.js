const root = document.documentElement;
const activityRegion = document.querySelector("[data-preview-state]");
const activityToggle = document.querySelector("[data-activity-toggle]");
const activityDetails = document.querySelector("[data-activity-details]");
const themeToggle = document.querySelector("[data-theme-toggle]");
const stateControls = Array.from(document.querySelectorAll("[data-state-control]"));

const stateContent = {
  running: {
    summaryTitle: "正在搜索资料",
    summaryMeta: "2/3 步骤 · 13s",
    summaryIcon: "running",
    searchIcon: "completed",
    searchTitle: "搜索 4 个查询",
    searchDescription: "官方文档、项目状态与相关工作流",
    searchTime: "13s",
    synthesisIcon: "running",
    synthesisTitle: "正在整理搜索结果",
    synthesisDescription: "归并来源，准备生成回答",
    synthesisTime: "运行中",
    showFailureAction: false,
  },
  completed: {
    summaryTitle: "已完成资料搜索",
    summaryMeta: "3 步骤 · 13.4s",
    summaryIcon: "completed",
    searchIcon: "completed",
    searchTitle: "搜索 4 个查询",
    searchDescription: "已保留 8 个可信来源",
    searchTime: "13s",
    synthesisIcon: "completed",
    synthesisTitle: "整理搜索结果",
    synthesisDescription: "来源已归并，回答已生成",
    synthesisTime: "0.3s",
    showFailureAction: false,
  },
  failed: {
    summaryTitle: "搜索服务暂时不可用",
    summaryMeta: "第 2 步失败 · 13.2s",
    summaryIcon: "failed",
    searchIcon: "failed",
    searchTitle: "搜索 4 个查询",
    searchDescription: "服务未响应，可从此步骤重试",
    searchTime: "失败",
    synthesisIcon: "queued",
    synthesisTitle: "等待搜索结果",
    synthesisDescription: "上一步恢复后自动继续",
    synthesisTime: "已暂停",
    showFailureAction: true,
  },
};

function setIcon(element, state) {
  element.className = `status-icon status-icon--${state}`;
}

function renderState(state) {
  const content = stateContent[state];
  const shouldExpand = state !== "completed";
  activityRegion.dataset.previewState = state;
  activityToggle.setAttribute("aria-expanded", String(shouldExpand));
  activityDetails.hidden = !shouldExpand;
  document.querySelector(".technical-details").open = false;
  document.querySelector("[data-summary-title]").textContent = content.summaryTitle;
  document.querySelector("[data-summary-meta]").textContent = content.summaryMeta;
  document.querySelector("[data-search-title]").textContent = content.searchTitle;
  document.querySelector("[data-search-description]").textContent = content.searchDescription;
  document.querySelector("[data-search-time]").textContent = content.searchTime;
  document.querySelector("[data-synthesis-title]").textContent = content.synthesisTitle;
  document.querySelector("[data-synthesis-description]").textContent = content.synthesisDescription;
  document.querySelector("[data-synthesis-time]").textContent = content.synthesisTime;
  document.querySelector("[data-failure-action]").hidden = !content.showFailureAction;
  setIcon(document.querySelector("[data-summary-icon]"), content.summaryIcon);
  setIcon(document.querySelector("[data-search-icon]"), content.searchIcon);
  setIcon(document.querySelector("[data-synthesis-icon]"), content.synthesisIcon);
  stateControls.forEach((control) => {
    const selected = control.dataset.stateControl === state;
    control.classList.toggle("is-selected", selected);
    control.setAttribute("aria-pressed", String(selected));
  });
}

activityToggle.addEventListener("click", () => {
  const expanded = activityToggle.getAttribute("aria-expanded") === "true";
  activityToggle.setAttribute("aria-expanded", String(!expanded));
  activityDetails.hidden = expanded;
});

stateControls.forEach((control) => {
  control.addEventListener("click", () => renderState(control.dataset.stateControl));
});

themeToggle.addEventListener("click", () => {
  const nextTheme = root.dataset.theme === "light" ? "dark" : "light";
  root.dataset.theme = nextTheme;
  themeToggle.textContent = nextTheme === "light" ? "深色" : "浅色";
});
