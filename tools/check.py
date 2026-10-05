#!/usr/bin/env python3
"""简明技术中文检查脚本。

零依赖，Python 3.9 及以上。读取 Markdown 或纯文本，按《简明技术中文规范》
和《词表》检查，输出每条发现的行号、规则号、级别和说明。

用法：
    python3 tools/check.py 文件.md [更多文件...]
    python3 tools/check.py --strict 文件.md      # 有【必须】级别的发现时退出码为 1
    python3 tools/check.py --json 文件.md        # JSON 输出
    python3 tools/check.py --kind 描述 回答.md    # 把全文按描述句检查（例如聊天回答）
    cat 回答.md | python3 tools/check.py -

脚本只做句法层面的检查，不判断事实是否正确。所有发现都需要人工确认。
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VOCAB = os.path.normpath(os.path.join(HERE, "..", "词表.md"))

MUST = "必须"
SHOULD = "建议"

CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
LATIN_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+\-/]*")
ORDERED_ITEM = re.compile(r"^(\s*)(\d+)(?:[.)]\s+|[、）]\s*)(.*)$")
BULLET_ITEM = re.compile(r"^(\s*)[-*+]\s+(.*)$")
SENTENCE_SPLIT = re.compile(r"(?<=[。！？])(?![」』”’）)])")

# 系统行为句的常见主语。编号步骤里以这些词开头的句子不按操作句检查（规则 4.4）。
SYSTEM_SUBJECTS = ("系统", "服务", "接口", "程序", "页面", "浏览器", "终端", "客户端", "服务端", "命令", "脚本")


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    level: str
    message: str
    text: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}][{self.level}] {self.message}  ←「{self.text}」"


@dataclass
class Unit:
    """一个检查单元：一个段落、一个列表项、一个标题或一行表格。"""

    kind: str  # para | ordered | bullet | heading | table | quote
    lines: List[str]
    start_line: int
    indented: bool = False  # 首行有缩进。缩进的单元跟随前一个顶层单元的反例状态
    skip: bool = False  # 前面有 <!-- stc:skip --> 指令


# ---------------------------------------------------------------------------
# 词表
# ---------------------------------------------------------------------------

# 依赖语境的词用这里的正则替代简单匹配。键是词表中的词。
PATTERNS: Dict[str, str] = {
    "进行": r"进行(?!中|时|曲|到底)",
    "相关": r"相关(?!性|系数|联)",
    "等": r"(?:、[^、，。；：\n]{1,16}|(?:和|及|以及)[^，。；\n]{1,16})等(?:等)?(?!待|候|级|于|同|价|号|式|效|比|分|距|量|温|高|长|边|到|着)",
    "以上": r"\d\s*(?:个|次|秒|天|分钟|小时|倍|字|条|项|人|行|位|%|MB|GB|KB|TB|ms)?\s*以上",
    "以下": r"\d\s*(?:个|次|秒|天|分钟|小时|倍|字|条|项|人|行|位|%|MB|GB|KB|TB|ms)?\s*以下",
    "以内": r"\d[^。，；\n]{0,6}以内",
    "左右": r"[\d个次秒天钟时元倍%米克条]\s*左右",
    "及时": r"及时(?!性)",
    "基本": r"基本(?=兼容|可用|可以|没有|不|都|相同|一致|正常|完成|稳定|无|能)",
    "比较": r"比较(?=快|慢|大|小|多|少|高|低|长|短|好|差|稳定|复杂|简单|常见|重要|容易|困难|新|旧|久|频繁)",
    "相对": r"相对(?=快|慢|大|小|多|少|高|低|简单|复杂|稳定|较|容易|困难)",
    "相当": r"相当(?!于)",
    "十分": r"十分(?!钟)",
    "千万": r"千万(?!级|个|条|元|人|次|行|亿)",
    "最好": r"最好(?!的)",
    "请": r"(?<![申邀聘宴])请(?!求|假|教|示|柬|帖)",
    "展示": r"展示(?!层)",
    "需要": r"^需要(?!不)",
    "需": r"^需(?!要|求|不)",
    "落地": r"落地(?!页|窗)",
    "一些": r"(?<!这)一些",
    "一下": r"一下(?!子)",
    "显然": r"显然(?!易见)",
    "注销": r"注销(?!账号|帐号)",
    "开启": r"开启",
    "去除": r"去除(?!噪|重)",
    "选取": r"选取(?!区域|范围)",
}

# 词的检查范围。op：只在操作句；ordered：只在编号列表项；para：只在正文段落。
SCOPE: Dict[str, str] = {
    "请": "op",
    "您": "op",
    "你": "op",
    "需要": "op",
    "需": "op",
    "用户可以": "op",
    "用户需要": "op",
    "然后": "ordered",
    "接着": "ordered",
    "之后再": "ordered",
    "并且": "ordered",
    "而且": "ordered",
    "同时": "ordered",
    "首先": "para",
    "其次": "para",
    "最后": "para",
}

# 禁用词对应的规则号。没有列出的默认为 1.3。
RULE_OF_WORD: Dict[str, str] = {
    "进行": "1.4", "加以": "1.4", "作出": "1.4", "做出": "1.4", "予以": "1.4",
    "非常": "1.5", "很": "1.5", "极其": "1.5", "相当": "1.5", "十分": "1.5",
    "比较": "1.5", "较为": "1.5", "相对": "1.5", "大量": "1.5", "少量": "1.5",
    "大部分": "1.5", "多数": "1.5", "少数": "1.5", "尽快": "1.5", "及时": "1.5",
    "适当": "1.5", "合适": "1.5", "适量": "1.5", "基本": "1.5", "基本上": "1.5",
    "赋能": "1.7", "抓手": "1.7", "闭环": "1.7", "拉通": "1.7", "打通": "1.7",
    "沉淀": "1.7", "落地": "1.7", "赛道": "1.7", "心智": "1.7", "兜底": "1.7",
    "收口": "1.7", "透传": "1.7", "颗粒度": "1.7",
    "打法": "1.7", "组合拳": "1.7", "痛点": "1.7", "牵头": "1.7", "倒逼": "1.7",
    "体感": "1.7", "拉齐": "1.7", "对标": "1.7", "顶层设计": "1.7", "底层逻辑": "1.7",
    "请": "2.3", "您": "2.3", "你": "2.3", "需要": "2.3", "需": "2.3",
    "用户可以": "2.3", "用户需要": "2.3", "应该": "2.3", "应当": "2.3",
    "然后": "4.1", "接着": "4.1", "之后再": "4.1", "并且": "4.1", "而且": "4.1", "同时": "4.1",
    "首先": "3.3", "其次": "3.3", "最后": "3.3",
    "等": "3.5",
    "以上": "5.2", "以下": "5.2", "以内": "5.2",
    "大概": "5.4", "大约": "5.4", "左右": "5.4", "若干": "5.4", "一些": "5.4", "多次": "5.4",
}


@dataclass
class VocabEntry:
    words: List[str]
    replace: str
    note: str
    rule: str
    kind: str  # banned | choice


def _parse_tables(md: str) -> Dict[str, List[List[str]]]:
    sections: Dict[str, List[List[str]]] = {}
    current: Optional[str] = None
    for raw in md.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        sections[current].append(cells)
    return sections


def load_vocab(path: str = DEFAULT_VOCAB) -> List[VocabEntry]:
    """读取词表，返回标为「自动检查：是」的条目。"""
    with open(path, encoding="utf-8") as f:
        sections = _parse_tables(f.read())
    entries: List[VocabEntry] = []
    for title, rows in sections.items():
        if "第一部分" in title:
            for cells in rows[1:]:
                if len(cells) < 4 or cells[3] != "是":
                    continue
                words = [w for w in cells[0].split("、") if w]
                for w in words:
                    entries.append(VocabEntry([w], cells[1], cells[2], RULE_OF_WORD.get(w, "1.3"), "banned"))
        elif "第二部分" in title:
            for cells in rows[1:]:
                if len(cells) < 4 or cells[3] != "是":
                    continue
                rejected = [w for w in cells[2].split("、") if w]
                for w in rejected:
                    entries.append(VocabEntry([w], cells[1], cells[0], "1.1", "choice"))
    return entries


# ---------------------------------------------------------------------------
# 文本预处理
# ---------------------------------------------------------------------------

COUNTEREXAMPLE_PREFIXES = ("不批准", "不推荐", "反例", "错误示例", "改写前")


def strip_markup(line: str) -> str:
    """去掉 Markdown 标记。行内代码记为 CODE，「」里的内容记为 Q。

    「」里的内容是界面文字或被引用的词，按原样保留，不检查。
    """
    line = re.sub(r"`[^`]*`", " CODE ", line)
    line = re.sub(r"「[^」]*」", "「Q」", line)
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", line)
    line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"https?://\S+", " URL ", line)
    line = re.sub(r"<[^>]+>", " ", line)
    line = re.sub(r"(\*\*|~~|\*)(?=\S)", "", line)
    line = re.sub(r"(?<=\S)(\*\*|~~|\*)", "", line)
    return line


def is_counterexample(text: str) -> bool:
    """以「不批准：」这类前缀开头的行是反例，默认不检查。"""
    return text.lstrip("-*+ \t").startswith(COUNTEREXAMPLE_PREFIXES)


def count_chars(text: str) -> int:
    """按附录 A 计算字数。"""
    text = re.sub(r"`[^`]*`", " CODE ", text)
    return len(CJK.findall(text)) + len(LATIN_TOKEN.findall(text))


def split_sentences(text: str) -> List[str]:
    parts = SENTENCE_SPLIT.split(text)
    return [p.strip() for p in parts if p and p.strip()]


DIRECTIVE = re.compile(r"^\s*<!--\s*stc:(off|on|skip)\s*-->\s*$")


def parse_units(lines: List[str]) -> List[Unit]:
    """把文本切成检查单元。

    跳过：代码块、文件开头的 YAML front matter、`<!-- stc:off -->` 到
    `<!-- stc:on -->` 之间的内容。`<!-- stc:skip -->` 跳过它后面的一个单元。
    """
    units: List[Unit] = []
    in_fence = False
    off = False
    skip_next = False
    current: Optional[Unit] = None

    def close() -> None:
        nonlocal current
        if current is not None:
            units.append(current)
            current = None

    def start(kind: str, text: str, idx: int, raw: str) -> Unit:
        nonlocal skip_next
        unit = Unit(kind, [text], idx, indented=raw[:1] in (" ", "\t"), skip=skip_next)
        skip_next = False
        return unit

    start_at = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start_at = i + 1
                break

    in_comment = False
    for idx, raw in enumerate(lines[start_at:], start=start_at + 1):
        if in_comment:
            if "-->" not in raw:
                continue
            in_comment = False
            raw = raw.split("-->", 1)[1]
        d = DIRECTIVE.match(raw)
        if d is None and "<!--" in raw:
            # HTML 注释不是读者看到的内容。整行或行内的注释去掉；跨行注释到 --> 为止都跳过
            raw = re.sub(r"<!--.*?-->", "", raw)
            if "<!--" in raw:
                raw = raw.split("<!--", 1)[0]
                in_comment = True
        stripped = raw.strip()
        if d:
            close()
            if d.group(1) == "off":
                off = True
            elif d.group(1) == "on":
                off = False
            else:
                skip_next = True
            continue
        if off:
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            close()
            continue
        if in_fence:
            continue
        if not stripped:
            close()
            continue
        if stripped.startswith("#"):
            close()
            units.append(start("heading", stripped.lstrip("#").strip(), idx, raw))
            continue
        if stripped.startswith("|"):
            close()
            units.append(start("table", stripped, idx, raw))
            continue
        if stripped.startswith(">"):
            text = stripped.lstrip(">").strip()
            if current is not None and current.kind == "quote":
                current.lines.append(text)
            else:
                close()
                current = start("quote", text, idx, raw)
            continue
        m = ORDERED_ITEM.match(raw)
        if m:
            close()
            current = start("ordered", m.group(3).strip(), idx, raw)
            continue
        m = BULLET_ITEM.match(raw)
        if m:
            close()
            current = start("bullet", m.group(2).strip(), idx, raw)
            continue
        if current is not None and current.kind in ("ordered", "bullet") and raw.startswith(("  ", "\t")):
            current.lines.append(stripped)
            continue
        if current is not None and current.kind == "para":
            current.lines.append(stripped)
        else:
            close()
            current = start("para", stripped, idx, raw)
    close()
    return units


# ---------------------------------------------------------------------------
# 规则
# ---------------------------------------------------------------------------

class Checker:
    def __init__(self, vocab: Optional[List[VocabEntry]], max_op: int = 25, max_desc: int = 40,
                 kind: str = "auto", skip_counterexamples: bool = True) -> None:
        self.vocab = vocab or []
        self.max_op = max_op
        self.max_desc = max_desc
        self.kind = kind
        self.skip_counterexamples = skip_counterexamples
        self._compiled = [(e, re.compile(PATTERNS.get(e.words[0], re.escape(e.words[0])))) for e in self.vocab]

    # -- 入口 --------------------------------------------------------------

    def check_text(self, text: str, path: str = "<text>") -> List[Finding]:
        units = parse_units(text.splitlines())
        findings: List[Finding] = []
        checked: List[Unit] = []
        in_counterexample = False
        for unit in units:
            if not unit.indented:
                in_counterexample = self.skip_counterexamples and is_counterexample(unit.lines[0])
            if in_counterexample or unit.skip:
                continue
            checked.append(unit)
            findings.extend(self._check_unit(unit, path))
        findings.extend(self._check_acronyms(checked, path))
        findings = self._dedupe(findings)
        findings.sort(key=lambda f: (f.line, f.rule))
        return findings

    def check_file(self, path: str) -> List[Finding]:
        with open(path, encoding="utf-8") as f:
            return self.check_text(f.read(), path)

    # -- 单元 --------------------------------------------------------------

    def _check_unit(self, unit: Unit, path: str) -> List[Finding]:
        out: List[Finding] = []
        clean_lines = [strip_markup(l) for l in unit.lines]
        if unit.kind in ("heading", "table"):
            for offset, line in enumerate(clean_lines):
                out.extend(self._check_vocab(line, unit.start_line + offset, path, op=False, unit_kind=unit.kind))
            return out

        sentences: List[tuple] = []  # (sentence, line_no)
        for offset, line in enumerate(clean_lines):
            for s in split_sentences(line):
                sentences.append((s, unit.start_line + offset))

        # 3.2 段落句数
        if unit.kind == "para" and len(sentences) > 6:
            out.append(Finding(path, unit.start_line, "3.2", MUST,
                               f"一段有 {len(sentences)} 句，不超过 6 句", clean_lines[0][:30]))

        # 3.3 正文里串联步骤
        if unit.kind == "para":
            joined = "".join(clean_lines)
            if "首先" in joined and re.search(r"然后|其次|最后|接着", joined):
                out.append(Finding(path, unit.start_line, "3.3", MUST,
                                   "正文用「首先……然后……」串联步骤，改用编号列表", clean_lines[0][:30]))

        for pos, (sentence, line_no) in enumerate(sentences):
            op = self._is_operation(unit, sentence, pos)
            out.extend(self._check_sentence(sentence, line_no, path, op, unit.kind))
            out.extend(self._check_vocab(sentence, line_no, path, op, unit.kind))
        return out

    def _is_operation(self, unit: Unit, sentence: str, pos: int) -> bool:
        if self.kind == "操作":
            return True
        if self.kind == "描述":
            return False
        if unit.kind != "ordered":
            return False
        if sentence.startswith(SYSTEM_SUBJECTS):
            return False
        return True

    # -- 句子规则 ----------------------------------------------------------

    def _check_sentence(self, s: str, line: int, path: str, op: bool, unit_kind: str) -> List[Finding]:
        out: List[Finding] = []
        n = count_chars(s)
        excerpt = s[:40]

        # 2.1 句长
        limit = self.max_op if op else self.max_desc
        label = "操作句" if op else "描述句"
        if n > limit:
            out.append(Finding(path, line, "2.1", MUST, f"{label} {n} 字，不超过 {limit} 字", excerpt))

        # 2.2 一句多事
        connectors = re.findall(r"然后|并且|而且|接着|随后|之后", s)
        if not op and len(connectors) >= 2:
            out.append(Finding(path, line, "2.2", MUST, "一句里有多个动作，拆句", excerpt))

        # 2.3 操作句的祈使形式
        if op and re.match(r"^(用户|使用者|管理员|开发者)(需要|可以|应该|应当|必须)", s):
            out.append(Finding(path, line, "2.3", MUST, "操作句用祈使句，去掉主语和「需要」「可以」", excerpt))

        # 2.4 被动
        passive = re.search(r"被(?!动|告|迫|称为|视为|子|窝|套|褥|面)|受到|遭到|(?<![因认成作称以改行])为[^，。]{1,10}所(?!以|有|属|在|需|谓|得|做|作|用|说|示|述|处|含|致|知|见|愿)", s)
        if passive is None:
            passive = re.search(r"由[^，。于来此]{1,8}(?:负责|完成|执行|生成|处理|发送|收集|读取|管理|维护|调用|触发|创建|返回|接管|承担)", s)
        if passive:
            level = MUST if op else SHOULD
            out.append(Finding(path, line, "2.4", level, "被动句，改为主动句并写出执行者", excerpt))

        # 2.5 条件在后
        cond = r"(?:如果|若(?!干)|假如|当(?!前|时|天|地|然|中|作|成))"
        if re.search(r"[，,]\s*" + cond + r"[^，。]{1,20}$", s) or re.search(r"[（(]\s*" + cond + r"[^）)]*[）)]", s):
            out.append(Finding(path, line, "2.5", MUST, "条件写在动作后面，移到动作前", excerpt))

        # 2.6 否定
        if re.search(r"不得不|不无|未尝不|无不|不能不|不会不|没有[^，。]{0,6}不|不[^，。]{0,4}不是不", s):
            out.append(Finding(path, line, "2.6", MUST, "双重否定，改为肯定句", excerpt))
        else:
            negs = re.findall(r"不要|不能|不得|不会|没有|无法|禁止", s)
            if len(negs) >= 2:
                out.append(Finding(path, line, "2.6", SHOULD, "一句里有多个否定，确认否定范围", excerpt))

        # 2.7 长定语（用「的」的数量近似）
        if s.count("的") >= 4:
            out.append(Finding(path, line, "2.7", SHOULD, "一句里有 4 个以上「的」，可能有长定语", excerpt))

        # 2.8 指代
        if "上述" in s:
            out.append(Finding(path, line, "2.8", MUST, "「上述」指代不明，重复名词", excerpt))
        pron = re.findall(r"(?<![尤与及极])其(?!他|它|中|次|实|余|间|后|前|内|外|上|下|名|实)|(?<!应)该(?!死)|(?<![因如由从彼至于])此(?!外)|它|这个", s)
        if len(pron) >= 2:
            out.append(Finding(path, line, "2.8", SHOULD, "一句里有多个指代词，确认指代对象在上一句", excerpt))

        # 2.9 反问、设问、感叹
        if s.endswith(("？", "?", "！", "!")) and unit_kind != "heading":
            out.append(Finding(path, line, "2.9", MUST, "不用问句和感叹句", excerpt))
        if re.search(r"难道|岂不|何必", s):
            out.append(Finding(path, line, "2.9", MUST, "反问，改为陈述句", excerpt))

        # 4.3 警告混在步骤里
        if unit_kind == "ordered" and re.search(r"注意|警告|小心", s):
            out.append(Finding(path, line, "4.3", MUST, "警告写在步骤里，独立成段并放在步骤前", excerpt))

        # 4.5 括号里的前置条件
        if unit_kind == "ordered" and re.search(r"[（(][^）)]*(?:需要|要求|前提|不低于|版本|权限)[^）)]*[）)]", s):
            out.append(Finding(path, line, "4.5", SHOULD, "前置条件写在括号里，单独列出", excerpt))

        # 4.6 步骤里解释原因
        if unit_kind == "ordered" and re.search(r"因为|由于|原因是", s):
            out.append(Finding(path, line, "4.6", SHOULD, "步骤里解释原因，移到步骤前后的说明段", excerpt))

        # 5.1 中文数字和「百分之」
        units = r"(?:秒|分钟|小时|天|周|次|倍|行|列|位|字节|毫秒)"
        if re.search(r"(?<![一十第])[一二三四五六七八九十两]+" + units + r"(?!钟|数|性)", s):
            out.append(Finding(path, line, "5.1", MUST, "用阿拉伯数字", excerpt))
        if "百分之" in s:
            out.append(Finding(path, line, "5.1", MUST, "「百分之」改为 %", excerpt))
        if re.search(r"\d(?:MB|GB|KB|TB|ms|px)\b", s):
            out.append(Finding(path, line, "5.1", SHOULD, "数字与单位之间空一格", excerpt))

        # 5.3 相对时间
        if re.search(r"明天|后天|昨天|前天|下周|上周|下个月|上个月|近期|稍后|过几天|不久", s):
            out.append(Finding(path, line, "5.3", MUST, "相对时间，改为绝对日期或时长", excerpt))

        # 5.4 操作句里的估计词
        if op and re.search(r"(?<![预节合契违签])约(?!束|定|会|谈|稿)|几(?=次|个|秒|分钟|天|行|台|分)", s):
            out.append(Finding(path, line, "5.4", MUST, "操作句里有估计词，写出数值", excerpt))

        # 5.5 倍数表示减少
        if re.search(r"(?:降低|减少|下降|缩小|降)[^，。]{0,6}\d+\s*倍", s):
            out.append(Finding(path, line, "5.5", MUST, "减少不用「倍」，用「减少到原来的 1/n」或百分比", excerpt))

        # 6.1 界面元素名
        if op and re.search(r"点击(?!\s*「|\s*『|\s*CODE)", s):
            out.append(Finding(path, line, "6.1", SHOULD, "界面元素名用「」括起", excerpt))

        return out

    # -- 词表 --------------------------------------------------------------

    def _check_vocab(self, s: str, line: int, path: str, op: bool, unit_kind: str) -> List[Finding]:
        out: List[Finding] = []
        for entry, pattern in self._compiled:
            scope = SCOPE.get(entry.words[0])
            if scope == "op" and not op:
                continue
            if scope == "ordered" and unit_kind != "ordered":
                continue
            if scope == "para" and unit_kind != "para":
                continue
            m = pattern.search(s)
            if not m:
                continue
            word = entry.words[0]
            if entry.kind == "banned":
                msg = f"禁用词「{word}」，改用：{entry.replace}"
            else:
                msg = f"「{word}」改用「{entry.replace}」（{entry.note}）"
            out.append(Finding(path, line, entry.rule, MUST, msg, s[:40]))
        return out

    # -- 文件级 ------------------------------------------------------------

    def _check_acronyms(self, units: List[Unit], path: str) -> List[Finding]:
        seen: Dict[str, Dict[str, int]] = {}
        for unit in units:
            for offset, raw in enumerate(unit.lines):
                idx = unit.start_line + offset
                clean = re.sub(r"`[^`]*`", " ", raw)
                clean = re.sub(r"https?://\S+", " ", clean)
                for tok in re.findall(r"\b[A-Za-z]{2,}\b", clean):
                    variants = seen.setdefault(tok.lower(), {})
                    variants.setdefault(tok, idx)
        out: List[Finding] = []
        for key, variants in seen.items():
            if len(variants) > 1 and any(v.isupper() for v in variants):
                forms = "、".join(sorted(variants))
                first = min(variants.values())
                out.append(Finding(path, first, "1.6", SHOULD, f"缩写写法不一致：{forms}", key))
        return out

    @staticmethod
    def _dedupe(findings: List[Finding]) -> List[Finding]:
        seen = set()
        out = []
        for f in findings:
            key = (f.line, f.rule, f.message)
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
        return out


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="简明技术中文检查脚本")
    parser.add_argument("files", nargs="+", help="要检查的文件；用 - 表示标准输入")
    parser.add_argument("--strict", action="store_true", help="有【必须】级别的发现时退出码为 1")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--kind", choices=["auto", "操作", "描述"], default="auto",
                        help="句子类型。auto：编号列表项按操作句，其他按描述句")
    parser.add_argument("--vocab", default=DEFAULT_VOCAB, help="词表路径")
    parser.add_argument("--no-vocab", action="store_true", help="不检查词表")
    parser.add_argument("--max-op", type=int, default=25, help="操作句字数上限，默认 25")
    parser.add_argument("--max-desc", type=int, default=40, help="描述句字数上限，默认 40")
    parser.add_argument("--quiet", action="store_true", help="只输出汇总")
    parser.add_argument("--check-counterexamples", action="store_true",
                        help="也检查以「不批准：」「反例」等开头的行。默认跳过")
    args = parser.parse_args(argv)

    vocab = None if args.no_vocab else load_vocab(args.vocab)
    checker = Checker(vocab, args.max_op, args.max_desc, args.kind,
                      skip_counterexamples=not args.check_counterexamples)

    findings: List[Finding] = []
    for path in args.files:
        if path == "-":
            findings.extend(checker.check_text(sys.stdin.read(), "<stdin>"))
        else:
            findings.extend(checker.check_file(path))

    must = sum(1 for f in findings if f.level == MUST)
    should = len(findings) - must

    if args.json:
        print(json.dumps({"findings": [asdict(f) for f in findings], "必须": must, "建议": should},
                         ensure_ascii=False, indent=2))
    else:
        if not args.quiet:
            for f in findings:
                print(f.format())
        print(f"共 {len(findings)} 条：{MUST} {must}，{SHOULD} {should}")

    if args.strict and must > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
