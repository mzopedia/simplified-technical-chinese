#!/usr/bin/env python3
"""用模型初判抽样结果是真报还是误报。结果供人工抽查，不直接当结论。

用法：
    python3 tools/calibration/label.py <输出目录> --env <含 LLM_* 变量的 .env 文件> [--workers 8] [--limit N]

读取 sample.jsonl，对每条样本给出 verdict（真 / 误 / 不确定）和一句理由，写入 labels.jsonl。
断点续跑：labels.jsonl 里已有的 id 跳过。
.env 里需要：LLM_BASE_URL（OpenAI 兼容）、LLM_API_KEY、LLM_MODEL；可选 LLM_EXTRA_JSON（并入请求体）。
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

SYSTEM = """你是一名中文技术文档编辑。有一套写作规范和一个按规范检查文档的脚本。
脚本在一篇真实文档里报了一条提示。请判断这条提示是否成立。

判定标准：
- 真：规则按字面确实被违反，而且按规则改写后，这句话不会变得更不准确。
- 误：命中的词或句在这里是正常用法、固定术语、引用的界面文字或代码，或者按规则改写会损害意思。
- 不确定：两种判断都说得通。

只输出一行 JSON：{"verdict": "真|误|不确定", "reason": "不超过 40 字的理由"}"""


def load_env(path: str) -> Dict[str, str]:
    env: Dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'") if not v.strip().startswith("{") else v.strip()
    return env


def load_rules() -> Dict[str, str]:
    """规范.md 里每条规则的标题和正文（含批准 / 不批准例子）。"""
    with open(os.path.join(ROOT, "规范.md"), encoding="utf-8") as f:
        text = f.read()
    rules: Dict[str, str] = {}
    parts = re.split(r"^(?=### \d+\.\d+ )", text, flags=re.M)
    for p in parts:
        m = re.match(r"### (\d+\.\d+) (.*)", p)
        if not m:
            continue
        body = re.split(r"^## ", p, flags=re.M)[0].strip()
        rules[m.group(1)] = body[:1500]
    return rules


def load_vocab_rows() -> Dict[str, str]:
    """词表里每个词所在的表格行，供模型看替换建议。"""
    rows: Dict[str, str] = {}
    with open(os.path.join(ROOT, "词表.md"), encoding="utf-8") as f:
        for line in f:
            if not line.startswith("|") or "---" in line:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            for w in re.split("[、，]", cells[0]):
                if w and w not in rows:
                    rows[w] = line.strip()
            if len(cells) > 2:
                for w in re.split("[、，]", cells[2]):
                    if w and w not in rows:
                        rows[w] = line.strip()
    return rows


def build_prompt(rec: dict, rules: Dict[str, str], vocab: Dict[str, str]) -> str:
    parts = [f"## 规则 {rec['rule']}", rules.get(rec["rule"], "（规则正文缺失）")]
    if rec.get("word") and rec["word"] in vocab:
        parts += ["", "## 词表条目", vocab[rec["word"]]]
    parts += ["", "## 脚本的提示", rec["message"], "", "## 命中的句子", rec["text"]]
    if rec.get("context"):
        parts += ["", "## 上下文（原文，命中行前后各一行）", *rec["context"]]
    parts += ["", f"文档来自 {rec['corpus']}，路径 {rec['path']}。这条提示成立吗？"]
    return "\n".join(parts)


def call(env: Dict[str, str], prompt: str, timeout: int = 90) -> str:
    body: dict = {
        "model": env["LLM_MODEL"],
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 200,
    }
    if env.get("LLM_EXTRA_JSON"):
        body.update(json.loads(env["LLM_EXTRA_JSON"]))
    req = urllib.request.Request(
        env["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {env['LLM_API_KEY']}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def parse_verdict(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    v = str(obj.get("verdict", "")).strip()
    if v not in ("真", "误", "不确定"):
        return None
    return {"verdict": v, "reason": str(obj.get("reason", ""))[:120]}


def label_one(env: Dict[str, str], rec: dict, rules: Dict[str, str], vocab: Dict[str, str]) -> dict:
    prompt = build_prompt(rec, rules, vocab)
    last_err = ""
    for attempt in range(3):
        try:
            raw = call(env, prompt)
            parsed = parse_verdict(raw)
            if parsed:
                return {"id": rec["id"], "rule": rec["rule"], "word": rec.get("word"), **parsed, "model": env["LLM_MODEL"]}
            last_err = f"无法解析：{raw[:80]}"
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
            last_err = repr(e)[:120]
        time.sleep(2 * (attempt + 1))
    return {"id": rec["id"], "rule": rec["rule"], "word": rec.get("word"), "verdict": "错误", "reason": last_err, "model": env["LLM_MODEL"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--env", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    env = load_env(args.env)
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        if k not in env:
            print(f"缺少 {k}", file=sys.stderr)
            return 2
    rules, vocab = load_rules(), load_vocab_rows()

    labels_path = os.path.join(args.out_dir, "labels.jsonl")
    done = set()
    if os.path.exists(labels_path):
        with open(labels_path, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("verdict") != "错误":
                    done.add(rec["id"])
    todo = []
    with open(os.path.join(args.out_dir, "sample.jsonl"), encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec["id"] not in done:
                todo.append(rec)
    if args.limit:
        todo = todo[: args.limit]
    print(f"已标 {len(done)}，待标 {len(todo)}", file=sys.stderr)

    n_ok = n_err = 0
    with open(labels_path, "a", encoding="utf-8") as out, ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(label_one, env, rec, rules, vocab) for rec in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            res = fut.result()
            out.write(json.dumps(res, ensure_ascii=False) + "\n")
            out.flush()
            n_err += res["verdict"] == "错误"
            n_ok += res["verdict"] != "错误"
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}（失败 {n_err}）", file=sys.stderr)
    print(f"完成：成功 {n_ok}，失败 {n_err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
