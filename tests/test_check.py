"""检查脚本的回归测试。运行：python3 -m unittest discover tests"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import check  # noqa: E402


def rules(findings):
    return {f.rule for f in findings}


class TestCount(unittest.TestCase):
    def test_appendix_a_examples(self):
        self.assertEqual(check.count_chars("重启服务。"), 4)
        self.assertEqual(check.count_chars("把 `max_connections` 改为 200。"), 5)

    def test_latin_tokens_count_one(self):
        self.assertEqual(check.count_chars("使用 API v2.0 和 UTF-8 编码"), 8)


class TestVocab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vocab = check.load_vocab()
        cls.checker = check.Checker(cls.vocab)

    def test_vocab_loads(self):
        self.assertGreater(len(self.vocab), 80)
        kinds = {e.kind for e in self.vocab}
        self.assertEqual(kinds, {"banned", "choice"})

    def test_jinxing_flagged(self):
        f = self.checker.check_text("对配置文件进行修改。")
        self.assertIn("1.4", rules(f))

    def test_jinxing_zhong_not_flagged(self):
        f = self.checker.check_text("任务进行中。")
        self.assertNotIn("1.4", rules(f))

    def test_yishang_after_digit(self):
        f = self.checker.check_text("并发数 100 以上。")
        self.assertIn("5.2", rules(f))

    def test_yishang_without_digit(self):
        f = self.checker.check_text("以上步骤完成后，服务可用。")
        self.assertNotIn("5.2", rules(f))

    def test_deng_enumeration(self):
        f = self.checker.check_text("支持 MySQL、PostgreSQL 等数据库。")
        self.assertIn("3.5", rules(f))

    def test_deng_not_enumeration(self):
        f = self.checker.check_text("等待 3 秒。")
        self.assertNotIn("3.5", rules(f))
        f = self.checker.check_text("保存文件、关闭窗口，等待 3 秒。")
        self.assertNotIn("3.5", rules(f))

    def test_quoted_text_is_skipped(self):
        f = self.checker.check_text("不写「请」「您」「进行」。")
        self.assertEqual([x for x in f if x.level == check.MUST], [])

    def test_nested_counterexample_is_skipped(self):
        text = "- 不批准：\n  1. 请进行安装，然后重启。\n- 批准：\n  1. 安装。\n  2. 重启。\n"
        self.assertEqual(self.checker.check_text(text), [])

    def test_front_matter_and_directives_are_skipped(self):
        text = "---\ndescription: 请进行安装\n---\n\n<!-- stc:off -->\n请进行安装。\n<!-- stc:on -->\n\n<!-- stc:skip -->\n请进行安装。\n\n安装。\n"
        self.assertEqual(self.checker.check_text(text), [])

    def test_html_comments_are_skipped(self):
        text = "\n".join([
            "<!--",
            "这里的内容进行测试，不应该被检查。",
            "-->",
            "中文句子。<!-- 行内注释里的进行 -->",
            "<!-- 多行",
            "注释开始",
            "--> 注释后的进行修改。",
        ])
        f = self.checker.check_text(text)
        self.assertEqual([(x.rule, x.line) for x in f], [("1.4", 7)])

    def test_counterexample_line_is_skipped(self):
        f = self.checker.check_text("- 不批准：对配置文件进行修改。")
        self.assertEqual(f, [])
        strict = check.Checker(self.vocab, skip_counterexamples=False)
        self.assertIn("1.4", rules(strict.check_text("- 不批准：对配置文件进行修改。")))

    def test_qing_only_in_operation(self):
        f = self.checker.check_text("1. 请点击「保存」。")
        self.assertIn("2.3", rules(f))
        f = self.checker.check_text("这里不是操作句，请求参数如下。")
        self.assertNotIn("2.3", rules(f))

    def test_choice_word(self):
        f = self.checker.check_text("单击「保存」。")
        msgs = [x.message for x in f if x.rule == "1.1"]
        self.assertTrue(any("点击" in m for m in msgs))

    def test_jargon_is_rule_1_7(self):
        f = self.checker.check_text("按新打法对标行业方案，把握用户痛点，理清底层逻辑。")
        hits = [x for x in f if x.rule == "1.7"]
        self.assertEqual(len(hits), 4)
        # 痛点常有正当用法，降为建议；其余是必须
        self.assertEqual(sum(x.level == check.MUST for x in hits), 3)
        self.assertEqual(sum(x.level == check.SHOULD for x in hits), 1)

    def test_words_with_technical_meaning_are_not_banned(self):
        # 势能、飞轮、护城河 标为不自动检查；脚手架、收敛 只在词表第三部分限定意义
        f = self.checker.check_text("弹簧的势能转化为动能。用脚手架生成项目。迭代 20 次后误差收敛。")
        self.assertNotIn("1.7", rules(f))
        self.assertNotIn("1.3", rules(f))

    def test_zhuxiao_account_allowed(self):
        f = self.checker.check_text("注销账号后数据不可恢复。")
        self.assertFalse(any("注销" in x.message for x in f))

    def test_ranhou_only_in_ordered(self):
        f = self.checker.check_text("1. 打开终端，然后运行命令。")
        self.assertIn("4.1", rules(f))
        f = self.checker.check_text("服务读取配置，然后连接数据库。")
        self.assertNotIn("4.1", rules(f))

    def test_substring_matches_are_not_banned_words(self):
        for text in ["可以传入参数，生成对应的值。", "坐标位置不准确。", "添加以下参数。", "我们不得不为此调整。",
                     "为其实施写保护。", "你不一定要从零开始。", "节点选择完全受控。", "针对标识符的定义。", "一千万行数据。"]:
            f = [x for x in self.checker.check_text(text) if x.rule in ("1.1", "1.3", "1.4", "1.7")]
            self.assertEqual(f, [], text)

    def test_degree_and_estimate_words_only_in_operations(self):
        self.assertNotIn("1.5", rules(self.checker.check_text("大部分用户不用 beta 版。尽快升级。")))
        self.assertIn("1.5", rules(self.checker.check_text("1. 尽快重启服务。")))
        # 很、非常、合适这类词连操作句里也多是正常用法，不自动检查
        self.assertNotIn("1.5", rules(self.checker.check_text("1. 等待很长时间。")))
        self.assertNotIn("5.4", rules(self.checker.check_text("这会有大约 16 KB 的基本打包大小。")))
        self.assertIn("5.4", rules(self.checker.check_text("1. 重试若干次。")))
        self.assertIn("5.4", rules(self.checker.check_text("| 超时 | 大约 30 秒 |")))

    def test_modal_words_only_in_operations(self):
        self.assertNotIn("2.3", rules(self.checker.check_text("输出结果应该是这样。")))
        self.assertIn("2.3", rules(self.checker.check_text("1. 您需要先备份。")))
        # 你、应该在编号列表里多是说明不是步骤，不自动检查
        self.assertNotIn("2.3", rules(self.checker.check_text("1. 你应该先备份。")))

    def test_open_list_with_example_marker_is_allowed(self):
        self.assertNotIn("3.5", rules(self.checker.check_text("例如 Deployment、Service 等对象。")))
        self.assertIn("3.5", rules(self.checker.check_text("支持 MySQL、PostgreSQL 等数据库。")))

    def test_qingkuang_only_after_de(self):
        self.assertNotIn("1.3", rules(self.checker.check_text("默认情况下，服务监听 8080 端口。")))
        # 「在……的情况下」是固定搭配，不查；「的情况」单独出现才查
        self.assertNotIn("1.3", rules(self.checker.check_text("出现错误的情况下重试。")))
        self.assertIn("1.3", rules(self.checker.check_text("用 TiUP 部署的情况，见下文。")))


class TestSentenceRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checker = check.Checker(None)

    def test_length_operation(self):
        long_op = "1. 在确认数据库已经完成备份并且备份文件可以正常恢复之后登录到主服务器。"
        f = self.checker.check_text(long_op)
        self.assertIn("2.1", rules(f))

    def test_length_description_ok(self):
        f = self.checker.check_text("服务读取配置文件。")
        self.assertNotIn("2.1", rules(f))

    def test_system_subject_in_step_is_description(self):
        text = "1. 点击「提交」。系统生成订单号并写入数据库，然后发送通知邮件给管理员。"
        f = self.checker.check_text(text)
        # 第二句以「系统」开头，按描述句算，40 字以内不报 2.1
        self.assertNotIn("2.1", rules(f))

    def test_double_negation(self):
        # 校准后降为建议：「不得不」这类固定搭配模型多判为正常用法
        f = self.checker.check_text("不得不重启服务。")
        self.assertTrue(any(x.rule == "2.6" and x.level == check.SHOULD for x in f))

    def test_question_mark(self):
        f = self.checker.check_text("为什么服务起不来？")
        self.assertIn("2.9", rules(f))

    def test_exclamation_inside_quotes_ok(self):
        f = self.checker.check_text("系统显示「保存成功！」。")
        self.assertNotIn("2.9", rules(f))

    def test_condition_after_action(self):
        f = self.checker.check_text("1. 重启服务，如果修改了端口号。")
        self.assertTrue(any(x.rule == "2.5" and x.level == check.MUST for x in f))
        # 括号里的内容多是补充说明，校准后不再当条件
        self.assertNotIn("2.5", rules(self.checker.check_text("重启服务（如果修改了端口号）。")))

    def test_passive_in_operation_is_should(self):
        f = self.checker.check_text("1. 配置文件会被服务读取。")
        self.assertTrue(any(x.rule == "2.4" and x.level == check.SHOULD for x in f))
        # 「被 X 的 Y」是定语，不是被动谓语
        self.assertNotIn("2.4", rules(self.checker.check_text("1. 查看被拒绝的请求。")))

    def test_passive_in_description_is_not_checked(self):
        # 描述句里的被动多是执行者未知或不重要的合规用法，脚本分不出来，校准后只查操作句
        f = self.checker.check_text("配置文件会被服务读取。此选项已被弃用。")
        self.assertNotIn("2.4", rules(f))

    def test_passive_markers_inside_other_words_are_not_passive(self):
        # 来自 answer-me-with-html 维护者在 1000 篇中文文档上的实测误报。
        for text in ["把被子叠好。", "因为缓存所在目录不可写，任务失败。", "成为开发者所需的全部工具。", "系统所示的路径。"]:
            f = self.checker.check_text(text)
            self.assertNotIn("2.4", rules(f), text)

    def test_imperative_rule_skips_questions_and_nouns(self):
        for text in ["1. 需不需要重启，看日志。", "1. 用户表里新增一列。"]:
            f = self.checker.check_text(text)
            self.assertNotIn("2.3", rules(f), text)

    def test_reduce_by_times(self):
        f = self.checker.check_text("延迟降低了 3 倍。")
        self.assertIn("5.5", rules(f))

    def test_relative_time(self):
        f = self.checker.check_text("旧接口下周下线。")
        self.assertIn("5.3", rules(f))
        # 「稍后」「近期」在技术描述里多指程序时序，不是相对于写作时间的日期
        self.assertNotIn("5.3", rules(self.checker.check_text("保存当前值，以便稍后恢复。查看近期事件。")))

    def test_chinese_numeral(self):
        f = self.checker.check_text("等待三秒。")
        self.assertIn("5.1", rules(f))

    def test_paragraph_sentences(self):
        text = "一。二。三。四。五。六。七。"
        f = self.checker.check_text(text)
        self.assertIn("3.2", rules(f))

    def test_first_then_in_prose_is_not_checked(self):
        # 3.3 从脚本移除：正文里的「首先……然后……」多数在描述顺序，不是在写步骤（校准精确率 30%）
        f = self.checker.check_text("首先停止服务，然后备份数据，最后运行脚本。")
        self.assertNotIn("3.3", rules(f))

    def test_numerals(self):
        # 「一次」「两次」「一行」是量词习惯用法；三以上和两位数才查
        self.assertNotIn("5.1", rules(self.checker.check_text("只执行一次。这一行会报错。重试两次。")))
        self.assertIn("5.1", rules(self.checker.check_text("等待三秒。")))
        self.assertIn("5.1", rules(self.checker.check_text("保留二十行。")))

    def test_code_block_skipped(self):
        text = "```\n请进行安装，然后等等等。\n```\n"
        f = self.checker.check_text(text)
        self.assertEqual(f, [])

    def test_hard_wrapped_lines_form_one_sentence(self):
        # Markdown 里的硬换行不是句子边界：两行拼成一句 46 字，报一次 2.1，行号是句子开始的那行
        text = "第一句。这是一个被硬换行切开的很长的描述句，前半段写在这一行的末尾，\n后半段写在下一行，加起来超过四十个字。"
        f = [x for x in self.checker.check_text(text) if x.rule == "2.1"]
        self.assertEqual([(x.line, x.message[:8]) for x in f], [(1, "描述句 45 字")])

    def test_unpunctuated_lines_are_not_sentences(self):
        text = "\n".join(["基本"] * 8 + ["这些是组件示例的名字。"])
        self.assertNotIn("3.2", rules(self.checker.check_text(text)))
        self.assertNotIn("3.2", rules(self.checker.check_text("<code src=\"./demo/basic.tsx\">基本</code>\n" * 8)))


class TestExamples(unittest.TestCase):
    def setUp(self):
        self.checker = check.Checker(check.load_vocab())

    def test_before_has_many_findings(self):
        f = self.checker.check_file(os.path.join(ROOT, "examples", "before.md"))
        must = [x for x in f if x.level == check.MUST]
        self.assertGreaterEqual(len(must), 15)

    def test_after_has_no_must(self):
        f = self.checker.check_file(os.path.join(ROOT, "examples", "after.md"))
        must = [x for x in f if x.level == check.MUST]
        self.assertEqual(must, [], "\n".join(x.format() for x in must))


class TestCli(unittest.TestCase):
    def test_strict_exit_code(self):
        before = os.path.join(ROOT, "examples", "before.md")
        after = os.path.join(ROOT, "examples", "after.md")
        self.assertEqual(check.main(["--strict", "--quiet", before]), 1)
        self.assertEqual(check.main(["--strict", "--quiet", after]), 0)


if __name__ == "__main__":
    unittest.main()
