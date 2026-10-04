# 简明技术中文

Simplified Technical Chinese（STC）。一套受控的中文写法，用于技术说明、操作步骤、接口文档和 AI 的解释性回答。目标是读者读一遍就不会读错。

它借鉴 [ASD-STE100](https://www.asd-ste100.org/)（Simplified Technical English）的方法：限制用词，限制句式，一句一事。它不是 ASD-STE100 的译本，与 ASD 没有关系。

<!-- stc:off -->
> **English.** STC is a controlled language for Chinese technical writing, modelled on the method of ASD-STE100: a numbered rule set, a controlled vocabulary (one meaning, one word), and a zero-dependency checker. It is not a translation of STE and is not affiliated with ASD. The rules are written for the ambiguities of Chinese: nominalised verbs (进行 + verb), long pre-nominal modifiers, the inclusive/exclusive ambiguity of 以上/以下, permission vs ability of 可以, and object restrictions on 打开/关闭/启动.
<!-- stc:on -->

## 一个例子

节选自 [examples/before.md](examples/before.md)：

> 改写前：用户首先需要登陆到目标服务器，然后切换到 /opt 目录并且创建一个用于存放采集器配置文件以及运行时产生的临时数据的工作目录。

节选自 [examples/after.md](examples/after.md)：

> 1. 登录目标服务器。
> 2. 切换到 `/opt` 目录。
> 3. 创建工作目录 `/opt/collector`。工作目录存放配置文件和临时数据。

检查脚本对改写前那一句的输出：

```text
examples/before.md:11: [1.1][必须] 「登陆」改用「登录」（进入登录状态）
examples/before.md:11: [2.1][必须] 操作句 56 字，不超过 25 字
examples/before.md:11: [4.1][必须] 禁用词「然后」，改用：拆成编号步骤
examples/before.md:11: [4.1][必须] 禁用词「并且」，改用：拆句；只有真正同时发生时用「同时」
```

整篇改写前的文档有 40 多条【必须】级别的发现，改写后是 0 条。

## 为什么做这个

2026 年 10 月，Andrej Karpathy [发帖](https://x.com/karpathy/status/2105819303471976479)说，让大模型用 ASD-STE100 来解释东西，读起来清楚得多。ASD-STE100 是航空维修手册用的受控英语：53 条写作规则，加一本约 900 个词的词典，每个词只有一个意思。

中文没有对应的东西。已有的中文技术写作规范管排版、标点和文档结构，见[和现有项目的区别](#和现有项目的区别)。它们都没有做 STE 的核心：编号规则、受控词表、可以自动检查的句法约束。本项目补这一块。

## 内容

| 文件 | 内容 |
| --- | --- |
| [规范.md](规范.md) | 写作规则。6 节，40 条，每条带「不批准 / 批准」例句。规则分【必须】和【建议】两级 |
| [词表.md](词表.md) | 受控词表。禁用词及替换、选词表（一个意义一个词）、一词一义限定。约 150 条 |
| [tools/check.py](tools/check.py) | 检查脚本。零依赖，Python 3.9 及以上。读规范和词表，输出行号、规则号、级别 |
| [SKILL.md](SKILL.md) | 给 Claude Code、Codex、Cursor 这类 agent 用的技能文件 |
| [examples/](examples/) | 改写前后的完整示例 |

规则的六节：词、句、段、步骤与警告、数字时间与范围、术语与标记。最常用的几条：

- 一个概念全文只用一个词。
- 不用「进行」「加以」加动词。直接用动词。
- 操作句不超过 25 字，描述句不超过 40 字。
- 操作句用祈使句，动词开头，不写「请」「您」「用户需要」。
- 条件写在动作前面。警告独立成段，放在步骤前。
- 不用数字后的「以上」「以下」，写「大于」「不小于」。
- 「打开」只用于文件和窗口。功能用「启用」，程序用「启动」。
- 「可以」只表示允许。能力用「支持」。

## 给 AI 用

### 装成技能

用 [skills](https://github.com/vercel-labs/skills) 安装器：

```bash
npx skills add mzopedia/simplified-technical-chinese
```

或手动复制。Claude Code 的全局技能目录是 `~/.claude/skills/`：

```bash
git clone --depth 1 https://github.com/mzopedia/simplified-technical-chinese.git ~/.claude/skills/simplified-technical-chinese
```

装好后，agent 在写中文技术说明时会按规范写，并在保存成文件后运行检查脚本。

### 直接写进提示词

不装技能时，把下面这段放进系统提示或对话里：

```text
用简明技术中文回答。规则：一句只说一件事，操作句不超过 25 字，描述句不超过 40 字；操作步骤用编号列表，动词开头，不写「请」「您」；用主动句；条件写在动作前面；一个概念全文只用一个词；不用「进行」「相关」「等」「以上」「尽快」「大概」；不用反问和感叹；数字后不用「以上」「以下」，写「大于」「不小于」。
```

这对应规范的常规模式，也就是 Karpathy 说的「做到八成」。要全部规则时，把 [规范.md](规范.md) 整个给模型。

## 给人用

读 [规范.md](规范.md)。写完后用检查脚本过一遍：

```bash
python3 tools/check.py 文档.md
```

在 CI 里用 `--strict`，有【必须】级别的发现时退出码为 1：

```bash
python3 tools/check.py --strict docs/*.md
```

## 检查脚本

```text
python3 tools/check.py 文件.md [更多文件]
    --strict               有【必须】级别的发现时退出码为 1
    --json                 JSON 输出
    --kind 操作|描述        强制按一种句型检查。聊天回答用「描述」
    --max-op 25            操作句字数上限
    --max-desc 40          描述句字数上限
    --no-vocab             不检查词表
    --check-counterexamples  也检查「不批准：」开头的反例行
```

脚本能稳定查出的：

- 禁用词，以及选词表中标为自动检查的词
- 句长、段落句数
- 被动标记、双重否定、条件后置、开放列举
- 相对时间、中文数字、「倍」表示减少
- 步骤里的警告和原因

脚本查不出的：事实是否正确、术语选得对不对、逻辑顺序、一词一义限定。它用编号列表项判断操作句，用「的」的数量近似长定语。所有发现都要人工确认。

脚本不检查的内容：

- 「」里的内容，按界面文字处理
- 代码块和行内代码
- 文件开头的 YAML front matter
- 以「不批准：」「反例」「改写前」开头的行
- `<!-- stc:off -->` 和 `<!-- stc:on -->` 之间的内容；`<!-- stc:skip -->` 跳过它后面的一段

## 和 ASD-STE100 的关系

- 方法来自 STE：一词一义、句长限制、祈使句、条件在前、段落句数、不用开放列举。
- 规则是按中文重写的。中文没有时态和词形变化，但有自己的歧义来源。例如名词化结构、长定语、「以上」的端点歧义、「可以」的许可和能力歧义。对应关系见规范的附录 B。
- ASD-STE100 是注册商标。本项目不使用这个名字，不暗示与 ASD 有关系，也不表示符合本规范的文本符合 ASD-STE100。

## 和现有项目的区别

| 项目 | 管什么 | 本项目的关系 |
| --- | --- | --- |
| [ruanyf/document-style-guide](https://github.com/ruanyf/document-style-guide) | 标题、段落、数值、标点、文档结构 | 互补。本规范不管排版 |
| [yikeke/zh-style-guide](https://github.com/yikeke/zh-style-guide) | 语言风格、标点、文档元素 | 互补 |
| [Fenng/Tech-Doc-Style-Chinese](https://github.com/Fenng/Tech-Doc-Style-Chinese) | 事实保真、改写流程、术语排版，有一节受控写作原则 | 它有 6 条原则和改写样例，没有编号规则和词表，并且明确不把句长做成硬规则。本项目做的正是这部分 |

写完整文档时，建议三者配合：用本规范管句子和用词，用上面的项目管排版和结构。

## 状态

草案 0.1。规范、词表说明、本文件和 SKILL.md 自身都通过了检查脚本（0 条【必须】）。

已知问题：

- 句长阈值（操作句 25 字、描述句 40 字）和定语字数（15 字）是草案值，没有经过阅读实验校准。
- 词表约 150 条，只覆盖通用技术写作。
- 没有做过阅读理解的对照实验。
- 检查脚本只做句法层面的检查。

## 参与

提一个词的方法：开 issue，写清四项：词、意义、建议的处理（禁用 / 选词 / 限定）、一个例句。

改词表时保持表格的列顺序，「自动检查」列只填「是」或「否」。改完运行测试：

```bash
python3 -m unittest discover tests
```

## 许可

- 规范和词表的文本：[CC BY 4.0](LICENSE-CC-BY-4.0)
- 检查脚本和测试：[MIT](LICENSE)
