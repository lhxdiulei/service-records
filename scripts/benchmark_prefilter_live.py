"""One synthetic A/B against configured LOCAL Dify; never uses the business DB.

Default is a dry run. --execute makes exactly one workflow call per variant,
without retries or external-profile fallback. Dify may run its own correction
node. Only synthetic content and sanitized numeric usage are reported.
"""
import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import NAMESPACE_URL, uuid4, uuid5

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent / 'backend'))

import httpx
from app import budget, dify, parser, pipeline, prefilter


SOURCE = (
    '2026-10-15 08:00:00:合成客户:你好\n'
    '2026-10-15 08:01:00:合成客户:谢谢\n'
    '2026-10-15 08:02:00:合成客户:[图片]\n'
    '2026-10-15 08:03:00:合成客户:   \n'
    '2026-10-15 10:00:00:合成客户:示例表 DemoRecord 的截止日期取哪个字段？\n'
    '2026-10-15 10:01:00:合成客服:DemoRecord 的 EndDate 表示截止日期。\n'
)


def synthetic_id(label):
    return str(uuid5(NAMESPACE_URL, 'prefilter-live-synthetic:' + label))


def prepare():
    entries = parser.parse_text(SOURCE)
    original = copy.deepcopy(entries)
    started = time.perf_counter()
    reasons = prefilter.classify(entries)
    filtering_ms = (time.perf_counter() - started) * 1000
    if entries != original or len(reasons) != len(entries):
        raise AssertionError('Prefilter changed original synthetic records')
    if reasons[4] is not None or reasons[5] is not None:
        raise AssertionError('Synthetic question or answer was filtered')
    limits = budget.policy('local')
    if limits['tokenizer_kind'] != 'hf_json':
        raise ValueError('Live comparison requires configured local hf_json tokenizer')
    participants = [dict(participant_id=synthetic_id(name), display_name=name, role=role)
                    for name, role in [('合成客户', 'customer'), ('合成客服', 'support')]]
    base = dict(schema_version='1.0',
                run=dict(job_id=str(uuid4()), step_id=str(uuid4()),
                         pipeline_version='synthetic-prefilter-live-1', input_hash='0' * 64),
                scope=dict(customer_id=synthetic_id('customer'), chat_group_id=synthetic_id('group')),
                participants=participants)
    all_messages = []
    for index, entry in enumerate(entries):
        body, quoted, spans = parser.direct_parts(entry['raw_text'])
        all_messages.append(dict(
            message_id=synthetic_id('message-' + str(index)), participant_id=synthetic_id(entry['sender']),
            sent_at=entry['sent_at'], raw_text=entry['raw_text'], body_text=body, quoted_text=quoted,
            direct_body_spans=[dict(start=s['start_cp'], end=s['end_cp']) for s in spans],
            reply_to_message_id=None, has_nontext=entry['kind'] == 'media_placeholder',
            parse_warnings=entry['warnings'],
        ))
    variants = []
    for name, indexes in [
        ('baseline_media_only', [i for i, e in enumerate(entries) if e['kind'] != 'media_placeholder']),
        ('new_prefilter', [i for i, reason in enumerate(reasons) if reason is None]),
    ]:
        messages = [all_messages[i] for i in indexes]
        plan = pipeline.parts(messages, limits['fragment_tokens'], limits)
        payload = pipeline.topic_packet(base, messages, plan, 0, [], limits)
        if payload['processing']['cursor_end'] != len(plan):
            raise ValueError('Live benchmark must fit exactly one packet per variant')
        measured = budget.measure('topic_assignment', payload, limits)
        if not measured['fits']:
            raise ValueError('Synthetic input exceeds configured local token budget')
        payload['processing'].update(output_tokens=measured['output_reserve'], context_tokens=measured['context_limit'])
        payload['run']['step_id'] = str(uuid4())
        payload['run']['input_hash'] = hashlib.sha256(json.dumps(
            {k: v for k, v in payload.items() if k != 'run'}, ensure_ascii=False, sort_keys=True,
        ).encode()).hexdigest()
        dify.validate_schema('topic_assignment.input', payload)
        variants.append((name, payload, measured))
    return variants, limits, reasons, filtering_ms


def numeric(value):
    return value if type(value) in (int, float) else None


class ObservedResponse:
    """Pass through SSE unchanged while retaining only numeric usage fields."""
    def __init__(self, response, trace):
        self.response, self.trace = response, trace

    @property
    def status_code(self):
        return self.response.status_code

    def raise_for_status(self):
        return self.response.raise_for_status()

    def iter_lines(self):
        for line in self.response.iter_lines():
            if line.startswith('data:'):
                try:
                    event = json.loads(line[5:].strip())
                    data = event.get('data') or {}
                    if event.get('event') == 'node_finished' and data.get('node_type') == 'llm':
                        usage = (data.get('outputs') or {}).get('usage') or {}
                        metadata = data.get('execution_metadata') or {}
                        self.trace['llm_nodes'].append(dict(
                            prompt_tokens=numeric(usage.get('prompt_tokens')),
                            completion_tokens=numeric(usage.get('completion_tokens')),
                            total_tokens=numeric(usage.get('total_tokens', metadata.get('total_tokens'))),
                            elapsed_seconds=numeric(data.get('elapsed_time')),
                        ))
                    if event.get('event') == 'workflow_finished':
                        self.trace.update(workflow_elapsed_seconds=numeric(data.get('elapsed_time')),
                                          workflow_total_tokens=numeric(data.get('total_tokens')),
                                          workflow_total_steps=numeric(data.get('total_steps')))
                except (ValueError, TypeError, AttributeError):
                    pass  # The actual transport still validates the same event.
            yield line


