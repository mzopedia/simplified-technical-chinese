# Simplified Technical Chinese

简明技术中文 (STC). A controlled language for Chinese technical writing: procedures, API docs, troubleshooting guides, and explanatory answers from LLMs. The goal is that a reader gets it right on the first read.

It follows the method of [ASD-STE100](https://www.asd-ste100.org/) (Simplified Technical English): a numbered rule set, a controlled vocabulary where one meaning has one word, and sentence constraints a script can check. It is not a translation of STE and is not affiliated with ASD.

The Chinese README is [README.md](README.md). The spec and vocabulary are in Chinese, because they are about Chinese.

## Why

In October 2026 Andrej Karpathy [posted](https://x.com/karpathy/status/2105819303471976479) that asking an LLM to explain things in ASD-STE100 makes the output far more readable. STE is a controlled English built for aircraft maintenance manuals: 53 writing rules plus a dictionary of about 900 words, each with one meaning.

Chinese had no equivalent. The existing Chinese style guides cover typography, punctuation and document structure. None of them does the core of STE: numbered rules, a controlled vocabulary, and sentence constraints that a tool can enforce. This project fills that gap.

## Example

Before, from [examples/before.md](examples/before.md):

> 用户首先需要登陆到目标服务器，然后切换到 /opt 目录并且创建一个用于存放采集器配置文件以及运行时产生的临时数据的工作目录。
>
> *"The user first needs to log in [misspelt] to the target server, then switch to the /opt directory and also create a working directory that is used for storing the collector's configuration files as well as the temporary data produced at runtime."*

After, from [examples/after.md](examples/after.md):

> 1. 登录目标服务器。 *Log in to the target server.*
> 2. 切换到 `/opt` 目录。 *Change to the `/opt` directory.*
> 3. 创建工作目录 `/opt/collector`。工作目录存放配置文件和临时数据。 *Create the working directory `/opt/collector`. It holds the configuration files and temporary data.*

What the checker says about the "before" sentence:

```text
examples/before.md:11: [1.1][必须] 「登陆」改用「登录」          # wrong character for "log in"
examples/before.md:11: [2.1][必须] 操作句 56 字，不超过 25 字      # instruction is 56 units, limit 25
examples/before.md:11: [4.1][必须] 禁用词「然后」，改用：拆成编号步骤  # "then": split into numbered steps
examples/before.md:11: [4.1][必须] 禁用词「并且」，改用：拆句       # "and also": split the sentence
```

The whole "before" document has 48 must-fix findings. The rewrite has 0.

## What is in the box

| File | Content |
| --- | --- |
| [规范.md](规范.md) | The rules. 6 sections, 40 rules, each with a rejected and an approved example. Two levels: must and should |
| [词表.md](词表.md) | The vocabulary. Banned words with replacements, a one-meaning-one-word table, and meaning restrictions on common verbs. About 150 entries |
| [tools/check.py](tools/check.py) | The checker. Zero dependencies, Python 3.9+. It reads the vocabulary tables straight from the Markdown |
| [SKILL.md](SKILL.md) | Agent skill for Claude Code, Codex, Cursor and others |
| [examples/](examples/) | A full before/after rewrite |

The rules that do most of the work:

- One concept, one word, for the whole document.
- No 进行 / 加以 + verb (the Chinese equivalent of "perform an installation"). Use the verb.
- Instructions: at most 25 units. Descriptions: at most 40. A unit is one Chinese character, or one Latin word or number.
- Instructions are imperatives that start with the verb. No 请 ("please"), no 您 ("you"), no "the user needs to".
- Conditions before actions. Warnings in their own paragraph, before the step they apply to.
- No 以上 / 以下 after a number (Chinese "and above / and below" is ambiguous about the endpoint). Write 大于 / 不小于 ("greater than / not less than").
- 打开 ("open") is only for files, windows and pages. Features are 启用 ("enabled"), programs are 启动 ("started").
- 可以 only means "may". Capability is 支持 ("supports").

Rules that are specific to Chinese and have no STE counterpart: nominalised verbs, long pre-nominal modifiers (the 的 chains), the endpoint ambiguity of 以上/以下, the permission/ability ambiguity of 可以, and relative time words. The mapping to STE is in appendix B of the spec.

## Use it with an agent

```bash
npx skills add mzopedia/simplified-technical-chinese
```

Or copy the repository into your agent's skill folder. For Claude Code:

```bash
git clone --depth 1 https://github.com/mzopedia/simplified-technical-chinese.git ~/.claude/skills/simplified-technical-chinese
```

Without the skill, paste this into the system prompt. It is the "normal mode", roughly Karpathy's "80% of the way to STE":

```text
用简明技术中文回答。规则：一句只说一件事，操作句不超过 25 字，描述句不超过 40 字；操作步骤用编号列表，动词开头，不写「请」「您」；用主动句；条件写在动作前面；一个概念全文只用一个词；不用「进行」「相关」「等」「以上」「尽快」「大概」；不用反问和感叹；数字后不用「以上」「以下」，写「大于」「不小于」。
```

For the full rule set, give the model [规范.md](规范.md).

## The checker

```text
python3 tools/check.py file.md [more files]
    --strict            exit 1 when there is any must-level finding
    --json              JSON output
    --kind 操作|描述     force one sentence type; use 描述 for chat answers
    --max-op 25         unit limit for instructions
    --max-desc 40       unit limit for descriptions
```

It reliably catches: banned words, rejected synonyms, sentence and paragraph length, passive markers, double negation, trailing conditions, open-ended lists (…等), relative time, Chinese numerals, "reduced by N times", and warnings or reasons written inside a step.

It cannot judge facts, term choice, logical order, or the meaning restrictions that need context. It treats numbered list items as instructions and uses the count of 的 as a proxy for long modifiers. Every finding needs a human.

It skips code, inline code, HTML comments, text inside 「」 (UI labels), YAML front matter, lines that start with 不批准 ("rejected:"), and anything between `<!-- stc:off -->` and `<!-- stc:on -->`.

## Status

Draft 0.1. Known limits:

- The length limits (25 / 40 units, 15-unit modifiers) are first guesses. No reading experiment has calibrated them.
- The vocabulary has about 170 entries and covers general technical writing only.
- No controlled reading-comprehension study yet.
- The checker is syntactic only.

The spec, the Chinese README and SKILL.md pass the checker with 0 must-level findings, and CI re-checks them on every push. This English README is not checked: the checker is for Chinese text.

## Licence

Text of the spec and vocabulary: [CC BY 4.0](LICENSE-CC-BY-4.0). Checker and tests: [MIT](LICENSE).
