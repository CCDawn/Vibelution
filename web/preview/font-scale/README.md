# 单一字号派生字阶预览（font-scale）

隔离预览页：验证「单一基准变量 + 固定偏移派生全套主字阶」机制（ZCode FontSizeInput
模式）。只做预览，不改生产代码；生产集成待用户批准后由后续任务执行。

## 看什么

- 同一页面在 base=14/15/16/17/18 下的真实渲染对比（生产 VUI 组件 + 生产令牌）。
- 固定例外对照：工作流画布子阶梯（`--vui-font-canvas-*`，9–15px）、桌宠
  （`--vui-pet-*`，固定 px）、xterm 终端（13px）不随基准缩放。
- A/B 对拍：`?mode=ab` 左右分栏同屏 16px vs 当前所选。
- 底部如实标注派生式为本地副本与钳制范围（14–18px）。

## 深链

`http://127.0.0.1:5247/preview/font-scale/index.html?base=14|16|17|18[&mode=ab][&theme=dark|light]`

## 机制

`src/fontScaleTokens.css` 在 `:root` 把主字阶 12 档改写为
`calc(var(--vui-font-base) ± Npx)`（md = 基准本身），base=16 时与生产
`src/design/tokens.css` 的 rem 现值逐档零漂移；其余令牌（颜色/圆角/行高/字重）
照抄生产。偏移表：micro-9=−7 … xs=−2、sm=−1、md=0、chat=+1、lg=+2、title=+3、
xl=+6（例外刻度）。

A/B 分栏用 `.font-scale-scope` 整梯重声明：custom property 的
`calc(var(--vui-font-base))` 在声明元素处求值，后代内联改 base 不会重算
`:root` 已解析的档位，因此每个分栏元素要在本元素上重声明整条梯。

## 命令

```
npm run dev       # 等价：vite --config vite.config.ts（端口 5247，root=web/）
npm run selftest  # 逻辑自测（162 断言：派生公式×base14–18、钳制、例外不变）
npm run capture   # playwright 6 张截图 + 45 条断言 + capture-report.json
```

截图不入库（`screenshots/.gitignore`），仅 `capture-report.json` 入库。

## 边界

- 只读引用 `web/src` 的 VUI 组件与设计样式；不进生产路由/构建/tsconfig/vitest。
- 独立 vite 配置与端口（5247），独立 tsconfig；生产 `tsc -b` 不扫描本目录。
