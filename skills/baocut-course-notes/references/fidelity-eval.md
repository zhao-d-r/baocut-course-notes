# 保真评测：精度与召回

两个问题，两个指标：

| 指标 | 问题 | 做法 |
|---|---|---|
| 精度 | 笔记写下的东西对不对？ | 评审拿笔记条目对照它引用的原句、画面或外部来源，判断是否有支持 |
| 召回 | 课上讲的东西有没有漏？ | 出题者只看原始转写和画面出题，答题者只看笔记作答 |

评测替代了旧流程里的逐图审计台账、视觉覆盖台账和 review 验收表：那些是作者自己填写的声明，脚本只能检查格式；这里由另一个评审对照原始证据检查最终内容。

## 角色与独立性

- `reviewer`（精度）、`question_author`、`answerer`（召回）各取 `independent_agent` / `human` / `same_agent`，由 `merge` 根据记录的模型自动判定，不由作者自填。
- 评审必须是**不同家族的模型**、作为独立进程运行（例如 Grok 写、GPT 评）。同家族的子代理与作者共享盲区，对照实验里同模型自评全部给出 0.99–1.00，而外部评委只给召回 0.73–0.86；`merge` 遇到同家族一律记为 `same_agent`。
- 出题者看不到笔记，答题者看不到转写和标准答案（`blind` 自动剥离）。
- 任何一个角色是 `same_agent` 时，结果最多是 `self_checked`，不能报告为 `passed`。

## 用评审包跑外部评测（推荐流程）

```sh
python3 <skill>/scripts/fidelity_eval.py prepare --notes <run>/notes.json --index <run>/chunks/index.json --out <run>/eval
# 按 <run>/eval/RUN.md 用另一家模型分别运行 author/ 与 precision/ 包（可并行）
python3 <skill>/scripts/fidelity_eval.py blind --dir <run>/eval
# 运行 answer/ 包；再让出题模型按 author/GRADE.md 判分
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
# 只跑 eval-r2/precision，并只对 stale 列出的召回题重新作答、判分
python3 <skill>/scripts/fidelity_eval.py merge ... --dir <run>/eval-r2 --update <run>/fidelity-eval.json
```

评分时若有过期条目，状态为 `stale` 并列出需要复核的 ref/题号；未变的判断继续有效。

## 精度

- **全量**检查顶层：每节 `takeaway`、每张 `visual`、`map`。这些是读者最先看到、压缩最狠的内容，任何一条 `unsupported` 或 `distorted` 都判失败，不论平均分多高。
- **抽样**检查完整笔记：建议每节至少 2 条，优先数字、条件、因果和外部资料结论；写明抽样方法。
- 判定：`supported`（有支持）、`partial`（部分支持或丢了条件）、`unsupported`（找不到依据）、`distorted`（与来源相反或改变了语气，如把“我猜”写成事实）。`evidence` 写对照的原句 ID、时间、页码或链接。
- ref 写法：`s3:takeaway`、`s3:visual`、`map`、`s3:p1`、`s3:e0`、`s3:n0`、`s3:f0`、`x2`、`q4`（自测）、`summary0`。

## 召回

- 出题者通读转写并查看关键帧/讲义，出 ≥ 20 题（默认门槛），覆盖全课时间轴；题目考事实、条件、数字、因果和方法步骤，不考措辞。画面里才有的信息要单独出题（`from: visual`）。
- 每题写 `expected`（标准答案）和 `evidence`（原句 ID 或帧时间）。
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
