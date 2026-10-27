# 推荐材料与论文：把阅读变成课堂笔记的增量

适用于课程官网、教师讲义或口述给出推荐阅读的笔记任务。学习笔记仍以课堂为主线，阅读补充帮助解释课堂省略的机制、实验细节与适用边界。用户明确只要视频、摘要或指定阅读范围时遵从本次要求；不递归追读论文的全部参考文献。

## 身份与范围先核对

- 记录课程学期、官网查询时间、官方视频 ID、播放列表和推荐阅读原始链接。公开视频 Part 编号未必等于官网课次；按标题、授课日期和内容映射，无法确认时标待核对。
- 从官方阅读清单和课堂提及材料出发，优先论文原文、作者/机构技术报告、官方文档与仓库。社区笔记只作定位或对照，不作为已阅读原文的证明。
- 同时盘点讲义和转写中的推荐，记录原始物理页、源码行或口述句ID。给材料标 recommendation_kind：explicit_recommendation / core_source / background_citation；说明 required 与取舍依据。明确推荐默认 required，核心方法的直接原始来源纳入相关阅读；仅历史背景或论文参考文献不自动扩展为整门新课程，不能把课上引用说成老师明确推荐。
- 明确推荐若按用户范围排除，required=false 必须附 scope_reason，不能用改标记逃过阅读门槛；范围内 required 材料仅读完而未形成有内容的课堂补充，整合阶段仍 pending。读后确认为无关时应给出具体取舍证据并重核 required，而非写“没时间”。额外推荐视频与论文/书章分开登记，不把读配套代码冒充观看视频。
- 先复用文件与实际阅读记录。arXiv abs HTML、参考文献元数据或下载成功只证明身份/获取，不证明有全文；同名不同版本不混用。书籍/长网页可按与课程相关的明确章节限定范围，记录 scope_sections；此时 full 只表示该声明范围已读完，不能声称整书已读。
- 打开后核对实际标题、作者、arXiv ID/版本或 DOI；官网文字与链接错配时同时保留原链接和核实后的来源，不悄悄修正，不总结错误论文。新版与授课时版本不同则分开标注，不能把新版结果归于课堂。
- 逐项给出处置：本课相关并阅读、同课其他视频共用已读版本、未访问/受限、身份存疑，或不在本课范围（理由）。相关材料默认纳入；仅因阅读耗时长不静默省略。

## 实际读原文

### 明确推荐的课外视频

课外明确推荐的视频默认按课堂视频标准复核；用户明确排除才记录范围理由。不以作者配套文本、摘要、网页字幕或代码阅读替代完整音视频采集。复用匹配视频ID的媒体、BaoCut转写及真实核验记录；音频/视频stream完整性与尾段解码分别检查，全文顺序阅读转写，按`visual-coverage.md`盘点全时间轴画面、复核入选原帧。将独有的推导、代码执行状态、例子与边界写入关联课堂正文，并明确属于课外视频、给真实时间码与来源。并非逐秒播放/听审时如实注明。

材料登记`kind=video`、真实媒体`path/sha256`，以及`video_review`：`video_id`、`duration_seconds`、`media_integrity=passed`、`transcript_reading=full`、`visual_review=full_timeline`。`artifacts`登记带当前哈希的`transcript`、`read_coverage`、`manifest`、`fidelity_eval`四项，字段为`path/sha256`。缺一阶段保持partial/pending；只有配套文稿不允许声明视频full。文件/声明校验仍不能证明真的阅读或看过画面；独立内容与最终页面验收继续执行。

### 论文、书章与网页

完整下载/提取不等于已经读完。PDF 按物理页保留索引，再分块阅读全文，含方法、实验、局限和相关附录；长网页按真实章节分块。教师明确只推荐特定章节/附录，或课程相关的书籍章节时，可记录 scope_pages / scope_sections 与 scope_reason（原推荐证据及边界），full 只表示该声明范围完成，不冒充整篇/整书。不能因为耗时长才临时缩小范围。只有摘要可访问时明确标 abstract_only，不据此写方法或实验细节。范围内只能读部分时记录未读部分，不写 full。

承载关键公式、架构、表格或消融的原页应实际目视，检查提取缺失的符号、图例、坐标与分母。网页 HTML、PDF 物理页和印刷页不要混用定位。阅读材料没有视频时间码；related_time 只表示关联课堂片段。

读每篇时围绕本课问题判断：

- 它补上课堂哪一步论证？方法的输入、反馈/验证信号、搜索或训练流程、输出分别是什么？
- 结果在哪个模型、数据集、预算、指标与基线上成立？oracle coverage、可部署的选择准确率和成本能否分开？
- 对照/消融支持哪个结论，作者承认哪些限制，哪些泛化判断仍只是整理者推论？
- 对学习者的实际设计选择有何影响？练习或小实验可作为整理者建议，不冒充原论文实验。

