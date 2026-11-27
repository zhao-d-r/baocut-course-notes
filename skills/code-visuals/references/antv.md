# AntV Infographic 语法速查（code-visuals 用）

摘自 AntV 官方 skill `infographic-creator`（github.com/antvis/Infographic，MIT），按本 skill 的检查结果删掉了会自带文字的模板。完整文档：https://infographic.antv.vision/learn/infographic-syntax

## 硬性规则

- 第一行 `infographic <模板名>`；之后是 `data` 块和可选的 `theme` 块，块内一律两个空格缩进。
- 键值对写成 `键 空格 值`；数组条目用 `- ` 开头。
- `data` 里写 `title`（图标题）、可选 `desc`（副标题），再加一个与模板匹配的主字段：
  - `list-*` → `lists`
  - `sequence-*` → `sequences`
  - `sequence-interaction-*` → `sequences` + `relations`
  - `compare-binary-*` / `compare-hierarchy-*` → `compares`，恰好两个根节点，各自带 `children`
  - `compare-quadrant-*` → `compares`，4 个根节点
  - `hierarchy-structure` → `items`
  - 其他 `hierarchy-*` → 单个 `root` 加递归 `children`
  - `relation-*` → `nodes` + `relations`（如 `a - 标签 -> b`，`a -> b`）
  - `chart-*` → `values`（每项写 `label` 和 `value`）
- 每个条目可带 `label`、`desc`、`value`、`icon`。`label`、`desc`、`title` 里出现的每段文字都必须在 labels.json 里，`value` 也会显示出来，数字同样要在清单里。
- `icon` 写英文语义关键词，多个词用空格分隔（`chart line`，不要写 `chart-line`）。
- 手绘：`theme` 块写 `stylize rough`。配色：`palette #2a62a8 #3c8a5a #c0621b`（裸色值，不加引号和逗号）。不要改字号。

## 示例

```
infographic sequence-snake-steps-simple
data
  title 一次请求的生命周期
  desc 先 prefill 再 decode
  sequences
    - label 读入 prompt
      icon file text
    - label prefill
      icon layers
    - label decode
      icon repeat
    - label 输出 token
      icon send
theme
  stylize rough
```

```
infographic list-column-vertical-icon-arrow
data
  title context engineering
  desc 不能全塞进去
  lists
    - label system prompt
      icon settings
    - label message history
      icon message
    - label tool call results
      icon tool
    - label attached files
      icon file
theme
  stylize rough
```

```
infographic relation-dagre-flow-tb-badge-card
data
  title 检索增强
  nodes
    - id q
      label 问题
    - id r
      label 检索
    - id a
      label 回答
  relations
    q -> r
    r - 相关段落 -> a
```

## 模板选择

只用下面"可用模板"里的。

- 步骤、阶段 → `sequence-snake-steps-simple`、`sequence-stairs-front-pill-badge`、`sequence-roadmap-vertical-simple`
- 时间线 → `sequence-timeline-simple`
- 循环 → `sequence-circular-simple`
- 并列要点 → `list-column-vertical-icon-arrow`、`list-column-simple-vertical-arrow`、`list-column-done-list`
- 因果、依赖、流程分支 → `relation-dagre-flow-tb-*`（`nodes` + `relations`）
- 层级、分类 → `hierarchy-structure`、`hierarchy-tree-tech-style-capsule-item`
- 四象限 → `compare-quadrant-quarter-circular`
- 柱状图 → `chart-column-simple`（数值必须来自原文）
- 两方对比、课程地图、其他自由版面 → 不用 AntV，改用手绘页（`assets/freeform.html`，它的示例就是一张对比图）

## 可用模板

2026-11-27 用 @antv/infographic 0.2.20、4 个条目、标题和副标题逐个渲染，通过了全部检查（文字核对、不重叠、手机可读）：

- chart-column-simple
- compare-quadrant-quarter-circular
- hierarchy-structure
- hierarchy-tree-tech-style-capsule-item
- list-column-done-list
- list-column-simple-vertical-arrow
- list-column-vertical-icon-arrow
- relation-dagre-flow-tb-animated-badge-card
- relation-dagre-flow-tb-animated-simple-circle-node
- relation-dagre-flow-tb-badge-card
- relation-dagre-flow-tb-simple-circle-node
- sequence-circular-simple
- sequence-cylinders-3d-simple
- sequence-roadmap-vertical-plain-text
- sequence-roadmap-vertical-simple
- sequence-snake-steps-simple
- sequence-snake-steps-underline-text
- sequence-stairs-front-pill-badge
- sequence-timeline-simple
- sequence-zigzag-pucks-3d-simple

其他模板不要用：
- 横向铺开的（`list-row-*`、`list-grid-*`、`list-zigzag-*`、横向 `sequence-*`、`hierarchy-tree-curved-*` 等）字太小，检查会报 "text too small"；
- 饼图会自动算百分比；
- `compare-binary-*` 会塞 Pros/Cons；
- `compare-swot` 会塞单字；
- `sequence-ascending-stairs-3d-underline-text` 编号重叠；
- `chart-wordcloud` 不适合教学图。

条目越多字越小：一张图 3–6 项为宜，超过就拆成两张或改用手绘页。
