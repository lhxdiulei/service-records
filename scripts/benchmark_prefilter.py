"""Offline, synthetic prefilter checks and exact topic-prompt token comparison.

No database, customer files, credentials, network, or model inference is used.
Run with the backend's installed dependencies and bundled tokenizer/prompts.
"""
import argparse
from collections import Counter
import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time


# Both a repository checkout and a script mounted at /srv are supported.
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / 'backend'))

from app import budget, parser, pipeline, prefilter


def row(body, label, sender='客户甲', stamp=None):
    return dict(body=body, label=label, sender=sender, stamp=stamp)


def fixtures():
    """Fixed labelled cases; do not select or replicate by measured savings."""
    cases = [
        ('isolated_noise', '只有空白、媒体和独立礼貌用语的会话', [
            row('   ', 'noise'), row('[图片]', 'noise'), row('[语音]', 'noise'),
            row('[文件]', 'noise'), row('config/media/demo.png', 'noise'),
            row('你好', 'noise'), row('早上好', 'noise'), row('谢谢', 'noise'),
            row('以下为新消息', 'noise', '系统消息'),
        ]),
        ('business_only_control', '全部有效的零收益对照', [
            row('订单导出时出现 502，如何处理？', 'question'),
            row('先检查网关日志中的 request_id，再重试导出。', 'answer', '工程师乙'),
            row('日志显示连接超时，需要增加超时时间吗？', 'question'),
            row('将代理读取超时改为 120 秒，保存后重新加载配置。', 'answer', '工程师乙'),
            row('正常了', 'status'), row('不是这个，我说的是导出结果缺少字段。', 'correction'),
        ]),
        ('mixed_workday', '业务上下文中的短回复、礼貌用语和媒体', [
            row('你好', 'context'),
            row('库存查询的 AvailableQty 字段为什么为空？', 'question'),
            row('[图片]', 'noise'), row('收到', 'status', '工程师乙'),
            row('稍等', 'status', '工程师乙'), row('   ', 'noise'),
            row('AvailableQty 是可用库存；未同步仓库数据时会为空。', 'answer', '工程师乙'),
            row('谢谢', 'context'), row('还是不行', 'status'),
            row('不是这个', 'correction'), row('REQ-2026-00128', 'requirement_id'),
            row('已提交需求', 'status', '工程师乙'), row('[视频]', 'noise'),
        ]),
        ('cross_day_reply', '跨日回复和没有业务关键词的状态', [
            row('权限调整后仍无法查询历史账单，请排查。', 'question', stamp='2026-10-12 16:58:00'),
            row('已调整，请明早重新登录确认。', 'answer', '工程师乙', '2026-10-12 17:01:00'),
            row('[语音]', 'noise', stamp='2026-10-13 08:58:00'),
            row('还是不行', 'status', stamp='2026-10-13 09:00:00'),
            row('现在好了', 'status', stamp='2026-10-14 10:00:00'),
            row('不对', 'correction', stamp='2026-10-14 10:01:00'),
        ]),
        ('quotes_sql_and_ambiguity', '引用、SQL、需求号、重复故障及不确定文本', [
            row('EndDate 的统计口径是什么？', 'question'),
            row('这是一条引用/回复消息\n「客户甲：EndDate 的统计口径是什么？」\n---\nEndDate 包含当天，条件使用小于次日零点。', 'answer', '工程师乙'),
            row('「工程师乙：EndDate 包含当天」', 'quote'),
            row('> [图片]\n附件中的错误代码是 E104，应该怎样处理？', 'question'),
            row("SELECT id, '[图片]' AS marker FROM orders WHERE EndDate < '2026-10-17';", 'sql', '工程师乙'),
            row('需求 #4831：请给库存报表增加仓库名称。', 'requirement_id'),
            row('报错又出现了', 'status'), row('报错又出现了', 'status'),
            row('这条先留着', 'ambiguous'), row('客服甲撤回了一条消息', 'ambiguous'),
            row('以下为新消息', 'ambiguous'),
            row('[图片] 中的数字不对', 'correction'),
        ]),
    ]
    # A long, valid message forces the real source-fragment path. Every line is
    # synthetic SQL; length is fixed before counting either pipeline.
    long_sql = 'WITH source AS (\n' + '\nUNION ALL\n'.join(
        f"SELECT {i} AS order_id, 'SYNTHETIC-{i:03d}' AS order_code, {i * 3} AS amount"
        for i in range(60)
    ) + '\n)\nSELECT order_id, SUM(amount) FROM source GROUP BY order_id;'
    cases.append(('long_sql', '有效长消息分片；包含 Unicode 与末尾换行', [
        row('请给出逐订单汇总金额的 SQL，中文备注和 😀 需要保留。', 'question'),
        row(long_sql, 'sql', '工程师乙'),
        row('GROUP BY 必须包含 order_id，不能按 order_code 合并。', 'answer', '工程师乙'),
        row('正常了，谢谢', 'status'),
    ]))
    many = []
    for index in range(12):
        many.extend([
            row(f'测试模块 {index + 1} 返回错误 E{100 + index}，如何恢复？', 'question'),
            row('[图片]', 'noise'),
            row(f'检查模块 {index + 1} 的连接池配置，然后重启对应任务。', 'answer', '工程师乙'),
            row('收到', 'status'),
            row('还是不行' if index % 2 else '正常了', 'status'),
        ])
    cases.append(('many_batches', '较多短业务消息触发输出容量分批', many))
    return cases


