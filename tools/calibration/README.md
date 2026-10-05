# 校准流程

这个目录的脚本把检查脚本放到真实中文技术文档上跑，量出每条规则、每个词的命中数和精确率，用结果决定规则的级别、阈值和词表的取舍。校准结果见 [docs/校准报告.md](../../docs/校准报告.md)。

## 步骤

1. 准备语料。每个文档仓库克隆到 `.data/corpus/<名称>/`。大仓库用稀疏检出只取中文文档目录。`.data/` 不入库。
2. 记录语料版本：

   ```bash
   python3 tools/calibration/manifest.py .data/corpus .data/calib/corpora.json
   ```

3. 统计命中和句长分布：

   ```bash
   python3 tools/calibration/stats.py .data/corpus .data/calib
   ```

   只统计正文以中文为主的 Markdown 文件。双语仓库只取中文版。输出 `findings.jsonl`、`sentences.jsonl`、`stats.json`、`stats.md`。

4. 分层抽样：

   ```bash
   python3 tools/calibration/sample.py .data/corpus .data/calib --per-rule 50 --per-word 8
   ```

   每条规则最多 50 条。词表类规则先按词分层，每个词最多 8 条，再在语料库之间轮流取。

5. 模型初判：

   ```bash
   python3 tools/calibration/label.py .data/calib --env <含 LLM_BASE_URL、LLM_API_KEY、LLM_MODEL 的文件>
   ```

   每条样本给出「真」「误」「不确定」和一句理由。支持断点续跑。

6. 人工复核。把复核结果写进 `.data/calib/labels.human.jsonl`，字段和 `labels.jsonl` 相同，人工结果覆盖模型结果。
7. 生成报告：

   ```bash
   python3 tools/calibration/report.py .data/calib
   ```

   `report.md` 是表格，`misses.md` 列出所有判为误报的样本和理由，用来修正则和词表。

## 判定标准

- 真：规则按字面确实被违反，而且按规则改写后，这句话不会变得更不准确。
- 误：命中的词或句在这里是正常用法、固定术语、引用的界面文字或代码，或者按规则改写会损害意思。
- 不确定：两种判断都说得通。不计入精确率。

## 处理规则

精确率 = 真 / (真 + 误)。

| 精确率 | 处理 |
| --- | --- |
| 不低于 80% | 保留 |
| 50% 到 79% | 给词加匹配条件，或把规则降为【建议】 |
| 低于 50% | 从脚本移除。规则只留在规范文本里，由人判断 |

句长阈值取好文档中句长分布的 p90 附近，而不是拍脑袋。
