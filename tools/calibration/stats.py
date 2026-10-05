#!/usr/bin/env python3
"""在真实语料上运行检查脚本，统计每条规则、每个词的命中数和句长分布。

用法：
    python3 tools/calibration/stats.py <语料目录> <输出目录>

语料目录下每个子目录是一个语料库（一个文档仓库）。只统计中文为主的 Markdown 文件。
输出：
    findings.jsonl   每条命中一行，带语料库、路径、行号、规则、词
    sentences.jsonl  每个句子一行，带句型（操作/描述）、字数、「的」数
    stats.json       汇总数字
    stats.md         汇总表，可直接贴进校准报告
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Dict, Iterator, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import check  # noqa: E402

SKIP_DIRS = {".git", "node_modules", ".github", ".vitepress", "public", "_template"}
MIN_CJK = 100  # 少于这个数的汉字按非中文文件处理
WORD_IN_MESSAGE = re.compile(r"「(.+?)」")


PROSE_NOISE = [
    (re.compile(r"\A---\n.*?\n---\n", re.S), ""),       # front matter
    (re.compile(r"<!--.*?-->", re.S), ""),              # HTML 注释（k8s 中文文档用它保留英文原文）
    (re.compile(r"```.*?```", re.S), ""),               # 代码块
    (re.compile(r"`[^`\n]*`"), ""),                     # 行内代码
    (re.compile(r"https?://\S+"), ""),                  # 链接
    (re.compile(r"<[^>\n]+>"), ""),                     # HTML 标签
    (re.compile(r"\{\{.*?\}\}", re.S), ""),             # Hugo / 模板短代码
]


def is_chinese_doc(text: str) -> bool:
    """正文（去掉代码、注释、链接、标签后）以中文为主的文件才算语料。"""
    for pat, rep in PROSE_NOISE:
        text = pat.sub(rep, text)
    cjk = len(check.CJK.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return cjk >= MIN_CJK and cjk * 2 >= latin


def md_files(root: str) -> Iterator[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            # ant-design 这类双语仓库：只取中文版
            if re.search(r"\.(en-US|en)\.md$", name):
                continue
            yield os.path.join(dirpath, name)


def sentences_of(text: str) -> Iterator[dict]:
    """按检查脚本同样的切分方式产出句子。"""
    units = check.parse_units(text.splitlines())
    in_counterexample = False
    for unit in units:
        if not unit.indented:
            in_counterexample = check.is_counterexample(unit.lines[0])
        if in_counterexample or unit.skip or unit.kind in ("heading", "table"):
            continue
        for offset, raw in enumerate(unit.lines):
            line = check.strip_markup(raw)
            for pos, s in enumerate(check.split_sentences(line)):
                op = unit.kind == "ordered" and not s.startswith(check.SYSTEM_SUBJECTS)
                n = check.count_chars(s)
                if n == 0:
                    continue
                yield {
                    "line": unit.start_line + offset,
                    "unit": unit.kind,
                    "kind": "操作" if op else "描述",
                    "chars": n,
                    "de": s.count("的"),
                    "text": s[:80],
                }


def percentiles(values: List[int], points=(50, 75, 90, 95, 99)) -> Dict[str, float]:
    if not values:
        return {}
    xs = sorted(values)
    out = {}
    for p in points:
        k = max(0, min(len(xs) - 1, round(p / 100 * len(xs) + 0.5) - 1))
        out[f"p{p}"] = xs[k]
    out["max"] = xs[-1]
    out["n"] = len(xs)
    out["mean"] = round(sum(xs) / len(xs), 1)
    return out


def word_of(f: check.Finding) -> Optional[str]:
    if f.rule in ("1.1", "1.3", "1.4", "1.5", "1.7", "2.3", "3.5", "4.1", "5.2", "5.4", "3.3"):
        m = WORD_IN_MESSAGE.search(f.message)
        return m.group(1) if m else None
    return None


def main(argv: List[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    corpus_root, out_dir = argv[1], argv[2]
    os.makedirs(out_dir, exist_ok=True)
    checker = check.Checker(check.load_vocab())

    corpora = sorted(d for d in os.listdir(corpus_root) if os.path.isdir(os.path.join(corpus_root, d)))
    per_corpus: Dict[str, dict] = {}
    rule_counts: Dict[str, Counter] = defaultdict(Counter)   # rule -> corpus -> n
    word_counts: Dict[str, Counter] = defaultdict(Counter)   # word -> corpus -> n
    word_rule: Dict[str, str] = {}
    lengths: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: {"操作": [], "描述": []})
    de_counts: Dict[str, List[int]] = defaultdict(list)
    n_findings = 0

    with open(os.path.join(out_dir, "findings.jsonl"), "w", encoding="utf-8") as ff, \
            open(os.path.join(out_dir, "sentences.jsonl"), "w", encoding="utf-8") as sf:
        for corpus in corpora:
            root = os.path.join(corpus_root, corpus)
            stat = {"files": 0, "skipped_files": 0, "sentences": 0, "chars": 0, "findings": 0, "must": 0}
            for path in md_files(root):
                try:
                    with open(path, encoding="utf-8") as f:
                        text = f.read()
                except (UnicodeDecodeError, OSError):
                    stat["skipped_files"] += 1
                    continue
                if not is_chinese_doc(text):
                    stat["skipped_files"] += 1
                    continue
                rel = os.path.relpath(path, root)
                stat["files"] += 1
                for s in sentences_of(text):
                    stat["sentences"] += 1
                    stat["chars"] += s["chars"]
                    lengths[corpus][s["kind"]].append(s["chars"])
                    lengths["__all__"][s["kind"]].append(s["chars"])
                    de_counts[corpus].append(s["de"])
                    s.update({"corpus": corpus, "path": rel})
                    sf.write(json.dumps(s, ensure_ascii=False) + "\n")
                for i, fd in enumerate(checker.check_text(text, rel)):
                    w = word_of(fd)
                    if w:
                        word_counts[w][corpus] += 1
                        word_rule[w] = fd.rule
                    rule_counts[fd.rule][corpus] += 1
                    stat["findings"] += 1
                    stat["must"] += fd.level == check.MUST
                    n_findings += 1
                    rec = {
                        "id": f"{corpus}:{rel}:{fd.line}:{fd.rule}:{i}",
                        "corpus": corpus, "path": rel, "line": fd.line, "rule": fd.rule,
                        "level": fd.level, "word": w, "message": fd.message, "text": fd.text,
                    }
                    ff.write(json.dumps(rec, ensure_ascii=False) + "\n")
            stat["findings_per_10k_chars"] = round(stat["findings"] / stat["chars"] * 10000, 1) if stat["chars"] else None
            per_corpus[corpus] = stat
            print(f"{corpus}: {stat['files']} 个文件，{stat['sentences']} 句，{stat['chars']} 字，{stat['findings']} 条命中", file=sys.stderr)

    rules_sorted = sorted(rule_counts, key=lambda r: -sum(rule_counts[r].values()))
    words_sorted = sorted(word_counts, key=lambda w: -sum(word_counts[w].values()))
    stats = {
        "corpora": per_corpus,
        "total_findings": n_findings,
        "rules": {r: {"total": sum(c.values()), "by_corpus": dict(c)} for r, c in rule_counts.items()},
        "words": {w: {"rule": word_rule[w], "total": sum(c.values()), "by_corpus": dict(c)} for w, c in word_counts.items()},
        "sentence_length": {
            c: {k: percentiles(v) for k, v in kinds.items()} for c, kinds in lengths.items()
        },
        "over_limit": {
            c: {
                "操作>25": round(sum(x > 25 for x in kinds["操作"]) / len(kinds["操作"]) * 100, 1) if kinds["操作"] else None,
                "描述>40": round(sum(x > 40 for x in kinds["描述"]) / len(kinds["描述"]) * 100, 1) if kinds["描述"] else None,
            } for c, kinds in lengths.items()
        },
        "de_per_sentence": {c: percentiles(v) for c, v in de_counts.items()},
    }
    with open(os.path.join(out_dir, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)

    total_chars = sum(s["chars"] for s in per_corpus.values()) or 1
    md = ["## 语料", "", "| 语料库 | 文件 | 句子 | 字数 | 命中 | 每万字命中 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for c, s in per_corpus.items():
        md.append(f"| {c} | {s['files']} | {s['sentences']} | {s['chars']} | {s['findings']} | {s['findings_per_10k_chars']} |")
    md += ["", "## 每条规则的命中", "", "| 规则 | 命中 | 每万字 | " + " | ".join(corpora) + " |",
           "| --- | ---: | ---: | " + " | ".join("---:" for _ in corpora) + " |"]
    for r in rules_sorted:
        c = rule_counts[r]
        md.append(f"| {r} | {sum(c.values())} | {sum(c.values()) / total_chars * 10000:.1f} | " + " | ".join(str(c.get(x, 0)) for x in corpora) + " |")
    md += ["", "## 命中最多的词（前 60）", "", "| 词 | 规则 | 命中 | 每万字 |", "| --- | --- | ---: | ---: |"]
    for w in words_sorted[:60]:
        c = word_counts[w]
        md.append(f"| {w} | {word_rule[w]} | {sum(c.values())} | {sum(c.values()) / total_chars * 10000:.2f} |")
    md += ["", "## 句长分布（字）", "", "| 语料库 | 句型 | n | 均值 | p50 | p75 | p90 | p95 | p99 | 最长 | 超过草案上限 |",
           "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for c in corpora + ["__all__"]:
        for k in ("操作", "描述"):
            p = stats["sentence_length"].get(c, {}).get(k) or {}
            if not p:
                continue
            over = stats["over_limit"][c]["操作>25" if k == "操作" else "描述>40"]
            md.append(f"| {c} | {k} | {p['n']} | {p['mean']} | {p['p50']} | {p['p75']} | {p['p90']} | {p['p95']} | {p['p99']} | {p['max']} | {over}% |")
    with open(os.path.join(out_dir, "stats.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(f"共 {n_findings} 条命中，写入 {out_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
