import copy
import unittest

from app import parser, prefilter


def message(raw, minute=0, **extra):
    value = dict(raw_text=raw, kind='text', sender='客户',
                 sent_at=f'2026-10-16T10:{minute:02d}:00+08:00', warnings=[])
    value.update(extra)
    return value


class PrefilterTests(unittest.TestCase):
    def test_only_certain_empty_and_media_noise(self):
        entries = [message(raw) for raw in (
            '', ' \r\n\t', '[图片]\r\n', '[语音]', 'config/media/picture.png',
            '[图片] 看这个报错', '[图片]\n[图片]', '[未知]', '😀',
        )]
        self.assertEqual(prefilter.classify(entries), [
            'empty', 'empty', 'media_placeholder', 'media_placeholder',
            'media_placeholder', None, None, None, None,
        ])

    def test_valid_short_answers_status_corrections_and_deadlines_survive(self):
        raw = [
            '正常了', '还是不行', '不是这个', '已调整', '收到', '好的', '有维护的',
            '没有', '是', '对', '1', 'T+1', '不支持', '可以', '不是', '已解决',
            '稍等', '已提交需求', '三个工作日', '明天下午反馈', '辛苦了', '这个？',
            '谢谢，但是仍然有问题', '你好，请问怎么登录', '正常了，谢谢',
            '谢谢？', '你好\n请帮忙', '订单状态为已完成', '字段叫 EndDate',
            'SELECT a.id\nFROM test_table a\nWHERE a.id = 1;',
        ]
        self.assertEqual(prefilter.classify([message(s) for s in raw]), [None] * len(raw))

    def test_isolated_whole_message_allowlist(self):
        raw = ['你好', '您好！', '大家好。', '谢谢', '多谢～', '谢谢您！']
        self.assertEqual(prefilter.classify([message(s) for s in raw]),
                         ['isolated_greeting'] * 3 + ['isolated_thanks'] * 3)

    def test_neighboring_business_preserves_greeting_and_thanks(self):
        entries = [message('你好', 0), message('登录失败，怎么处理？', 1),
                   message('重置密码后重试', 2), message('谢谢！', 3)]
        self.assertEqual(prefilter.classify(entries), [None] * 4)

    def test_social_runs_and_media_cannot_hide_business_context(self):
        entries = [message('登录正常了', 0)]
        entries += [message('你好', 1)] * 8
        entries += [message('[图片]', 2), message('谢谢', 3)]
        self.assertEqual(prefilter.classify(entries), [None] * 9 + ['media_placeholder', None])

    def test_unknown_short_phrase_is_context_without_business_keywords(self):
        self.assertEqual(prefilter.classify([message('有维护的'), message('谢谢', 1)]),
                         [None, None])

    def test_context_boundary_is_inclusive_and_checks_both_sides(self):
        self.assertEqual(prefilter.classify([message('登录恢复了'), message('谢谢', 30)]),
                         [None, None])
        self.assertEqual(prefilter.classify([message('登录恢复了'), message('谢谢', 31)]),
                         [None, 'isolated_thanks'])
        self.assertEqual(prefilter.classify([
            message('你好'), message('如何查询字段？', 31), message('谢谢', 32),
        ]), ['isolated_greeting', None, None])

    def test_unknown_or_inconsistent_timestamps_keep_social_context(self):
        cases = [
            [dict(raw_text='有维护的'), dict(raw_text='谢谢')],
            [message('有维护的', 30), message('谢谢', 0)],
            [message('有维护的', sent_at='2026-10-16T08:00:00'), message('谢谢')],
            [message('有维护的', sent_at='bad time'), message('谢谢')],
        ]
        for entries in cases:
            with self.subTest(entries=entries):
                self.assertEqual(prefilter.classify(entries), [None, None])

    def test_warnings_malformed_and_reply_metadata_never_filter(self):
        extras = [
            {'warnings': ['时间格式无效']}, {'parse_warnings': ['边界需确认']},
            {'kind': 'malformed'}, {'kind': 'unknown'}, {'sent_at': None},
            {'kind': []}, {'kind': 'media_placeholder'},
            {'sent_at': 'invalid'}, {'reply_to_message_id': 'm1'},
            {'quoted_message_id': 'm1'}, {'quoted_text': '之前的问题'},
            {'mentions': ['客户']}, {'parse_error': 'bad header'},
            {'direct_body_spans': []},
            {'direct_body_spans': [{'start_cp': -1, 'end_cp': 2}]},
            {'direct_body_spans': [{'start_cp': 0, 'end_cp': 50}]},
        ]
        for extra in extras:
            with self.subTest(extra=extra):
                self.assertEqual(prefilter.classify([message('谢谢', **extra)]), [None])
        self.assertEqual(prefilter.classify([
            message('[图片]', warnings=['引用边界不明']), message(' ', kind='malformed'),
        ]), [None, None])

    def test_quotes_mentions_and_multiline_are_preserved(self):
        raw = ['@张三 谢谢', '> 谢谢', '「谢谢」', '“谢谢”',
               '这是一条引用/回复消息：\n你好\n-----\n谢谢',
               '你好\n谢谢', '谢谢\nSQL 如下：\nselect 1;', '谢谢\n[图片]']
        self.assertEqual(prefilter.classify([message(s) for s in raw]), [None] * len(raw))

    def test_export_notice_needs_known_system_identity_and_exact_text(self):
        entries = [
            message('以上是历史消息', sender='系统消息'),
            message('以下为新消息', kind='system'),
            message('聊天记录导出完成', sender='导出工具'),
            message('以上是历史消息'),
            message('系统通知：接口维护中', sender='系统通知'),
            message('张三撤回了一条消息', sender='系统'),
            message('以上是历史消息\n登录失败', sender='系统消息'),
        ]
        self.assertEqual(prefilter.classify(entries), ['export_system_notice'] * 3 + [None] * 4)

    def test_parser_records_and_codepoint_positions_are_unchanged(self):
        source = ('2026-10-16 10:00:00:甲: [图片]\r\n'
                  '2026-10-16 10:01:00:甲: 你好！\r\n'
                  '2026-10-16 10:02:00:乙: EndDate 为什么为空？😀\r\n'
                  '2026-10-16 10:03:00:甲: 谢谢\r\n')
        entries = parser.parse_text(source)
        before = copy.deepcopy(entries)
        self.assertEqual(prefilter.classify(entries), ['media_placeholder', None, None, None])
        self.assertEqual(entries, before)
        for entry in entries:
            self.assertEqual(source[entry['source_body_start']:entry['source_body_end']], entry['raw_text'])

    def test_db_and_model_direct_span_shapes_are_supported(self):
        for span in ({'start_cp': 1, 'end_cp': 5}, {'start': 1, 'end': 5}):
            with self.subTest(span=span):
                self.assertEqual(prefilter.classify([message(' 谢谢！\n', direct_body_spans=[span])]),
                                 ['isolated_thanks'])

    def test_unknown_values_and_explanation_coverage(self):
        self.assertEqual(prefilter.classify([None, {}, {'raw_text': None}, {'raw_text': 123}]),
                         [None] * 4)
        self.assertEqual(prefilter.classify([message('以上是历史消息', sender=[])]), [None])
        self.assertEqual(prefilter.classify([]), [])
        self.assertTrue(prefilter.VERSION)
        self.assertTrue(all(isinstance(text, str) and text for text in prefilter.REASONS.values()))
        for reason in prefilter.classify([message(''), message('[图片]'), message('你好')]):
            self.assertIn(reason, prefilter.REASONS)


if __name__ == '__main__':
    unittest.main()