按材料实际内容组织，不强迫每篇相同字数、模板或配图数量。只摘有教学作用的图表，保留图号、物理页、来源及真实查看记录，不为“补充”复制全部 PDF 图。

## 阅读台账与正文连接

课程级保存一份 `materials.json`，单课 manifest 把它列为 artifact 并在 scope 中写本课材料 ID。共用材料只需读一次，但复用必须匹配版本/哈希和实际已读范围。最少字段示例：

```json
{
  "schema_version": 1,
  "course_url": "https://example.edu/course",
  "checked_at": "带时区的实际查询时间",
  "expected_material_ids": ["paper-001"],
  "materials": [{
    "id": "paper-001",
    "listed_title": "官网标题",
    "listed_url": "https://example.edu/original-link",
    "title": "已核实的原文标题",
    "source_url": "https://arxiv.org/abs/XXXX.XXXXXv1",
    "version": "v1",
    "identity_status": "verified",
    "identity_note": null,
    "path": "sources/paper-001.pdf",
    "sha256": "实际文件哈希",
    "total_pages": 12,
    "reading_status": "partial",
    "read_pages": [1, 2, 3],
    "read_sections": [],
    "visual_checks": [{"page": 3, "detail": "实际看过的图表及发现"}],
    "known_gaps": ["物理页4至12未读"],
    "related_items": ["lecture-02"],
    "contributions": [{
      "item": "lecture-02", "section": 3,
      "location": "PDF物理页3，式2",
      "claim": "正文采用的具体补充",
      "role": "mechanism",
      "note_target": "editor_notes[0]"
    }]
  }]
}
```

reading_status 使用 unread/abstract_only/partial/full/blocked/out_of_scope；身份使用 verified/mismatch/unverified。full 只能在实际完整阅读后声明，未知页数/版本留 null。网页用 read_sections 与稳定章节锚点；不要给网页编页码。contributions 指向实际写入的补充；读过但没采用时说明原因，不强行造结论。

正文沿用 notes v2：

- `sections[].editor_notes`：在对应课堂论证旁写“论文补充 [paper-001，v1，物理页3，式2]：……”；来源网页链接及详细方法写入 `supplements`。
- `supplements[]`：用 title/text/source_label/source_url/pages 表达独立补充，source_label 标“课程推荐论文，非课堂口述”；网页不写 pages。text 中给材料 ID、章节/图号、实验口径、局限及关联课堂章节。每篇保留有实际学习价值的内容，不能仅列标题与 URL；条目独立标注来源，通过 notes 的 `flow` 放进相关知识点，不要求单列文末补充区。
- 论文插图使用已支持的 `pdf_page`，放在相关节的 frames 中，caption 明确“论文补充”、材料 ID/版本/图号，source_label/source_url/page 完整。不要伪造 time；需要导航时用 related_time。
- 重要图表可以复用已核对版本的原图，或从原页提取完整教学区域；保留坐标、图例、表头、单位、样本量和关键脚注，并写图的解读及实验边界，不只插图不解释。裁切不能改变含义，原页另保留供回查；已有课堂图与同版原文一致时可复用，不必重复塞图。

## 回查与验收

在 manifest 的 `status` 写 `reading_materials` 与 `material_integration`（passed/pending/blocked/not_requested）及证据路径。补充内容进入 [保真评测](fidelity-eval.md) 的精度抽查（ref 为 `xN`）。逐项核对预期阅读清单、身份、真实阅读范围和正文贡献。需要材料而未读完时，总 outcome=partial；缺口不阻塞视频文字笔记等独立阶段。

检查每个关键补充的原文位置、预算/指标/基线、语气和归因；查看最终 HTML 确认 supplements、正文注释与论文图实际保留、来源链接可回查，并按 [分层阅读与图解](layered-reading.md) 检查补充与相关图紧邻其解释的课堂问题。结构校验、哈希或全文提取不能证明读完或语义正确。manifest 的 artifacts 把使用的原文、materials.json、图片、notes、评测和 HTML 加入依赖链；材料版本变化只重做受影响的补充和产物，不重复 ASR。

运行 `python3 <skill>/scripts/validate_materials.py --materials <course>/materials.json --course-root <course>`，核对材料身份、当前源哈希、声明阅读范围与实际正文/图表落点。required 材料未完成时返回 pending，不把已下载当完成；该工具不判断语义正确或代理是否真的读过。正文改变后保留原视频视觉盘点，更新依赖哈希并重新验收受影响的图和HTML，旧UI记录不能自动沿用。
