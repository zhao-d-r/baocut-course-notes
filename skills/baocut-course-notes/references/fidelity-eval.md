# 保真评测：精度与召回

两个问题，两个指标：

| 指标 | 问题 | 做法 |
|---|---|---|
| 精度 | 笔记写下的东西对不对？ | 评审拿笔记条目对照它引用的原句、画面或外部来源，判断是否有支持 |
| 召回 | 课上讲的东西有没有漏？ | 出题者只看原始转写和画面出题，答题者只看笔记作答 |

评测替代了旧流程里的逐图审计台账、视觉覆盖台账和 review 验收表：那些是作者自己填写的声明，脚本只能检查格式；这里由另一个评审对照原始证据检查最终内容。

## 生产模式：每课轻检，全量用于准入和抽检

全量评测（出题、盲答、判分、正文抽样、看帧）的花费和写一课笔记同量级。实测（GSE 第 08 课，Grok 写、GPT-6.1 Sol 评）：全量评测 5 轮共 11 次评审调用、输入 265 万 token、评测阶段约 20 分钟（全课 42 分钟）；轻检 1 次调用、输入 19.5 万 token、1.2 分钟。生产中改为：

| 档 | 何时 | 内容 | 状态 |
|---|---|---|---|
| 轻检 `prepare --light` | 日常每课 | 只查顶层：每节 takeaway、每张图解、课程地图，对照该节原句；不出召回题、不看帧、不抽正文 | `light_checked` |
| 全量 | 新组合的第一课（准入）、同组合每第 5 课（抽检）、最近一次全量未通过、用户要求、轻检两轮仍不过 | 本文其余部分 | `passed` |

为什么保留顶层：顶层是读者最先看到、压缩最狠的内容，实测的硬失败（结论写反、图解箭头画反）都在这一层；同家族自评一律给 0.99–1.00，不能代替。为什么召回只抽检：在“从原始素材重写”的组合上召回稳定在 0.84–0.96，主要风险是整个组合不行（例如某组合召回 0.42），这由准入和抽检发现。

**组合** = 写作模型（原样字符串）+ skill 版本 + 素材类型（如 `lecture`、`youtube`）。skill 版本用本 skill 的 git 短哈希或发布标签；任一项变化都要重新准入。

**台账** `eval-ledger.json` 放在课程根目录（各 `<视频ID>/<时间>` run 的上两级，如 `Downloads/课堂笔记/eval-ledger.json`）。`score --ledger` 按 run 覆盖写入最新结果，所以改稿后重新打分不会重复记录；批量时由协调者写台账。`mode` 读台账给出本课的档位和理由：

- 没有通过的全量记录 → `full`（准入）。
- 最近一次全量后已有 4 课轻检 → `full`（抽检）。
- 最近一次全量未通过 → `full`，并在 `backfill` 列出上次通过以来只做过轻检的 run：逐个补全量评测，修 skill 后重新准入。

轻检交付必须写明“召回与正文精度未测”，并附该组合最近一次全量评测（`mode` 输出的 `latest_full`）。轻检不能报告为 `passed`。

轻检看不到的：单课漏讲、正文与帧图注的部分支持（实测首轮约 30% 正文条目为 partial）、生成图里清单外的文字。这些由抽检的趋势兜底。

## 角色与独立性

- `reviewer`（精度）、`question_author`、`answerer`（召回）各取 `independent_agent` / `human` / `same_agent`，由 `merge` 根据记录的模型自动判定，不由作者自填。
- 评审必须是**不同家族的模型**、作为独立进程运行（例如 Grok 写、GPT 评）。同家族的子代理与作者共享盲区，对照实验里同模型自评全部给出 0.99–1.00，而外部评委只给召回 0.73–0.86；`merge` 遇到同家族一律记为 `same_agent`。
- 出题者看不到笔记，答题者看不到转写和标准答案（`blind` 自动剥离）。
- 任何一个角色是 `same_agent` 时，结果最多是 `self_checked`，不能报告为 `passed`。

