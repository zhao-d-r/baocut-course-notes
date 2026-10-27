# 可追溯运行：一个 manifest.json

目标不变：能回答“这句话依据什么、为什么复用、哪里返工、交付的是哪一版”。变化是把原来分散在五个文件里的记录合进 run 目录下的一个 `manifest.json`，由 `scripts/manifest.py` 追加和核对。

## 旧文件去哪了

| 旧文件 | 记录什么 | 现在在哪 | 保留的保证 |
|---|---|---|---|
| `run.json` | run_id、视频、范围、范围变更 | `run_id`、`item`、`scope` | 同字段 |
| `trace-spec.json` | 文件及 depends_on | `artifacts[]` | 同样检查 ID 唯一、依赖存在、无环 |
| `trace-rNN.json` | 每版文件 SHA-256/字节 | `revisions[].files` | 只追加；每版带上一版的哈希（`prev_sha256`），任何改写或删版都会被 `check` 发现 |
| `events.jsonl` | 阶段、状态、尝试、job、证据、时间 | `log[]` | 同字段；`at` 为记录时间，`occurred_at` 为声明的发生时间，未知留 null |
| `review.json` | 结局、验收状态、阻塞、指标 | `status` + `revisions[].eval` | 验收改由冻结时绑定的保真评测给出 |
| `audit.json` 的 issues | 问题与修复历史 | `issues[]` | issue 只能改状态不能删除；修复必须写 `fix` 和 `verified_by`；未解决的高严重度问题阻止以 completed 交付 |

旧 run 的文件不迁移、不改写。它们的 `trace-rNN.json` 仍可用 `scripts/trace_artifacts.py check --snapshot <file>` 只读核对。

## 格式

```json
{
  "schema_version": 1,
  "run_id": "VIDEO-20261027T0300Z",
  "item": {"video_id": "VIDEO", "source_url": "https://...", "title": "第3课"},
  "scope": {"requested": "单课完整笔记 + 图解", "materials": false,
            "changes": [{"at": "2026-10-27T03:40Z", "request": "加读推荐论文", "added_work": "materials.json + supplements"}]},
  "toolchain": {"baocut": "2.1.0 build 54", "asr_model": null, "skill_commit": "git 提交号或 null"},
  "artifacts": [
    {"id": "transcript", "path": "transcript.json", "depends_on": [], "role": "source", "origin": "reused", "basis": "同一视频ID的 fresh 导出"},
    {"id": "index", "path": "chunks/index.json", "depends_on": ["transcript"]},
    {"id": "frames", "path": "frames/index.json", "depends_on": [], "role": "source", "origin": "generated"},
    {"id": "notes", "path": "notes.json", "depends_on": ["index", "frames"]},
    {"id": "renderer", "path": "/abs/skill/scripts/layered.py", "depends_on": [], "role": "tool"},
    {"id": "html", "path": "课堂笔记.html", "depends_on": ["notes", "renderer"]},
    {"id": "fidelity_eval", "path": "fidelity-eval.json", "depends_on": ["notes", "transcript", "frames"]}
  ],
  "log": [{"at": "...", "occurred_at": "...", "stage": "asr", "status": "reused", "attempt": null, "job_id": null, "detail": "复用已有转写", "evidence": "transcript.json"}],
  "issues": [{"id": "i-001", "severity": "high", "location": "s5:p0 / s-212", "problem": "3σ 写成 2σ", "evidence": "s-214 原句", "fix": "改为 3σ 并重画 s05.svg", "verified_by": "independent_agent", "status": "fixed"}],
  "status": {"outcome": "partial", "known_gaps": ["真实手机未测"], "browser_check": "桌面1280与手机390宽实际查看，见 qa/"},
  "revisions": []
}
```

- `artifacts` 要列出 notes 真正用到的输入：转写、合并后的索引、选用图片的清单、图解目录的清单、推荐材料、渲染脚本和模板、HTML、评测。依赖是声明，不是执行证明；漏列的文件 `check` 无法发现。
- 图片很多时，列一个清单文件（如 `frames/index.json`，含每张图的 SHA-256），不必逐张列为 artifact。
- 不写 Cookie、令牌、带签名的下载链接或完整环境变量。

## 命令

```sh
# 阶段开始/结束/复用/失败都追加一条
python3 <skill>/scripts/manifest.py log --run <run> --stage asr --status started --attempt asr-01 --job-id <实际job> --evidence logs/asr.jsonl
# 冻结一个版本（每次修复或交付）
python3 <skill>/scripts/manifest.py freeze --run <run> --reason "修复 i-001 后重新评测" [--delivered]
# 交付前或恢复任务时检查是否有文件在冻结后变化
python3 <skill>/scripts/manifest.py check --run <run> [--root <搬迁后的目录>]
```

- 重试另起 `attempt`；轮询同一后台 job 不算重试。paused 不是 failed；reused 表示复用证据，不是本次重跑。CLI 返回不等于后台作业完成。
- `freeze` 计算全部 artifact 的 SHA-256，追加一版并链接上一版。若有 `fidelity_eval`，它必须绑定当前 notes，否则拒绝；评分结果写进这一版。`--delivered` 要求已有评测和 `status.outcome`，且没有未解决的高严重度 issue 时才能以 completed 交付。
- `check` 先验证版本链没被改写，再比较当前文件与最新版本：`changed_files` 是直接变化，`unavailable_files` 是缺失，`requires_revalidation` 是依赖它们的下游。退出码：0 未变，2 有变化，1 格式错误。
- 修改转写、图片、notes 或模板后：先 `check` 找出受影响范围 → 重新生成和评测 → 再 `freeze`。不能只重新冻结来消除变化提示，也不能删除旧版本。

## 时间与用量

`at` 是写入日志的 UTC 时间；`occurred_at` 是声明的实际发生时间，事后补录且不知道就留 null，知道就带时区并在 evidence 引用原始日志。没有可靠来源的耗时、token 和费用一律 null，不由文本长度或帧数估算。并行时代理数量不等于后台实际并发。

## 复核独立性

作者自查、同一代理二次检查、另一代理或人工检查分别标注（`same_agent` / `independent_agent` / `human`），不统称“独立复核”。