def parse_case(name, description, labelled):
    start = datetime(2026, 10, 12, 9, 0, 0)
    source = ''.join(
        f"{r['stamp'] or (start + timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S')}:{r['sender']}:{r['body']}\n"
        for i, r in enumerate(labelled)
    )
    entries = parser.parse_text(source)
    if len(entries) != len(labelled):
        raise AssertionError(f'{name}: parser changed fixture message count')
    for entry, expected in zip(entries, labelled):
        if entry['raw_text'] != expected['body'] + '\n':
            raise AssertionError(f'{name}: source body did not survive parser verbatim')
    return dict(name=name, description=description, labelled=labelled, source=source, entries=entries)


def model_messages(entries, selected, case_name):
    people = sorted({e['sender'] for e in entries})
    identities = {name: 'person-' + str(i) for i, name in enumerate(people)}
    participants = [dict(participant_id=identities[name], display_name=name,
                         role='support' if name == '工程师乙' else 'customer') for name in people]
    messages = []
    for index in selected:
        entry = entries[index]
        body, quoted, spans = parser.direct_parts(entry['raw_text'])
        messages.append(dict(
            message_id=f'{case_name}-{index}', participant_id=identities[entry['sender']],
            sent_at=entry['sent_at'], raw_text=entry['raw_text'], body_text=body,
            quoted_text=quoted,
            direct_body_spans=[dict(start=s['start_cp'], end=s['end_cp']) for s in spans],
            reply_to_message_id=None, has_nontext=entry['kind'] == 'media_placeholder',
            parse_warnings=entry['warnings'],
        ))
    return dict(schema_version='1.0', participants=participants), messages


CANDIDATES = [
    dict(issue_id='synthetic-order', title='订单导出失败', summary='导出网关超时', support_message_ids=[]),
    dict(issue_id='synthetic-stock', title='库存字段口径', summary='AvailableQty 可用库存', support_message_ids=[]),
    dict(issue_id='synthetic-login', title='历史账单查询权限', summary='登录后权限未刷新', support_message_ids=[]),
]


def pack_case(case, selected, limits):
    base, messages = model_messages(case['entries'], selected, case['name'])
    plan = pipeline.parts(messages, limits['fragment_tokens'], limits)
    # Validate the same disjoint source coverage used by the production worker.
    for message in messages:
        ranges = [p for p in plan if p['message_id'] == message['message_id']]
        if not ranges or ranges[0]['start'] != 0 or ranges[-1]['end'] != len(message['raw_text']):
            raise AssertionError('Incomplete source coverage')
        if any(a['end'] != b['start'] for a, b in zip(ranges, ranges[1:])):
            raise AssertionError('Overlapping or missing source ranges')
        views = pipeline.materialize(messages, ranges)
        if ''.join(view['raw_text'] for view in views) != message['raw_text']:
            raise AssertionError('Source fragments changed raw text')
    cursor, tokens = 0, []
    while cursor < len(plan):
        payload = pipeline.topic_packet(
            base, messages, plan, cursor, CANDIDATES, limits,
            context_ranges=plan[max(0, cursor - 2):cursor],
        )
        measured = budget.measure('topic_assignment', payload, limits)
        if not measured['fits']:
            raise AssertionError('Packed prompt exceeds budget')
        tokens.append(measured['input_tokens'])
        next_cursor = payload['processing']['cursor_end']
        if next_cursor <= cursor:
            raise AssertionError('Topic packet cursor did not advance')
        cursor = next_cursor
    return dict(messages=len(messages), fragments=len(plan), packets=len(tokens),
                input_tokens=sum(tokens), packet_input_tokens=tokens)


def timed(function, repetitions):
    function()  # Exclude first-call tokenizer loading and ordinary cache warm-up.
    durations, result = [], None
    for _ in range(repetitions):
        started = time.perf_counter_ns()
        result = function()
        durations.append((time.perf_counter_ns() - started) / 1_000_000)
    return result, dict(repetitions=repetitions, median_ms=round(statistics.median(durations), 4),
                        min_ms=round(min(durations), 4), max_ms=round(max(durations), 4))


def limits_for(args):
    # Deliberately freeze budget defaults instead of inheriting deployment env.
    path = Path(args.tokenizer).resolve()
    return dict(context=args.context_tokens, model='qwen3-vl:4b-instruct-q4_K_M',
                tokenizer_kind='hf_json', tokenizer_file=str(path),
                topic_output=args.topic_output_tokens, record_output=2600,
                correction_headroom=512, safety=256, fragment_tokens=650,
                tokenizer_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                prompt_sha256=hashlib.sha256(''.join(budget.prompts('topic_assignment')).encode()).hexdigest())


