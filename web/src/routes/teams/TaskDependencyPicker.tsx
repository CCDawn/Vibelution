import { useId, useState } from "react";
import type { DevTeamTask } from "../../api/devTeamTasks";
import { VCheckbox, VNativeButton, VNativeInput, VPopover } from "../../components/vui";

import { taskDependencyPickerStyles as styles } from "./TaskDependencyPicker.styles";

const STATUS_LABELS: Record<string, { zh: string; en: string }> = {
  pending: { zh: "待办", en: "Pending" },
  in_progress: { zh: "进行中", en: "In progress" },
  rework: { zh: "退回", en: "Rework" },
  completed: { zh: "完成", en: "Done" },
};

function selectedIds(value: string) {
  return Array.from(new Set(value.split(/[\n,，]/).map((id) => id.trim()).filter(Boolean)));
}

export function TaskDependencyPicker({ lang, label, tasks, currentTaskId, value, onChange }: {
  lang: "zh" | "en";
  label: string;
  tasks: DevTeamTask[];
  currentTaskId?: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const labelId = useId();
  const text = (zh: string, en: string) => lang === "zh" ? zh : en;
  const ids = selectedIds(value);
  const query = search.trim().toLocaleLowerCase();
  const candidates = tasks.filter((task) => task.id !== currentTaskId);
  const taskStatus = (task: DevTeamTask) => STATUS_LABELS[task.status]?.[lang] || task.status;
  const matches = candidates.filter((task) => !query || [task.id, task.subject, task.status, taskStatus(task)].join(" ").toLocaleLowerCase().includes(query));
  const changeSelection = (id: string, checked: boolean) => {
    onChange((checked ? Array.from(new Set([...ids, id])) : ids.filter((item) => item !== id)).join(", "));
  };

  return (
    <div className={styles.field}>
      <span id={labelId}>{label}</span>
      <div className={styles.controls}>
        <VPopover
          open={open}
          onOpenChange={(next) => { setOpen(next); if (!next) setSearch(""); }}
          aria-label={label}
          contentClassName={styles.popover}
          trigger={<VNativeButton type="button" className={styles.trigger} aria-label={label} aria-labelledby={labelId}>
            <span>{ids.length ? text(`已选择 ${ids.length} 个依赖`, `${ids.length} dependencies selected`) : text("搜索并选择依赖任务", "Search and select dependencies")}</span>
            <span aria-hidden="true">⌄</span>
          </VNativeButton>}
        >
          <div className={styles.search}>
            <VNativeInput
              aria-label={text("搜索依赖任务", "Search dependencies")}
              placeholder={text("搜索编号、标题或状态", "Search ID, title, or status")}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <span role="status">{text(`${matches.length} 个可选任务`, `${matches.length} matching tasks`)}</span>
          </div>
          <div className={styles.options} aria-label={text("可选依赖任务", "Available dependencies")}>
            {matches.map((task) => <VCheckbox
              key={task.id}
              className={styles.option}
              isSelected={ids.includes(task.id)}
              onChange={(checked) => changeSelection(task.id, checked)}
              aria-label={`${task.id} · ${task.subject} · ${taskStatus(task)}`}
            >
              <span className={styles.optionLabel}>
                <span>{task.subject}</span>
                <small><span className={styles.id}>{task.id}</span> · {taskStatus(task)}</small>
              </span>
            </VCheckbox>)}
            {matches.length === 0 ? <p className={styles.empty}>{candidates.length ? text("没有匹配的任务，试试其他关键词。", "No matching tasks. Try another search.") : text("暂无可选的依赖任务。", "No dependency tasks are available.")}</p> : null}
          </div>
          <div className={styles.footer}>
            <VNativeButton type="button" disabled={ids.length === 0} onClick={() => onChange("")}>{text("清除选择", "Clear selection")}</VNativeButton>
            <VNativeButton type="button" onClick={() => setOpen(false)}>{text("完成选择", "Done")}</VNativeButton>
          </div>
        </VPopover>
        {ids.length > 0 ? <VNativeButton className={styles.clear} type="button" aria-label={text(`清除${label}`, `Clear ${label}`)} onClick={() => onChange("")}>{text("清除", "Clear")}</VNativeButton> : null}
      </div>
      {ids.length > 0 ? <div className={styles.selected} aria-label={text("已选择的依赖", "Selected dependencies")}>
        {ids.map((id) => {
          const task = tasks.find((item) => item.id === id);
          return <div className={styles.selectedRow} key={id}>
            <span><span className={styles.id}>{id}</span> · {task?.subject || text("任务未在当前列表中", "Task unavailable")}{task ? ` · ${taskStatus(task)}` : ""}</span>
            <VNativeButton type="button" aria-label={text(`移除依赖 ${id}`, `Remove dependency ${id}`)} onClick={() => changeSelection(id, false)}>×</VNativeButton>
          </div>;
        })}
      </div> : null}
    </div>
  );
}
