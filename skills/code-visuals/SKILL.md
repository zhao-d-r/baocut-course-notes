---
name: code-visuals
description: 让只会输出文字的模型（Claude、Gemini、GPT 等）也能"画"出好读的教学信息图：模型写 AntV Infographic 语法或一页 HTML+rough.js 手绘代码，本地无头 Chrome 渲染成 PNG，并自动检查图上文字只来自给定清单、不出界、不重叠。用于没有生图工具、生图额度用完、或需要文字一个不错的场合；课程笔记的图解、知识点对比、流程、层级、时间线、循环都适用。
---

# code-visuals：文字模型的生图备选方案

图片不是模型画的，而是模型写"画法"，再由浏览器渲染：

- 不占任何生图额度；
- 图上的字由浏览器排版，不会写错字；
- 改一个字重新出图只要几秒。

代价是没有生图模型那种插画感：没有小人和复杂场景，只有卡片、图标、箭头和手绘线条。

## 先准备文字清单

先把图上允许出现的全部文字写成一个 JSON 数组：短语，不写句子，6–14 条，逐字取自原文。数字也要照抄，不能自己算。存成 `labels.json`。渲染时会逐段核对：清单外的字（序号 1–20、①②、VS、箭头等装饰除外）一律报错。

## 选引擎

| 内容形状 | 用哪个 | 写什么 |
|---|---|---|
| 步骤、时间线、循环、并列要点、因果流程、层级、四象限、柱状图 | **AntV**（带图标；只用 references/antv.md 里列出的 21 个可用模板） | `.infographic` 文本 |
| 两方对比、课程地图、自由版面、需要特定示意（一排 token、增长的柱子） | **手绘页**（rough.js） | 一页 HTML，从 `assets/freeform.html` 复制改写 |

## 渲染与检查

```bash
python3 <skill>/scripts/render.py antv --dsl s3.infographic --labels-json labels.json --out raw-s3.png
python3 <skill>/scripts/render.py page --html draw-s3.html  --labels-json labels.json --out raw-s3.png
```

- **默认画布**：AntV 800×1200，按 2 倍像素输出；手绘页 1024×1536，横版用 `--width 1536 --height 1024`。渲染完会按内容自动裁掉留白。
- **输出**：一段 JSON。
  - `problems` 非空时退出码为 1，改源文件重跑，直到 `"problems": []`。可能的问题：
    - 清单外的字
    - 文字超出画布
    - 文字互相重叠
    - 手绘线穿过文字
    - 字太小：字号小于内容宽度的 2%，图片按页面宽度显示时，在手机上会小到看不清
  - `warnings` 只是提醒：字偏小、清单里有条目没用上。
- **最后用眼睛看一遍 PNG**：检查只管字，不管意思。箭头和分组有没有画出原文没有的因果，要自己看。

## AntV 要点（详见 references/antv.md）

- **只用 `references/antv.md` 列出的可用模板**。其余模板要么会自己加清单外的字（饼图百分比、Pros/Cons），要么横向铺开、字在手机上太小，检查都会拦下。
- **手绘风格**：`theme` 下写 `stylize rough`。不要改字号，模板按默认字号排版，改了会重叠。
- **`icon` 只写通用英文关键词**（如 `database`、`timer`、`users`），不要写课程原文。图标按关键词从 AntV 的在线图标服务取，离线时图标会缺失，但文字照常显示。
- **控制条目数**：每项 `label` 尽量短，一张图 3–6 项。条目太多时字会被缩得很小。

## 手绘页要点

- 文字用 CSS 排版，一个短语一个元素。
- 在 `window.paint = (k) => { ... }` 里围绕文字画：
  - `k.box`：框
  - `k.arrow`：箭头
  - `k.banner`：底部横幅
  - `k.underline`：下划线
  - `k.square`、`k.circle`、`k.line`：小图形
  - 原始 rough.js 在 `k.rc`
- 小图标画在预留的空 `.doodle` 元素里，用 `k.rect('#id')` 取位置，不要压在字上。
- 相邻两个框之间留够距离：间距要大于两边框的内边距加上箭头长度。模板里的 `gap:110px` 是一个可用的值。

## 依赖

- 需要本机 Chrome 或 Chromium，找不到时设置 `CHROME=/path`。裁剪需要 ffmpeg，没有时输出不裁剪的原图。
- rough.js 4.6.6（MIT）和 @antv/infographic 0.2.20（MIT）已放在 `assets/`，不需要 npm。
- 标题手写字体从 Google Fonts 加载，离线时退回系统黑体。