def run(args):
    limits = limits_for(args)
    cases = [parse_case(*case) for case in fixtures()]
    source_snapshot = copy.deepcopy([case['entries'] for case in cases])
    reasons, timing = timed(lambda: [prefilter.classify(case['entries']) for case in cases], args.repetitions)
    errors, reports = [], []
    before_selected, after_selected = [], []
    for case, classified in zip(cases, reasons):
        if len(classified) != len(case['entries']):
            raise AssertionError('classify() changed message count')
        before = [i for i, entry in enumerate(case['entries']) if entry['kind'] != 'media_placeholder']
        after = [i for i, reason in enumerate(classified) if reason is None]
        before_selected.append(before)
        after_selected.append(after)
        lost = [dict(index=i, label=label['label'], reason=classified[i])
                for i, label in enumerate(case['labelled']) if label['label'] != 'noise' and classified[i] is not None]
        errors.extend(f"{case['name']}:{item['index']} lost {item['label']} ({item['reason']})" for item in lost)
        unknown = [reason for reason in classified if reason is not None and reason not in prefilter.REASONS]
        errors.extend(f"{case['name']}: unknown reason {reason}" for reason in unknown)
        useful = Counter(r['label'] for r in case['labelled'] if r['label'] != 'noise')
        reports.append(dict(
            name=case['name'], description=case['description'], total_messages=len(classified),
            source_sha256=hashlib.sha256(case['source'].encode()).hexdigest(),
            labelled_useful=dict(useful), labelled_noise=sum(r['label'] == 'noise' for r in case['labelled']),
            useful_messages_lost=lost,
            retained_noise=sum(r['label'] == 'noise' and classified[i] is None for i, r in enumerate(case['labelled'])),
            filtered_reasons=dict(Counter(reason for reason in classified if reason is not None)),
        ))
    if source_snapshot != [case['entries'] for case in cases]:
        errors.append('Prefilter mutated parsed source entries')
    def packed(selections):
        return [pack_case(case, selected, limits) for case, selected in zip(cases, selections)]
    baseline, baseline_time = timed(lambda: packed(before_selected), args.pack_repetitions)
    filtered, filtered_time = timed(lambda: packed(after_selected), args.pack_repetitions)
    for report, before, after in zip(reports, baseline, filtered):
        report.update(baseline_media_only=before, new_prefilter=after,
                      input_tokens_saved=before['input_tokens'] - after['input_tokens'])
    totals = {}
    for name, values in [('baseline_media_only', baseline), ('new_prefilter', filtered)]:
        totals[name] = {key: sum(v[key] for v in values) for key in ('messages', 'fragments', 'packets', 'input_tokens')}
    saved = totals['baseline_media_only']['input_tokens'] - totals['new_prefilter']['input_tokens']
    total_before = totals['baseline_media_only']['input_tokens']
    totals.update(input_tokens_saved=saved, input_tokens_saved_percent=round(saved / total_before * 100, 2) if total_before else 0,
                  useful_messages=sum(sum(r['labelled_useful'].values()) for r in reports),
                  useful_messages_lost=sum(len(r['useful_messages_lost']) for r in reports),
                  labelled_noise=sum(r['labelled_noise'] for r in reports),
                  retained_noise=sum(r['retained_noise'] for r in reports))
    return dict(
        benchmark_version='synthetic-prefilter-1', prefilter_version=prefilter.VERSION,
        verification='passed' if not errors else 'failed', errors=errors,
        source_entries_unchanged=source_snapshot == [case['entries'] for case in cases],
        retained_source_fragment_coverage='passed', limits=limits,
        measurement_scope='topic_assignment only; full project-rendered prompts with ChatML and actual packet packing',
        candidate_pool='three fixed synthetic candidates, identical for both paths; no simulated model output',
        inference='not run; no LLM latency, extraction tokens, or generated QA quality measured',
        timing=dict(prefilter_only=timing, baseline_packing=baseline_time, filtered_packing=filtered_time,
                    includes='packing timings include source coverage validation and prompt token counting',
                    excludes='parser, I/O, tokenizer cold start, database, network, model inference'),
        totals=totals, cases=reports,
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', type=Path, help='Optional JSON destination; stdout always receives the same report')
    cli.add_argument('--tokenizer', default=str(budget.TOKENIZER))
    cli.add_argument('--context-tokens', type=int, default=8192)
    cli.add_argument('--topic-output-tokens', type=int, default=1800)
    cli.add_argument('--repetitions', type=int, default=25)
    cli.add_argument('--pack-repetitions', type=int, default=3)
    args = cli.parse_args()
    if min(args.repetitions, args.pack_repetitions, args.context_tokens, args.topic_output_tokens) < 1:
        cli.error('budgets and repetition counts must be positive')
    try:
        report = run(args)
    except Exception as error:
        report = dict(verification='failed', errors=[f'{type(error).__name__}: {error}'])
    output = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding='utf-8')
    print(output, end='')
    return 0 if report['verification'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
