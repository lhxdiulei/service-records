"""Live end-to-end check against this project's Web/API and configured local Dify.

Uploads a labelled synthetic file and leaves generated drafts for inspection.
Never reads private chat files, prints credentials or approves AI output.
Run inside an API container, mounting this file read-only at /srv/live_check.py.
"""
import json
import os
import sys
import time
from datetime import datetime,timezone,timedelta
from uuid import uuid4

import httpx

BASE=os.getenv('LIVE_CHECK_BASE_URL','http://web')
ORIGIN=os.getenv('APP_ORIGINS','http://localhost:8088').split(',')[0]
TEXT=('2026-07-13 09:00:00:客户甲:示例表 DemoRecord 的截止日期取哪个字段？\n'
      '2026-07-14 10:00:00:客服乙:DemoRecord 的 EndDate 表示截止日期。\n')


def emit(**data):
    print(json.dumps(data,ensure_ascii=False),flush=True)


def main():
    with httpx.Client(base_url=BASE,timeout=30,follow_redirects=False) as client:
        for attempt in range(15):
            try:
                if client.get('/api/health').status_code==200:
                    break
            except httpx.HTTPError:
                pass
            if attempt==14:
                raise RuntimeError('Web/API health check failed')
            time.sleep(2)
        token=client.get('/api/v1/auth/csrf').json()['csrf_token']
        client.headers.update({'Origin':ORIGIN,'X-CSRF-Token':token})
        response=client.post('/api/v1/auth/login',json={'username':os.getenv('ADMIN_USERNAME','admin'),'password':os.environ['ADMIN_PASSWORD']})
        if response.status_code!=200:
            raise RuntimeError('Administrator login failed; check bootstrap credentials')
        client.headers['X-CSRF-Token']=response.json()['csrf_token']
        staff_name=response.json()['user']['display_name']

        def request(method,path,body=None,version=None,**kwargs):
            headers={'Idempotency-Key':str(uuid4())}
            if version is not None:
                headers['If-Match']=f'"{version}"'
            response=client.request(method,'/api/v1'+path,json=body,headers=headers,**kwargs)
            if response.status_code>=400:
                detail=response.json().get('detail',{})
                message=detail.get('message') if isinstance(detail,dict) else str(detail)[:300]
                raise RuntimeError(f'{method} {path}: HTTP {response.status_code}, {message}')
            return response.json()

        integrations=request('GET','/integrations/dify')
        if not any(p['id']=='local' and p['configured'] for p in integrations):
            raise RuntimeError('Local Dify keys are not configured in the running API')
        resume=os.getenv('LIVE_CHECK_JOB_ID')
        if resume:
            job=request('GET','/jobs/'+resume)
            if not job.get('batch_id'):
                raise RuntimeError('Resume requires a file extraction job')
            batch=request('GET','/imports/'+job['batch_id'])
            if not batch['original_filename'].startswith('dify-live-synthetic-'):
                raise RuntimeError('Resume is limited to labelled synthetic live-check files')
            if job['state'] in ('failed','partial_failed'):
                job=request('POST','/jobs/'+resume+'/retry',version=job['version'])
        else:
            suffix=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')+'-'+str(uuid4())[:8]
            text=TEXT.replace(':客服乙:',':'+staff_name+':').replace('哪个字段？','哪个字段？（验收标识：'+suffix+'）')
            uploaded=request('POST','/imports',files={'file':('dify-live-synthetic-'+suffix+'.txt',text.encode(),'text/plain')})
            batch=uploaded['batch']
            request('POST',f"/imports/{batch['id']}/confirm",{'parse_version':batch['parse_version'],'accept_warnings':True},batch['version'])
            job=request('POST',f"/imports/{batch['id']}/extractions",{'mode':'both','profile':'local'})
        emit(event='resumed' if resume else 'created',batch_id=batch['id'],job_id=job['id'])
        deadline=time.monotonic()+1320
        previous=None
        while time.monotonic()<deadline:
            job=request('GET','/jobs/'+job['id'])
            signal=(job['state'],[(s['stage'],s['state'],s.get('error_code')) for s in job['steps']])
            if signal!=previous:
                emit(event='progress',state=job['state'],steps=job['steps'],error_code=job.get('error_code'),error_summary=job.get('error_summary'))
                previous=signal
            if job['state'] in ('failed','partial_failed','cancelled'):
                emit(event='failed',job_id=job['id'],error_code=job.get('error_code'),error_summary=job.get('error_summary'))
                return 1
            if job['state']=='succeeded':
                issues=request('GET','/issues?group_id='+batch['group_id'])
                if not issues:
                    raise RuntimeError('No issue generated for the explicit synthetic question/answer')
                tickets=[request('GET','/tickets/'+i['ticket_id']) for i in issues]
                if not any(p['display_name']==staff_name and p['role']=='support' for t in tickets for p in t['participants']):
                    raise RuntimeError('Registered internal account was not resolved as support')
                sources={i['id'] for i in issues}
                qa_list=request('GET','/qa')
                qa=[q for q in qa_list if q['latest_revision'] and sources.intersection(q['latest_revision']['issue_ids'])]
                if not all(t['revisions'] for t in tickets) or not qa:
                    raise RuntimeError('Expected ticket and QA drafts were not both generated')
                if any(t['object']['current_revision_id'] for t in tickets) or any(q['current_revision_id'] for q in qa):
                    raise RuntimeError('AI output must not be automatically approved')
                if any(t['revisions'][0]['state']!='draft' or t['revisions'][0]['ticket_date']!='2026-07-13' for t in tickets):
                    raise RuntimeError('Expected draft tickets dated from the original question')
                if any(q['latest_revision']['state']!='draft' or 'EndDate' not in (q['latest_revision']['answer'] or '')
                       or not q['latest_revision']['evidence'] or not q['latest_revision']['contributors'] for q in qa):
                    raise RuntimeError('Expected an evidenced draft QA with the source answer and verified contributor')
                emit(event='passed',job_id=job['id'],batch_id=batch['id'],issues=len(issues),
                     ticket_drafts=[{'id':t['object']['id'],'revision_id':t['revisions'][0]['id'],'title':t['revisions'][0]['title'],'ticket_date':t['revisions'][0]['ticket_date'],'state':t['revisions'][0]['state'],'evidence_count':len(t['revisions'][0]['evidence'])} for t in tickets],
                     qa_drafts=[{'id':q['id'],'revision_id':q['latest_revision']['id'],'question':q['latest_revision']['question'],'answer':q['latest_revision']['answer'],'state':q['latest_revision']['state'],'evidence_count':len(q['latest_revision']['evidence']),'contributors':len(q['latest_revision']['contributors'])} for q in qa])
                return 0
            time.sleep(5)
        raise RuntimeError('Live verification timed out; persisted job can be inspected in the UI')


if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        emit(event='error',message=str(exc))
        sys.exit(1)
