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
        self.assertTrue(all(x.level == check.MUST for x in hits))

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
        f = self.checker.check_text("不得不重启服务。")
        self.assertTrue(any(x.rule == "2.6" and x.level == check.MUST for x in f))

    def test_question_mark(self):
        f = self.checker.check_text("为什么服务起不来？")
        self.assertIn("2.9", rules(f))

    def test_exclamation_inside_quotes_ok(self):
        f = self.checker.check_text("系统显示「保存成功！」。")
        self.assertNotIn("2.9", rules(f))

    def test_condition_after_action(self):
        f = self.checker.check_text("重启服务（如果修改了端口号）。")
        self.assertIn("2.5", rules(f))

    def test_passive_in_operation_is_must(self):
        f = self.checker.check_text("1. 配置文件会被服务读取。")
        self.assertTrue(any(x.rule == "2.4" and x.level == check.MUST for x in f))

    def test_passive_in_description_is_should(self):
        f = self.checker.check_text("配置文件会被服务读取。")
        self.assertTrue(any(x.rule == "2.4" and x.level == check.SHOULD for x in f))

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
        f = self.checker.check_text("旧接口近期下线。")
        self.assertIn("5.3", rules(f))

    def test_chinese_numeral(self):
        f = self.checker.check_text("等待三秒。")
        self.assertIn("5.1", rules(f))

    def test_paragraph_sentences(self):
        text = "一。二。三。四。五。六。七。"
        f = self.checker.check_text(text)
        self.assertIn("3.2", rules(f))

    def test_first_then_in_prose(self):
        f = self.checker.check_text("首先停止服务，然后备份数据，最后运行脚本。")
        self.assertIn("3.3", rules(f))

    def test_warning_inside_step(self):
        f = self.checker.check_text("1. 运行清理脚本。注意脚本会删除日志。")
        self.assertIn("4.3", rules(f))

    def test_code_block_skipped(self):
        text = "```\n请进行安装，然后等等等。\n```\n"
        f = self.checker.check_text(text)
        self.assertEqual(f, [])

    def test_acronym_consistency(self):
        f = self.checker.check_text("配置 CDN。cdn 会缓存文件。")
        self.assertIn("1.6", rules(f))


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
