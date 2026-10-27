# 数据合同 v3

`notes.json` 是一课的唯一事实源：完整笔记、来源归属和阅读布局都在这一个文件里，不再有需要用哈希绑定的独立布局文件。脚本不生成语义内容，所有文字按纯文本转义。

- 起步用 `course_notes.py scaffold` 生成绑定分块的骨架（不要从零手写或另写生成器）；`TODO(scaffold)` 占位会被校验拒绝，`read_chunks` 必须由读过转写的人或代理填写。
- 写完用 `course_notes.py validate` 一次拿到全部问题，每条带字段路径（如 `sections[14].visual`、`sections[3].source_ids`）；不必读脚本源码猜规则。下面的示例和 `examples/synthetic`、`scripts/test_layered.py` 中的 `v3_notes()` 都是能通过校验的完整样例。
- `visual` 可以是 SVG，也可以是生成的 PNG/JPEG/WebP 信息图；位图必须带 `labels`：图中出现的全部文字，逐条列出，例如 `{"path": "visuals/s01.jpg", "alt": "…", "refs": ["p0"], "labels": ["断网以后", "设计重试"]}`。

```json
{
  "schema_version": 3,
  "title": "麦田美股交易 · 第3课：策略、技术指标与时间框架",
  "course_title": "课程名", "issue": "第3课 / 5",
  "heading": "页面主标题", "subtitle": "这一课解决什么问题",
  "source_url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "limitations": ["完整阅读14个转写块；画面为1fps换页检测+15秒兜底，非逐秒观看"],
  "read_chunks": ["chunk-0001"],
  "omitted": [{"id": "s-9", "reason": "调试麦克风，无教学内容"}],
  "map": {"path": "visuals/map.svg", "alt": "本课论证链", "caption": "按各节关键判断绘制"},
  "summary": ["本课主线一句话"], "summary_terms": ["主线"],
  "groups": [{"start": 1, "label": "一 / 指标与图形"}],
  "sections": [{
    "title": "实际主题", "short": "目录短标题",
    "takeaway": "本节一句话结论（整理者提炼）",
    "start": 0, "end": 300, "source_ids": ["s-1", "s-2"],
    "terms": ["正文中的准确短语"],
    "flow": "p0 f0 p1 n0 x0",
    "visual": {"path": "visuals/s01.svg", "alt": "图解的文字描述", "refs": ["p0", "p1"]},
    "paragraphs": ["讲师的论证、条件与边界。", {"text": "讲师的经验判断。", "caveat": "未给样本或失败率"}],
    "examples": ["课堂案例、代码与演示细节。"],
    "editor_notes": ["整理者说明：口径差异、ASR 校正等。"],
    "frames": [
      {"source_type": "video_frame", "path": "frames/120.png", "time": 120, "caption": "视频此秒显示的内容"},
      {"source_type": "pdf_page", "path": "frames/slide-03.png", "source_label": "官方课程讲义", "page": 3, "related_time": 125, "caption": "讲义内容"}
    ]
  }],
  "bridges": {"x0": "说明这份补充怎样回答本节的问题（整理者衔接）"},
  "supplements": [{"title": "外部补充", "text": "补充正文", "source_label": "TradingView官方帮助；编者补充", "source_url": "https://example.org", "pages": [3]}],
  "self_test": [{"question": "复习问题", "answer": "有证据支持的答案", "section": 1}]
}
```

## 来源归属

| 字段 | 页面标签 | 放什么 |
|---|---|---|
| `paragraphs` | 课堂（默认，不加标签） | 讲师讲述的论证、条件、数字、语气 |
| `examples` | 课堂案例 | 课堂上的案例、代码、演示 |
| `editor_notes` | 整理者说明 | 口径差异、ASR 校正、图表核对、术语边界 |
| `supplements` | 外部资料 | 课外核对或推荐阅读，必须有 `source_label` |
| `takeaway`、`visual`、`map` | 整理者 / 整理者图解 | 只重组已有事实的提炼与图解 |

- 内容条目可以是字符串，或 `{"text", "caveat"}`。`caveat` 写这一条的限制（“讲师个人经验，未给样本”），渲染为条目下方的小字。用它替代正文里的重复免责句，但不能用它删除讲师原话中的不确定语气。
- 讲师说“我猜/据说/我的经验”时，正文照实写；外部资料的结论不写进 `paragraphs`。

## 覆盖与布局

- `source_ids` 来自 `chunks/index.json`，每句恰好归属一节或进入 `omitted`（附理由）。重复、遗漏、同时引用和省略都报错。`read_chunks` 只能在真读完后填写。
- 时间单位为秒，节区间包含它引用的原句和视频帧。
- `flow` 决定完整笔记里的展示顺序，token 为 `pN`/`eN`/`nN`/`fN`（本节，零基）、`fS:N`（第 S 节的讲义图，一基节号）、`xN`（全局 supplements）。省略 `flow` 时按 p→e→n→f 顺序。每个单位在全文恰好出现一次；没有放进任何节的 supplement 会出现在文末“延伸资料”，不会丢失。视频帧不能跨节。
- `terms` 必须在本节完整笔记的文字中精确出现；每个文本块最多强调两个。
- `bridges` 的键只能是已有的 `xN`，渲染为“整理者衔接”，只连接已有论证，不加新事实。
- `visual.refs` 必须是本节 `flow` 里的 token，渲染为“依据完整笔记第 N 条”的链接。

## 图片

- 原帧和讲义图：run 目录内的 PNG/JPEG/WebP，必须有 caption。`video_frame.time` 是实际截帧秒数，落在节区间内；`pdf_page` 必填 `source_label` 和物理页 `page`，不写 `time`，`related_time` 只作讲解导航。印刷页号写在 caption，不覆盖 `page`。
- 图解：run 目录内的 `.svg`，必须有 `alt`。以 `<img>` 内嵌，SVG 里的脚本与外链不会执行。
- 没有值得放的画面可以 `frames: []`，不为凑数插图。

## 运行目录

保留原始导出、`chunks/`、`notes.json`、`frames/`、`visuals/`、`课堂笔记.html`、`fidelity-eval.json`、`manifest.json`。来源、依赖、阶段日志、问题与修复、交付版本都写在 manifest（见 [可追溯运行](traceability.md)）。

## 兼容 v2

`schema_version` 为 2（或省略）时仍按旧合同加 `reading-layout.json` 渲染，用于已交付的旧课。v2 迁移到 v3：把布局文件每节的 `short`/`takeaway`/`terms`/`flow` 和顶层 `course_title`/`issue`/`title`→`heading`/`subtitle`/`summary_title`/`summary_terms`/`groups`/`bridges` 移入 notes，删除 `notes_sha256`；正文内容不改。
