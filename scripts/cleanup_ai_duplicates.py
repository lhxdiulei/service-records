"""Find identical-source AI QA drafts; --apply moves only unreviewed duplicates to recoverable deletion."""
import argparse
import json
import os
from pathlib import Path
from uuid import uuid4
import httpx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--base-url',default='http://web')
    parser.add_argument('--report',type=Path,help='可选报告路径；不指定时只输出标准输出')
    args=parser.parse_args()
    with httpx.Client(base_url=args.base_url,timeout=30) as c:
        token=c.get('/api/v1/auth/csrf').json()['csrf_token']
        c.headers.update({'Origin':os.getenv('APP_ORIGINS','http://localhost:8088').split(',')[0],'X-CSRF-Token':token})
        login=c.post('/api/v1/auth/login',json={'username':os.getenv('ADMIN_USERNAME','admin'),'password':os.environ['ADMIN_PASSWORD']});login.raise_for_status()
        c.headers['X-CSRF-Token']=login.json()['csrf_token']
        def get(path,**params):
            r=c.get('/api/v1'+path,params=params);r.raise_for_status();return r.json()
        records=[];page=1
        while True:
            value=get('/qa',page=page,page_size=100);records+=value['items']
            if len(records)>=value['total']:break
            page+=1
        kept={};duplicates=[]
        for q in sorted(records,key=lambda q:(q['created_at'],q['id'])):
            r=q['latest_revision']
            if q['current_revision_id'] or not r or r['origin']!='ai' or r['state']!='draft':continue
            detail=get('/qa/'+q['id'])
            if any(v['origin']!='ai' or v['state'] in ('approved','in_review') for v in detail['revisions']):continue
            proof=tuple(sorted({e['evidence_span_id'] for e in r['evidence'] if e['relation']=='supports' and (e['field_key']=='answer' or e['field_key'].startswith('answer_claims.'))}))
            if not proof:continue
            key=(q['customer_id'],tuple(sorted(r['issue_ids'])),proof)
            if key not in kept:kept[key]=q['id'];continue
            entry={'keep_qa_id':kept[key],'duplicate_qa_id':q['id'],'same_source_and_answer_evidence':True,'deleted':False}
            if args.apply:
                response=c.delete('/api/v1/records/qa/'+q['id'],headers={'Idempotency-Key':str(uuid4()),'If-Match':f'"{q["delete_version"]}"'})
                response.raise_for_status();entry.update(deleted=True,restore_version=response.json()['delete_version'])
            duplicates.append(entry)
        report={'status':'passed','applied':args.apply,'duplicates':duplicates,'count':len(duplicates),'raw_chat_mutated':False,'history_preserved':True}
        if args.report:
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
