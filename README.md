# 叙事母题证据台账

这是一个供文学课程与民间叙事研究小组使用的本地分析工具。研究者导入有来源说明的故事结构记录，逐条标注判断及其事件依据，再查看标注共识、未决覆盖率和可回溯报告。工具不自动解释文学意义，也不把新闻评论中的解释当作已验证结论。

## 运行

需要 Python 3.11 或更新版本，无第三方依赖。

从项目根目录运行：

```sh
PYTHONPATH=src python -m story_patterns.cli demo --database /tmp/story-patterns.sqlite3 --fixture fixtures/demo.json
```

也可分别使用 `import`、`decide` 与 `report` 子命令处理 JSON 文件。每个故事修订版包含来源、角色顺序及连续事件；每项判断必须引用该修订版中的事件。批次标识支持安全重试，标注标识与标注员序号不可覆盖既有内容。

支持包含故事对象的 JSON 数组或逐行 NDJSON 导入；这两种格式需使用 `--batch-id`。`queue` 展示未评、待补共识、分歧及已达共识的样本，并列出尚未被判断引用的事件。`report` 同时给出标注员两两一致率及事件证据覆盖率；这些是描述性指标，不替代人工解释。报告以内容指纹保存，可用 `export --report-id ... --format json|csv --output ...` 输出；默认拒绝覆盖现有文件，显式 `--force` 才替换。`audit` 检查 SQLite 内部与外键完整性。

导入前可以用 `preview` 汇总每条记录的校验错误，不写数据库；正式导入仍坚持整批事务。`lineage` 展示已录入的修订版本与缺失序号。`compare` 按传统标签分层输出描述性比例、共识数与覆盖率；不同分组的分母可能不同，结果不作因果或总体推断。

`manifest` 汇总导入批次、故事修订和来源引用。保存报告还包含读者剔除敏感性检查，提示结论是否依赖某位读者；该诊断不等同于置信区间。报告可导出为 Markdown (`--format md`) 供课程讨论。

`audit` 除 SQLite 外键和数据库完整性检查外，也会复核故事文档与索引列、导入批次摘要、标注证据、仲裁摘要及已保存报告的内容指纹是否一致。修订对比会标出角色、顺序、来源和事件内容变化；每个版本独立标注，系统不把旧版判断自动复制到新版。

## 证据锚点与故事修订

故事可以包含 `passages`（稳定段落：`passage_id`、可选 `chapter`、`paragraph` 与原文 `text`），事件可用 `passage_id` 指向段落。判断和仲裁记录可额外提供 `evidence_anchors`：

```json
{"decision_id": "a-1", "story_id": "well-and-bridge", "story_revision": 1,
 "annotator": "reader-a", "sequence": 1, "pattern": "parallel", "youngest_outcome": "wins",
 "evidence_event_ids": ["hide-bucket"],
 "evidence_anchors": [{"event_id": "hide-bucket", "passage_id": "p-well",
                       "quote": "把唯一的木桶藏进草堆"}]}
```

锚点也可以只写 `chapter` 与 `paragraph`，或只写 `quote`（此时按事件定位）；记录时会锁定引文在段落内的字符范围。引文必须出现在该修订版中，锚点不得引用 `evidence_event_ids` 之外的事件。未提供 `evidence_anchors` 的旧记录保持原样，继续按自由文本 `note` 与事件依据读取；锁定内容后的记录不可再用不同内容覆盖。

复核时，每条带锚点的判断都与**同一故事的最新修订版**比较，逐锚点给出：

- `intact`：引文仍在记录时的章节、段落和字符范围；
- `drifted`：引文仍可定位，但段落、阅读顺序、事件序号或字符范围已移动；仍计入覆盖但需人工确认；
- `unverifiable`：引文消失、事件被删除或事件内容已改写（引文可能仍在，却不再支持同一事件）。这类事件**不计入**证据覆盖率；
- `unstructured`：没有锚点的旧记录，仍按自由文本证据读取，不进入复核队列。

`queue` 会把已达成独立共识但锚点待复查的样本标为 `evidence_recheck`，并在 `decision_recheck` 中列出判断、复核状态与失效事件；`history` 为每条判断附上逐锚点复核结果。报告新增 `anchor_recheck` 汇总、每个故事修订的 `anchor_recheck_status`，并把被排除的引用列入 `evidence_coverage.invalid_anchor_citations`；CSV 与 Markdown 导出同样可见。没有稳定段落编号的材料（如口述转写）仍保留事件 `evidence` 原文，`manifest` 会给出 `has_stable_passages` 与逐事件的原文依据，批次来源仍按 `batch_stories` 保留。

`fixtures/anchors.json` 用本地合成材料演示插段、删段与重排后的复核；`demo` 会依次导入 `revisions` 中的后续修订版：

```sh
PYTHONPATH=src python -m story_patterns.cli demo --database /tmp/story-patterns-anchors.sqlite3 --fixture fixtures/anchors.json
```

报告列出最新有效读者的逐标签投票数和每位读者覆盖的修订数；被后续序号取代的旧判断仍保留在 `history`，但不会重复进入统计。

若独立标注存在分歧，编辑可用 `adjudicate` 提交单独的处理记录。它要求引用当前修订事件与简短理由，不覆盖任何读者投票；报告并列保留独立共识、最终采用标签及仲裁依据。`history` 可查看一位读者此前的判断和所有仲裁版本。

报告分别统计“平行型/加害型”判断和最小者结局判断。`unclear` 与 `unknown` 不进入对应投票，但覆盖表会保留同意、分歧和样本不足数量。报告列出参与故事修订及判断编号，便于复核。数据库仅保存在用户指定的本地路径。

演示文件完全由本地合成材料构成，并非新闻报道或已出版故事的原文。

## 检查

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m compileall -q src
PYTHONPATH=src python -m story_patterns.cli demo --database /tmp/story-patterns-check.sqlite3 --fixture fixtures/demo.json
```