## 用评审包跑外部评测（推荐流程）

```sh
python3 <skill>/scripts/fidelity_eval.py prepare --notes <run>/notes.json --index <run>/chunks/index.json --out <run>/eval
python3 <skill>/scripts/fidelity_eval.py review --notes <run>/notes.json --dir <run>/eval --out <run>/fidelity-eval.json --writer-model <写作模型>
```

`review` 做的就是下面的手工流程：author/ 与 precision/ 并行 → `blind` → answer/ → 出题模型按 author/GRADE.md 判分 → `merge`。评审 CLI 默认选另一家（GPT 写作 → `cursor-agent` + grok-4.7-high；其他 → `codex exec` + gpt-6.1-sol，`--reviewer`/`--reviewer-model` 可改）；每个角色是一个新进程，输出缺失或不是合法 JSON 时重跑一次，仍失败就报错并给出日志路径；各角色耗时和 token 写进 `eval/usage.json`；已有输出的角色不再重跑，所以中断后直接重跑同一条命令。**为什么要做成一条命令**：2026-10-28 的 YouTube 对照里，写作模型自己拼评审命令占了 Codex 42 分钟里的约 32 分钟（绕沙箱、轮询进度、猜文件名），Cursor 那组在 merge 参数上出错，评审 token 也没记下来。

只有 `review` 跑不了时才手工执行（命令见 `<run>/eval/RUN.md`）：

```sh
python3 <skill>/scripts/fidelity_eval.py blind --dir <run>/eval
python3 <skill>/scripts/fidelity_eval.py merge --notes <run>/notes.json --dir <run>/eval --out <run>/fidelity-eval.json \
  --writer-model <写作模型> --reviewer-model <精度评审模型> --author-model <出题模型> --answerer-model <答题模型>
```

- 包是自包含的：`precision/items.json` 只含抽样条目、各节对应的原句和**被抽中条目引用的帧**，评审不必浏览全部帧；`author/transcript.txt` 是带 ID 和时间的全文；`answer/notes.txt` 是带 ref 标签的扁平笔记（图解的 SVG 文字或 `labels` 已展开）。
- 生成的手绘信息图：评审打开图片，逐字核对图中文字与 `labels`，再核对与原句是否一致；图里出现清单外的字或数字记 `distorted`。

## 改了笔记之后：只复核变化的条目

每个精度条目带 `hash`（被评内容的哈希），每道召回题带它 `found_in` 所在小节的哈希（答不出的题绑定全文）。

```sh
python3 <skill>/scripts/fidelity_eval.py stale --notes <run>/notes.json --eval <run>/fidelity-eval.json
python3 <skill>/scripts/fidelity_eval.py prepare ... --out <run>/eval-r2 --only-stale <run>/fidelity-eval.json
python3 <skill>/scripts/fidelity_eval.py review ... --dir <run>/eval-r2 --update <run>/fidelity-eval.json
# review 只跑 eval-r2/precision，并只拿 stale 列出的召回题（沿用原题）重新作答、判分，然后 merge --update
```

评分时若有过期条目，状态为 `stale` 并列出需要复核的 ref/题号；未变的判断继续有效。

## 精度

- **全量**检查顶层：每节 `takeaway`、每张 `visual`、`map`。这些是读者最先看到、压缩最狠的内容，任何一条 `unsupported` 或 `distorted` 都判失败，不论平均分多高。
- **抽样**检查完整笔记：建议每节至少 2 条，优先数字、条件、因果和外部资料结论；写明抽样方法。
- 判定：`supported`（有支持）、`partial`（部分支持或丢了条件）、`unsupported`（找不到依据）、`distorted`（与来源相反或改变了语气，如把“我猜”写成事实）。`evidence` 写对照的原句 ID、时间、页码或链接。
- ref 写法：`s3:takeaway`、`s3:visual`、`map`、`s3:p1`、`s3:e0`、`s3:n0`、`s3:f0`、`x2`、`q4`（自测）、`summary0`。

