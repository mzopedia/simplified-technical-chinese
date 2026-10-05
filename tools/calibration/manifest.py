#!/usr/bin/env python3
"""记录语料目录里每个仓库的来源和提交号，写成 corpora.json，让别人能复现同一份语料。

用法：
    python3 tools/calibration/manifest.py <语料目录> <输出文件>
"""

import json
import os
import subprocess
import sys


def git(path: str, *args: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", path, *args], text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        return ""


def main(argv) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    root, out = argv[1], argv[2]
    corpora = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(os.path.join(path, ".git")):
            continue
        sparse = git(path, "sparse-checkout", "list").split("\n") if git(path, "config", "core.sparseCheckout") == "true" else []
        corpora.append({
            "name": name,
            "remote": git(path, "remote", "get-url", "origin"),
            "commit": git(path, "rev-parse", "HEAD"),
            "date": git(path, "log", "-1", "--format=%cs"),
            "paths": [p for p in sparse if p],
        })
    with open(out, "w", encoding="utf-8") as f:
        json.dump(corpora, f, ensure_ascii=False, indent=1)
    for c in corpora:
        print(f"{c['name']}: {c['remote']} @ {c['commit'][:7]} ({c['date']}) {' '.join(c['paths'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
