# Product — Team management

> 科研/资料搜集等团队域组合件。
> 阶段卡、结果列表等 **不是** 通用 kanban；通用壳用 Board recipe。

## TeamStageCard

### 职责
阶段卡片展示（tone + 内容）。

### 反冗余
- 总览看板列用 `ResearchBoardKanban`；本卡用于阶段 pipeline 语义

---

## TeamStageCommandBar

### 职责
阶段命令/统计条。

---

## TeamStagePipeline

### 职责
阶段流水线布局容器。

---

## TeamSourceFilterBar

### 职责
资料结果过滤条。

---

## TeamSourcePagination

### 职责
资料列表分页控件。

---

## TeamSourceResultList

### 职责
资料结果列表（含 `TeamSourceResultItem`）。

### 反冗余
- Item 不单独导出为第二列表体系

---

## TeamSourceResultStats

### 职责
结果统计条。

---

## TeamSourceEmptyState

### 职责
资料空态（可带 facts）。

### 反冗余
- 通用空态用 `VEmptyState`；本组件带领域 facts 结构

---

## TeamCandidateCard

### 职责
候选卡片。