## 召回

- 出题者通读转写并查看关键帧/讲义，出 ≥ 20 题（默认门槛），覆盖全课时间轴；题目考事实、条件、数字、因果和方法步骤，不考措辞。画面里才有的信息要单独出题（`from: visual`）。
- 每题只问一件事，`expected` 是 1–3 条短要点的列表（每条一个事实，≤160 字符），再写 `evidence`（原句 ID 或帧时间）。判分只看列出的要点，要点之外的细节不扣分。`review` 收到不合规的题会让出题者重写一次。
  **为什么**：2026-10-28 CS329A 第 2 课验收里，Grok 出的题标准答案中位 294 字符、一题 4–6 个事实，漏一个小点就判 partial；同一套 Grok 题给已通过的 Cursor 笔记也只有 0.696，Sol 的题（中位 37 字符）给 0.984——门槛量的是评委而不是笔记。改成短要点后同一 Grok 评委给两份笔记 0.847 / 0.819，与 Sol（0.887 / 0.984）的差距从约 0.3 缩到 0.04–0.16。两个评委对两份笔记的排序仍相反，所以单课召回差 0.1 以内不足以比较写作模型。旧评测（`expected` 为字符串）仍可计分，但与新评测的召回不直接可比。
- 答题者只读 notes.json 或 HTML 作答，并写 `found_in`（在哪节找到）。判定：`correct` / `partial` / `missing`（笔记里没有）/ `wrong`（笔记里的说法与标准答案冲突）。
- `missing` 是遗漏，回到转写补进完整笔记；`wrong` 先查是笔记错还是题目错，再改。

## 文件格式

```json
{
  "schema_version": 1,
  "notes_sha256": "被评测的 notes.json 原始字节 SHA-256",
  "sources": {"transcript_sha256": "...", "visual_inputs": "frames/ 下 311 张候选的联系表 + 课件第69–86页"},
  "precision": {
    "reviewer": "independent_agent",
    "method": "全部 takeaway/图解/地图 + 每节抽 2 条完整笔记",
    "items": [{"ref": "s5:visual", "verdict": "supported", "evidence": "s5:p1 / s-212–s-218", "note": ""}]
  },
  "recall": {
    "question_author": "independent_agent",
    "answerer": "independent_agent",
    "items": [{"id": "q01", "from": "transcript", "question": "讲师的均线组合是哪三条？", "expected": "EMA21、MA50、MA200", "evidence": "s-40", "answer": "EMA21、MA50、MA200", "verdict": "correct", "found_in": "s2"}]
  }
}
```

## 评分与门槛

```sh
python3 <skill>/scripts/fidelity_eval.py score --notes <run>/notes.json --eval <run>/fidelity-eval.json
```

- 精度 = (supported + 0.5×partial) / 条目数；召回 = (correct + 0.5×partial) / 题数。
- 默认门槛：精度 ≥ 0.95，召回 ≥ 0.85，题数 ≥ 20，用了画面时至少一道画面题。可用参数调整，调整理由写进 manifest。
- 带逐条哈希的评测按条目绑定：只有内容变了的条目失效（`stale`）。没有逐条哈希的旧评测仍要求 `notes_sha256` 等于当前 notes。
- 评审本身很贵（外部评委打分的额度消耗可以超过写作）：精度只全量检查顶层，正文按 `--per-section` 抽样；改稿后只复核 stale 条目。
- 未达标：每个失败条目在 manifest 记 issue（问题、证据、修复、复核人），改完后重新评测。

## 它证明不了什么

- 出题者和答题者都没注意到的遗漏，评测发现不了；`source_ids` 全覆盖检查仍是底线。
- 分数复述的是评审的判断，不证明评审读完了全部材料；把方法和输入范围写清楚。
- 可读性不在这两个指标里，靠浏览器检查和读者反馈。
- 轻检只证明顶层与原句一致，不证明没有遗漏。
