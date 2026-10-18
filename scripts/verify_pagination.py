"""登录后只读检查现有记录的分页；不依赖历史任务、不调用模型。"""
import argparse
import json
import math
import os
from pathlib import Path
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://web')
    parser.add_argument('--batch-id', help='可选：仅检查指定文件中的消息')
    parser.add_argument('--report', type=Path, help='可选：将计数报告另存为 JSON')
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        response = client.get('/api/v1/auth/csrf')
        response.raise_for_status()
        client.headers.update({
            'Origin': os.getenv('APP_ORIGINS', 'http://localhost:8088').split(',')[0],
            'X-CSRF-Token': response.json()['csrf_token'],
        })
        response = client.post('/api/v1/auth/login', json={
            'username': os.getenv('ADMIN_USERNAME', 'admin'), 'password': os.environ['ADMIN_PASSWORD'],
        })
        response.raise_for_status()
        client.headers['X-CSRF-Token'] = response.json()['csrf_token']

        def get(path, **params):
            response = client.get('/api/v1' + path, params=params)
            response.raise_for_status()
            return response.json()

        def check_pages(path, **params):
            first = get(path, page=1, **params)
            assert first['page_size'] == 10 and first['page'] == 1
            assert len(first['items']) == min(first['total'], 10)
            if first['total'] > 10:
                second = get(path, page=2, **params)
                assert not {m['id'] for m in first['items']} & {m['id'] for m in second['items']}
            last = get(path, page=max(1, math.ceil(first['total'] / 10)), **params)
            assert len(last['items']) == max(0, first['total'] - 10 * (last['page'] - 1))
            return {'total': first['total'], 'first_page_count': len(first['items'])}

        lists = {name: check_pages('/' + name) for name in ('tickets', 'qa', 'jobs', 'reviews', 'imports', 'users')}
        scope = {'batch_id': args.batch_id} if args.batch_id else {}
        messages = check_pages('/messages', **scope)
        states = {state: get('/messages', page=1, state=state, **scope)['total']
                  for state in ('pending', 'assigned', 'ignored', 'needs_review')}
        assert sum(states.values()) == messages['total']
        report = {'status': 'passed', 'page_size': 10, 'lists': lists, 'messages': messages,
                  'message_states': states, 'model_invoked': False, 'business_records_modified': False}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
