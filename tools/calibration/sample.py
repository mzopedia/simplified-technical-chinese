#!/usr/bin/env python3
"""从 findings.jsonl 分层抽样，生成待标注的样本。

用法：
    python3 tools/calibration/sample.py <语料目录> <输出目录> [--per-rule 50] [--per-word 8] [--seed 1]

每条规则最多抽 per-rule 条。词表类规则先按词分层，每个词最多 per-word 条，再在语料库之间轮流取，
让样本覆盖不同的词和不同的文档风格。每条样本附上命中行前后各一行原文作为上下文。
输出 sample.jsonl。
"""

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from typing import Dict, List

WORD_RULES = {"1.1", "1.3", "1.4", "1.5", "1.7", "2.3", "3.5", "4.1", "5.2", "5.4", "3.3"}


def round_robin(groups: Dict[str, List[dict]], limit: int, rng: random.Random) -> List[dict]:
    """在各组之间轮流取，直到取满 limit 条或取完。"""
    for g in groups.values():
        rng.shuffle(g)
    out: List[dict] = []
    keys = sorted(groups)
    i = 0
    while len(out) < limit and any(groups.values()):
        k = keys[i % len(keys)]
        if groups[k]:
            out.append(groups[k].pop())
        i += 1
    return out


def context(corpus_root: str, rec: dict, width: int = 1) -> List[str]:
    path = os.path.join(corpus_root, rec["corpus"], rec["path"])
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    lo = max(0, rec["line"] - 1 - width)
    hi = min(len(lines), rec["line"] + width)
    return [l[:300] for l in lines[lo:hi]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_root")
    ap.add_argument("out_dir")
    ap.add_argument("--per-rule", type=int, default=50)
    ap.add_argument("--per-word", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    by_rule: Dict[str, List[dict]] = defaultdict(list)
    with open(os.path.join(args.out_dir, "findings.jsonl"), encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            by_rule[rec["rule"]].append(rec)

    sample: List[dict] = []
    for rule in sorted(by_rule):
        recs = by_rule[rule]
        if rule in WORD_RULES:
            # 先按词分层：每个词最多 per-word 条，词内按语料库轮流
            by_word: Dict[str, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
            for r in recs:
                by_word[r.get("word") or "?"][r["corpus"]].append(r)
            per_word = {w: round_robin(groups, args.per_word, rng) for w, groups in by_word.items()}
            picked = round_robin({w: v for w, v in per_word.items()}, args.per_rule, rng)
        else:
            by_corpus: Dict[str, List[dict]] = defaultdict(list)
            for r in recs:
                by_corpus[r["corpus"]].append(r)
            picked = round_robin(by_corpus, args.per_rule, rng)
        for r in picked:
            r["context"] = context(args.corpus_root, r)
        sample.extend(sorted(picked, key=lambda r: r["id"]))
        print(f"{rule}: 命中 {len(recs)}，抽 {len(picked)}", file=sys.stderr)

    with open(os.path.join(args.out_dir, "sample.jsonl"), "w", encoding="utf-8") as f:
        for r in sample:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"共抽 {len(sample)} 条", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