class ObservedClient(httpx.Client):
    def __init__(self, trace):
        super().__init__(timeout=httpx.Timeout(45, connect=10), follow_redirects=False)
        self.trace = trace

    @contextmanager
    def stream(self, *args, **kwargs):
        with super().stream(*args, **kwargs) as response:
            yield ObservedResponse(response, self.trace)


def compare_output(payload, result):
    dify.validate_topic(payload, result)
    question, answer = synthetic_id('message-4'), synthetic_id('message-5')
    links = [{link['message_id']: link['relation'] for link in item['message_links']}
             for item in result['assignments']]
    question_found = any(item.get(question) == 'question' for item in links)
    answer_found = any(item.get(answer) == 'answer' for item in links)
    joined = any(item.get(question) == 'question' and item.get(answer) == 'answer' for item in links)
    return dict(schema_and_message_coverage_valid=True, question_relation_found=question_found,
                answer_relation_found=answer_found, same_issue_question_and_answer=joined,
                assignments=len(result['assignments']), unassigned_messages=len(result['unassigned_messages']))


def run_one(name, payload, measured):
    trace = dict(llm_nodes=[])
    outcome = dict(variant=name, main_messages=len(payload['main_message_ids']),
                   planned_first_prompt_input_tokens=measured['input_tokens'], model_trace=trace)
    def on_started(run_id, task_id):
        outcome['workflow_run_id'] = run_id
        print(json.dumps(dict(event='started', variant=name, workflow_run_id=run_id)), file=sys.stderr, flush=True)
    def check_workflow(workflow_id):
        outcome['workflow_id'] = workflow_id
    on_started.check_workflow = check_workflow
    started = time.perf_counter()
    try:
        with ObservedClient(trace) as client:
            result = dify.run_workflow('local', 'topic_assignment', payload, on_started, client=client)
        outcome['end_to_end_seconds'] = round(time.perf_counter() - started, 4)
        outcome['quality'] = compare_output(payload, result)
        outcome['status'] = 'passed' if outcome['quality']['same_issue_question_and_answer'] else 'quality_failed'
    except dify.DifyError as error:
        outcome.update(status='failed', end_to_end_seconds=round(time.perf_counter() - started, 4),
                       error_code=error.code, error_summary=error.message)
    except Exception as error:
        # Do not stringify arbitrary transport/configuration exceptions.
        outcome.update(status='failed', end_to_end_seconds=round(time.perf_counter() - started, 4),
                       error_code=type(error).__name__, error_summary='Unexpected error; no retry was attempted')
    nodes = trace['llm_nodes']
    trace['observed_prompt_tokens'] = sum(n['prompt_tokens'] for n in nodes) if nodes and all(n['prompt_tokens'] is not None for n in nodes) else None
    outcome['provider_prompt_minus_planned'] = (
        trace['observed_prompt_tokens'] - measured['input_tokens']
        if trace['observed_prompt_tokens'] is not None else None
    )
    print(json.dumps(dict(event='completed', variant=name, status=outcome['status'],
                          seconds=outcome['end_to_end_seconds'])), file=sys.stderr, flush=True)
    return outcome


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--execute', action='store_true', help='Run the two local workflow requests; otherwise validate inputs only')
    cli.add_argument('--output', type=Path)
    args = cli.parse_args()
    report = dict(benchmark_version='synthetic-prefilter-live-1', profile='local', stage='topic_assignment',
                  synthetic_source=SOURCE, no_business_database_access=True, maximum_workflow_calls=2,
                  order=['baseline_media_only', 'new_prefilter'], workflow_retries=0,
                  limitations='One A/B pair; baseline runs first without an extra warm-up. Model warm-up, cache, output length, internal correction and other load can change latency. Planned local prompt tokens may differ from provider usage and are reported separately. No extraction/QA generation is performed.')
    def save():
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    try:
        variants, limits, reasons, filtering_ms = prepare()
        report.update(prefilter_version=prefilter.VERSION, limits=limits,
                      filtering_reasons=reasons, prefilter_single_ms=round(filtering_ms, 4),
                      inputs=[dict(variant=n, messages=len(p['main_message_ids']), input_tokens=m['input_tokens']) for n, p, m in variants],
                      status='running' if args.execute else 'dry_run_passed', runs=[])
        save()
        if args.execute:
            for name, payload, measured in variants:
                report['runs'].append(run_one(name, payload, measured))
                save()
            report['status'] = 'passed' if all(r['status'] == 'passed' for r in report['runs']) else 'failed'
            versions = [r.get('workflow_id') for r in report['runs']]
            report['same_workflow_version'] = bool(versions[0] and versions[0] == versions[1])
            if not report['same_workflow_version']:
                report['status'] = 'failed'
    except dify.DifyError as error:
        report.update(status='failed', error_code=error.code, error_summary=error.message)
    except Exception as error:
        report.update(status='failed', error_code=type(error).__name__, error_summary='Input validation or execution failed; no retry was attempted')
    save()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] in ('passed', 'dry_run_passed') else 1


if __name__ == '__main__':
    sys.exit(main())
