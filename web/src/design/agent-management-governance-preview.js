const tabs = [...document.querySelectorAll(".view-tab")];
const panels = [...document.querySelectorAll(".view-panel")];
const inspector = document.querySelector(".inspector");

const setView = (view) => {
  tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.view === view));
  panels.forEach((panel) => panel.classList.toggle("active", panel.id === `view-${view}`));
};

tabs.forEach((tab) => tab.addEventListener("click", () => setView(tab.dataset.view)));
document.querySelector("#open-impact")?.addEventListener("click", () => setView("impact"));
document.querySelector(".empty-panel .secondary")?.addEventListener("click", () => setView("effective"));
document.querySelector(".close-inspector")?.addEventListener("click", () => inspector?.classList.add("closed"));

const inspectorCopy = {
  model: ["主要对话模型", "gpt-5.6-terra", "Agent 覆盖"],
  prompt: ["提示词模板", "科研主管 v4", "团队策略"],
  tools: ["工具策略", "研究工具集", "团队策略"],
  memory: ["记忆策略", "研究协作记忆", "全局默认"],
  delegation: ["委派与监督", "并发 3 · 深度 2", "Agent 覆盖"],
};

document.querySelectorAll(".config-row").forEach((row) => {
  row.addEventListener("click", () => {
    document.querySelectorAll(".config-row").forEach((item) => item.classList.remove("selected"));
    row.classList.add("selected");
    const [title, value, source] = inspectorCopy[row.dataset.key] || [];
    document.querySelector("#inspector-title").textContent = title;
    document.querySelector(".value-box strong").textContent = value;
    document.querySelector(".inheritance .current strong").textContent = source;
    inspector?.classList.remove("closed");
  });
});

document.querySelectorAll(".agent-row").forEach((row) => {
  row.addEventListener("click", () => {
    document.querySelectorAll(".agent-row").forEach((item) => item.classList.remove("selected"));
    row.classList.add("selected");
    if (row.dataset.agent) document.querySelector("#agent-name").textContent = row.dataset.agent;
  });
});
