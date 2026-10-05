#!/usr/bin/env python3
"""汇总命中统计和标注结果，算出每条规则、每个词的精确率，生成校准报告草稿。

用法：
    python3 tools/calibration/report.py <输出目录>

读取 stats.json、sample.jsonl、labels.jsonl；如果有 labels.human.jsonl（人工复核，同样的 id 和 verdict 字段），
人工结果覆盖模型结果。输出 report.md（表格）和 misses.md（所有判为误报的样本及理由，供修规则用）。

精确率 = 真 / (真 + 误)，不确定不计入。建议列按精确率给：
    ≥ 0.80 保留；0.50–0.79 加条件或降为建议；< 0.50 从脚本移除，规则只留在文本里。
"""

import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))


def wilson_low(k: int, n: int, z: float = 1.96) -> Optional[float]:
    """精确率的 Wilson 区间下界，样本少时提醒别过度相信。"""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def rule_titles() -> Dict[str, Tuple[str, str]]:
    out: Dict[str, Tuple[str, str]] = {}
    with open(os.path.join(ROOT, "规范.md"), encoding="utf-8") as f:
        for line in f:
            m = re.match(r"### (\d+\.\d+) (.*?)【(必须|建议)】", line)
            if m:
                out[m.group(1)] = (m.group(2), m.group(3))
    return out


def advice(p: Optional[float], n: int) -> str:
    if p is None or n == 0:
        return "无样本"
    if n < 10:
        return "样本不足"
    if p >= 0.8:
        return "保留"
    if p >= 0.5:
        return "加条件 / 降为建议"
    return "从脚本移除"


def fmt_p(p: Optional[float]) -> str:
    return "–" if p is None else f"{p * 100:.0f}%"


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    out_dir = argv[1]
    with open(os.path.join(out_dir, "stats.json"), encoding="utf-8") as f:
        stats = json.load(f)
    sample: Dict[str, dict] = {}
    with open(os.path.join(out_dir, "sample.jsonl"), encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            sample[rec["id"]] = rec
    labels: Dict[str, dict] = {}
    for name in ("labels.jsonl", "labels.human.jsonl"):
        path = os.path.join(out_dir, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("verdict") in ("真", "误", "不确定"):
                    labels[rec["id"]] = {**rec, "source": "人工" if "human" in name else "模型"}

    titles = rule_titles()
    total_chars = sum(c["chars"] for c in stats["corpora"].values()) or 1

    by_rule: Dict[str, Counter] = defaultdict(Counter)
    by_word: Dict[str, Counter] = defaultdict(Counter)
    misses: Dict[str, List[dict]] = defaultdict(list)
    for sid, rec in sample.items():
        lab = labels.get(sid)
        if not lab:
            by_rule[rec["rule"]]["未标"] += 1
            continue
        by_rule[rec["rule"]][lab["verdict"]] += 1
        if rec.get("word"):
            by_word[rec["word"]][lab["verdict"]] += 1
        if lab["verdict"] == "误":
            misses[rec["rule"]].append({**rec, "reason": lab["reason"], "source": lab["source"]})

    md = ["# 校准报告（草稿，由 tools/calibration/report.py 生成）", ""]
    md += ["## 语料", "", "| 语料库 | 文件 | 句子 | 字数 | 命中 | 每万字命中 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for c, s in stats["corpora"].items():
        md.append(f"| {c} | {s['files']} | {s['sentences']} | {s['chars']} | {s['findings']} | {s['findings_per_10k_chars']} |")
    md.append(f"| 合计 | {sum(s['files'] for s in stats['corpora'].values())} | {sum(s['sentences'] for s in stats['corpora'].values())} | {total_chars} | {stats['total_findings']} | {stats['total_findings'] / total_chars * 10000:.1f} |")

    md += ["", "## 每条规则", "", "精确率 = 真 / (真 + 误)。括号里是 95% 置信区间下界。", "",
           "| 规则 | 名称 | 级别 | 命中 | 每万字 | 抽样 | 真 | 误 | 不确定 | 精确率 | 估计误报/万字 | 建议 |",
           "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    rules = sorted(stats["rules"], key=lambda r: -stats["rules"][r]["total"])
    for r in rules:
        c = by_rule.get(r, Counter())
        k, n = c["真"], c["真"] + c["误"]
        p = k / n if n else None
        low = wilson_low(k, n)
        hits = stats["rules"][r]["total"]
        per10k = hits / total_chars * 10000
        fp = per10k * (1 - p) if p is not None else None
        title, level = titles.get(r, ("?", "?"))
        md.append(f"| {r} | {title} | {level} | {hits} | {per10k:.1f} | {sum(c.values())} | {c['真']} | {c['误']} | {c['不确定']} | "
                  f"{fmt_p(p)}{'' if low is None else f' ({fmt_p(low)})'} | {'–' if fp is None else f'{fp:.1f}'} | {advice(p, n)} |")

    md += ["", "## 词表条目（按命中数排序，只列有样本的词）", "",
           "| 词 | 规则 | 命中 | 每万字 | 抽样 | 真 | 误 | 精确率 | 建议 |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    words = sorted(stats["words"], key=lambda w: -stats["words"][w]["total"])
    for w in words:
        c = by_word.get(w)
        if not c:
            continue
        k, n = c["真"], c["真"] + c["误"]
        p = k / n if n else None
        info = stats["words"][w]
        md.append(f"| {w} | {info['rule']} | {info['total']} | {info['total'] / total_chars * 10000:.2f} | {sum(c.values())} | {c['真']} | {c['误']} | {fmt_p(p)} | {advice(p, n)} |")

    limits = stats.get("limits", {"操作": "?", "描述": "?"})
    md += ["", "## 句长分布（字）", "", f"| 语料库 | 句型 | n | 均值 | p50 | p90 | p95 | p99 | 超过上限（操作 {limits['操作']} / 描述 {limits['描述']}） |",
           "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for c in list(stats["corpora"]) + ["__all__"]:
        for k in ("操作", "描述"):
            p = stats["sentence_length"].get(c, {}).get(k) or {}
            if not p:
                continue
            over = stats["over_limit"][c][k]
            md.append(f"| {'合计' if c == '__all__' else c} | {k} | {p['n']} | {p['mean']} | {p['p50']} | {p['p90']} | {p['p95']} | {p['p99']} | {over}% |")

    n_lab = sum(sum(c[v] for v in ("真", "误", "不确定")) for c in by_rule.values())
    n_human = sum(1 for l in labels.values() if l["source"] == "人工")
    md += ["", f"样本 {len(sample)} 条，已标 {n_lab} 条，其中人工复核 {n_human} 条。", ""]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    lines = ["# 判为误报的样本", ""]
    for r in rules:
        if not misses.get(r):
            continue
        title = titles.get(r, ("?", "?"))[0]
        lines += [f"## {r} {title}（{len(misses[r])} 条）", ""]
        for m in misses[r]:
            w = f"「{m['word']}」" if m.get("word") else ""
            lines.append(f"- {w}{m['text']}  \n  理由：{m['reason']}（{m['source']}；{m['corpus']} {m['path']}:{m['line']}）")
        lines.append("")
    with open(os.path.join(out_dir, "misses.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"report.md 和 misses.md 已写入 {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
