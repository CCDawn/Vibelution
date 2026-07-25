const activityItems = [...document.querySelectorAll(".activity-item")];
const toast = document.querySelector(".toast");
let toastTimer = 0;

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 1600);
}

document.querySelector('[data-action="collapse-all"]').addEventListener("click", () => {
  activityItems.forEach((item) => {
    item.open = false;
  });
});

document.querySelector('[data-action="expand-all"]').addEventListener("click", () => {
  activityItems.forEach((item) => {
    item.open = true;
  });
});

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    if (!target) return;

    try {
      await navigator.clipboard.writeText(target.textContent.trim());
      showToast("已复制工具结果");
    } catch {
      showToast("当前预览环境不支持剪贴板");
    }
  });
});
