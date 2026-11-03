# Native scroll region

## VScrollRegion

### 功能
统一原生纵向滚动区域的暂显滚动条：使用主会话目录已有的 6px 透明轨道与主题色圆角滑块，用户滚动时显示，停止操作 800ms 后隐藏。

### 适用范围
- Launcher 导航列表、主会话目录与共享 `ConversationView` 时间线等需要同一滚动条规则的区域。
- 需要直接读取 `scrollTop`、绑定 virtualizer 或保留既有 follow 逻辑的单层原生滚动宿主。
- 页面壳仍由 page recipe 提供；仅需表面外观时使用 `VSurface`，横向滚动或自定义滚动轨道不属于本组件。

### 使用方式
```tsx
import { VScrollRegion } from "@/components/vui";

<VScrollRegion ref={scrollRef} className="h-full" tabIndex={0} aria-label="会话列表" onScroll={handleScroll}>
  {items}
</VScrollRegion>
```

| Prop / 接口 | 说明 |
| --- | --- |
| 原生 `div` props | 保留 `children`、`role`、`tabIndex`、ARIA、事件与 `style`；不自动改写语义 |
| `ref` | 直接指向唯一实际滚动 `HTMLDivElement`，无额外滚动层 |
| `className` | 调用方负责高度、宽度、间距等业务几何；默认只提供 `min-h/w-0`、纵向 auto、横向 hidden 与 stable gutter |
| `onWheel` / `onTouchMove` / `onKeyDown` / `onPointerDown` / `onScroll` | 原回调继续执行，不阻止默认滚动，不改 `scrollTop` |
| `data-scroll-active` / `data-scroll-dragging` | 标识暂显及原生滑块拖动状态，供状态验收使用 |

### 视觉与状态
- idle：轨道与滑块透明；gutter 保持占位，显示状态不改变布局。
- 用户 wheel、touchmove 或滚动键：滑块以 `--fg-secondary` 的 28% 混色显示，最后一次操作 800ms 后隐藏；可编辑控件内按键不触发。
- 鼠标主键在真实纵向 gutter 内按下：持续显示到 window `pointerup`、`pointercancel` 或失焦，随后再延迟 800ms 隐藏；按住超过 800ms 也不隐藏，兼容左侧 RTL gutter。
- Chromium 原生滑块拖动可能不派发 DOM pointer 事件；`::-webkit-scrollbar-thumb:active` 直接提供相同主题色作为原生拖动保障，此时随原生 active 结束隐藏。
- 程序触发的 `scroll`（包括流式自动 follow）只透传事件，不触发或延长显示。
- Chromium 使用 6px WebKit 伪元素样式并隐藏原生箭头，`!important` 只用于覆盖全局 native scrollbar reset；仅不支持 WebKit 伪元素的浏览器使用标准 `scrollbar-width: thin` fallback。
- 沿用滑块 150ms 颜色过渡，减少动态效果偏好下关闭过渡。

### 非职责
- 不负责页面布局、自动跟随、恢复位置、虚拟化、滚动持久化或额外焦点管理。

### 实现落点
- 公共 API：`primitives/VScrollRegion.tsx`
- 单层原生宿主及输入状态：`renderers/shadcn/ShadcnScrollRegion.tsx`
- 既有视觉规则：`renderers/shadcn/ShadcnScrollRegion.styles.ts`

### 反冗余
- 从 `ChatConversationIndexRail` 的现有规则提取，Launcher 导航及共享会话时间线使用同一 API；各消费者只保留自身几何。
- `VSurface`、`VPanel` 负责表面语义，不增加另一套滚动条；不引入额外 ScrollArea、第二个滚动 DOM 或产品私有 timer。
