
import logging
from datetime import datetime, timezone
from celery import Celery
from psycopg.types.json import Jsonb
from fastapi import HTTPException
from . import config, services as S, dify, models as M, budget, pipeline, identities as I, deletions as D, ai_records as A, triage as T
from .db import connect, one, rows, insert, uid, digest, plain, audit
from .security import scope, fail

log=logging.getLogger(__name__)
celery=Celery('service_records',broker=config.REDIS_URL)
celery.conf.update(task_acks_late=True,worker_prefetch_multiplier=1,task_reject_on_worker_lost=True,
    broker_transport_options={'visibility_timeout':1800},beat_schedule={'dispatch':{'task':'records.dispatch','schedule':10.0}},timezone='UTC')


def enqueue(db,user,data,batch=None,issue=None):
    dify.settings(data.profile,'topic_assignment' if batch else 'record_extraction')
    source_id=str(batch['id'] if batch else issue['id'])
    db.execute('SELECT pg_advisory_xact_lock(%s)',(int(digest(source_id+data.mode+data.profile)[:15],16),))
    if batch:D.active(db,'import',batch['id'])
    else:D.active(db,'ticket',one(db,'SELECT id FROM tickets WHERE issue_id=%s',(issue['id'],))['id'])
    active=one(db,'''SELECT * FROM extraction_jobs WHERE (batch_id=%s OR target_issue_id=%s) AND mode=%s AND model_profile_snapshot->>'id'=%s
        AND state IN ('queued','running') ORDER BY created_at DESC LIMIT 1''',(batch['id'] if batch else None,issue['id'] if issue else None,data.mode,data.profile))
    if active:
        if batch:
            S.entity(db,'chat_groups',batch['group_id'],user,True)
            added=one(db,"""SELECT m.id FROM messages m JOIN message_dispositions d ON d.message_id=m.id
                WHERE m.batch_id=%s AND NOT """+D.deleted('message','m')+""" AND d.state IN ('pending','needs_review')
                AND NOT (m.id=ANY(%s::uuid[])) LIMIT 1""",(batch['id'],active['input_manifest'].get('main_message_ids',[])))
            if added:fail(409,'active_job_missing_messages','已有任务正在处理，未包含新恢复的消息；请待该任务结束后重新发起 AI 归属与抽取')
        return dict(active,reused_request=True)
    if batch:
        group=S.entity(db,'chat_groups',batch['group_id'],user,True)
        source=rows(db,"""SELECT m.id,d.version FROM messages m JOIN message_dispositions d ON d.message_id=m.id
            WHERE m.batch_id=%s AND NOT """+D.deleted('message','m')+" AND d.state IN ('pending','needs_review') ORDER BY m.sent_at NULLS LAST,m.source_index,m.id",(batch['id'],))
        if not source:
            previous=one(db,"SELECT * FROM extraction_jobs WHERE batch_id=%s AND mode=%s AND model_profile_snapshot->>'id'=%s AND state='succeeded' ORDER BY created_at DESC LIMIT 1",(batch['id'],data.mode,data.profile))
            if previous:return dict(previous,reused_request=True)
            fail(409,'no_pending_messages','没有待归属消息，可从已有问题重新抽取')
        manifest={'group_id':str(group['id']),'ingestion_version':group['ingestion_version'],'batch_version':batch['version'],
                  'main_message_ids':[str(m['id']) for m in source], 'disposition_versions':{str(m['id']):m['version'] for m in source}}
    else:
        group=S.entity(db,'chat_groups',issue['primary_group_id'],user,True)
        manifest={'group_id':str(group['id']),'ingestion_version':group['ingestion_version']}
    manifest['identity_version']=I.version(db)
    profile={'id':data.profile,'topic_version':'topic_assignment_v2','record_version':'record_extraction_v2','budget':budget.policy(data.profile)}
    job=insert(db,'extraction_jobs',dict(id=uid(),customer_id=group['customer_id'],batch_id=batch['id'] if batch else None,
        target_issue_id=issue['id'] if issue else None,mode=data.mode,requested_by=user['id'],input_hash=digest(manifest),
        pipeline_version='0.2.0',workflow_versions={'topic':'v2','record':'v2'},model_profile_snapshot=profile,input_manifest=manifest))
    insert(db,'outbox_events',dict(id=uid(),customer_id=job['customer_id'],event_type='extract_requested',aggregate_type='extraction_job',
        aggregate_id=job['id'],dedupe_key='extract:'+str(job['id']),payload={'job_id':str(job['id'])}))
    audit(db,user['id'],'enqueue','job',job['id'],job['customer_id'],{'profile':data.profile,'mode':data.mode})
    return job


@celery.task(name='records.dispatch')
def dispatch():
    # Re-sweep the durable jobs as well as outbox: broker loss cannot lose queued work.
    with connect() as db:
        jobs=rows(db,"""SELECT id FROM extraction_jobs WHERE state='queued' OR
            (state='running' AND lease_until<now()) OR (state='cancel_requested' AND (lease_until IS NULL OR lease_until<now()))
            ORDER BY created_at LIMIT 50""")
    for j in jobs:
        run_job.delay(str(j['id']))
        with connect() as db:
            db.execute("UPDATE outbox_events SET state='published',published_at=now(),attempts=attempts+1 WHERE aggregate_id=%s AND state='pending'",(j['id'],))


def live(db,job_id,token):
    job=one(db,'SELECT * FROM extraction_jobs WHERE id=%s FOR UPDATE',(job_id,))
    if job['fencing_token']!=token or job['state']!='running':raise dify.DifyError('job_cancelled','任务已取消或执行权已变化')
    if job['input_manifest'].get('identity_version')!=I.version(db):raise dify.DifyError('identity_changed','客服账号身份已变化，请创建新任务；已完成结果保留')
    if job['batch_id']:
        batch=one(db,'SELECT b.version,'+D.metadata('import','b')+' FROM import_batches b WHERE b.id=%s',(job['batch_id'],))
        if batch['is_deleted'] or batch['version']!=job['input_manifest'].get('batch_version'):
            raise dify.DifyError('source_changed','来源文件已删除、恢复或变化，请创建新任务')
    db.execute("UPDATE extraction_jobs SET lease_until=now()+interval '15 minutes' WHERE id=%s",(job_id,))
    return job


def wf_messages(db,messages):
    result=[]
    for original in messages:
        m=S.effective_message(db,original)
        result.append(dict(message_id=str(m['id']),participant_id=str(m['sender_participant_id']) if m['sender_participant_id'] else None,
            sent_at=m['sent_at'].isoformat() if m['sent_at'] else None,raw_text=m['raw_text'],body_text=m['body_text'],quoted_text=m['quoted_text'],
            direct_body_spans=[{'start':s['start_cp'],'end':s['end_cp']} for s in m['direct_body_spans']],
            reply_to_message_id=str(m['quoted_message_id']) if m['quoted_message_id'] else None,
            has_nontext=m['kind']=='media_placeholder',parse_warnings=m['parse_warnings']))
        if original.get('relation'):result[-1]['relation']=original['relation']
    return result


def common(db,job):
    gid=job['input_manifest']['group_id']
    return dict(schema_version='1.0',run={'job_id':str(job['id']),'step_id':uid(),'pipeline_version':job.get('pipeline_version','0.2.0'),'input_hash':'0'*64},
        scope={'customer_id':str(job['customer_id']),'chat_group_id':gid},
        participants=[dict(participant_id=str(p['id']),display_name=p['display_name'],role=p['role']) for p in rows(db,'SELECT * FROM participants WHERE group_id=%s ORDER BY id',(gid,))])


def call_step(job,token,stage,target,payload):
    with connect() as db:
        live(db,job['id'],token)
        step=one(db,'SELECT * FROM job_steps WHERE job_id=%s AND stage=%s AND target_key=%s ORDER BY created_at LIMIT 1',(job['id'],stage,target))
        if step:
            payload=step['input_manifest']
            if step['error_code']=='workflow_changed':
                raise dify.DifyError('workflow_changed','此断点检测到 Dify 发布版本变化，请使用新配置创建任务；已有结果已保留')
            if step['output_json'] is not None:
                return step,payload,step['output_json']['result']
        else:
            step_id=uid();payload['run']['step_id']=step_id
            payload['run']['input_hash']=digest({k:v for k,v in payload.items() if k!='run'})
            measured=budget.measure(stage,payload,job['model_profile_snapshot'].get('budget'))
            if not measured['fits']:raise dify.DifyError('token_budget','分批输入超出已配置的模型 Token 预算')
            payload.setdefault('processing',{}).update(output_tokens=measured['output_reserve'],context_tokens=measured['context_limit'])
            dify.validate_schema(stage+'.input',payload)
            step=insert(db,'job_steps',dict(id=step_id,customer_id=job['customer_id'],job_id=job['id'],stage=stage,target_key=target,
                issue_id=payload['issue']['issue_id'] if stage=='record_extraction' else None,input_hash=payload['run']['input_hash'],workflow_version=stage+'_v2',input_manifest=payload,
                input_tokens=measured['input_tokens'],output_reserve=measured['output_reserve'],context_limit=measured['context_limit']))
        if step['state']=='failed' and step['error_code'] in ('workflow_invalid','schema_invalid','message_coverage','unknown_issue','mode_mismatch','qa_incomplete','remote_failed','evidence_missing','contributor_mismatch','date_scope','duplicate_topic','invalid_topic'):
            history=step.get('attempt_history',[])+[{'run_id':step['dify_workflow_run_id'],'error_code':step['error_code']} ]
            db.execute("UPDATE job_steps SET dify_workflow_run_id=NULL,dify_task_id=NULL,remote_state='not_started',error_code=NULL,error_summary=NULL,attempt_history=%s WHERE id=%s",(Jsonb(history),step['id']))
            step['dify_workflow_run_id']=None
        db.execute("UPDATE job_steps SET state='running',lease_owner=%s,lease_until=now()+interval '15 minutes',fencing_token=%s,attempt_count=attempt_count+1 WHERE id=%s",(str(job['id']),token,step['id']))
    def on_started(run_id,task_id):
        if not run_id:raise dify.DifyError('missing_run_id','Dify 未返回运行标识')
        with connect() as db:
            live(db,job['id'],token)
            db.execute("UPDATE job_steps SET dify_workflow_run_id=%s,dify_task_id=%s,remote_state='running' WHERE id=%s",(run_id,task_id,step['id']))
    def check_workflow(workflow_id):
        with connect() as db:
            current=live(db,job['id'],token)
            profile=current['model_profile_snapshot']
            versions=profile.setdefault('workflow_ids',{})
            if stage in versions and versions[stage]!=workflow_id:
                raise dify.DifyError('workflow_changed','Dify 已发布新版本，请为新模型配置创建新任务；已有断点结果已保留')
            versions[stage]=workflow_id
            db.execute('UPDATE extraction_jobs SET model_profile_snapshot=%s WHERE id=%s',(Jsonb(profile),job['id']))
    on_started.check_workflow=check_workflow
    try:
        result=dify.run_workflow(job['model_profile_snapshot']['id'],stage,payload,on_started,step['dify_workflow_run_id'])
        (dify.validate_topic if stage=='topic_assignment' else dify.validate_extraction)(payload,result)
        with connect() as db:
            live(db,job['id'],token)
            db.execute("UPDATE job_steps SET state='succeeded',remote_state='succeeded',output_json=%s,finished_at=now() WHERE id=%s",(Jsonb({'result':result,'applied':False}),step['id']))
        return step,payload,result
    except Exception as exc:
        with connect() as db:
            current=one(db,'SELECT fencing_token FROM extraction_jobs WHERE id=%s',(job['id'],))
            if current['fencing_token']==token:
                db.execute("UPDATE job_steps SET state='failed',error_code=%s,error_summary=%s WHERE id=%s",(getattr(exc,'code','step_failed'),getattr(exc,'message','工作流执行失败'),step['id']))
        raise


def applied(db,step_id):
    step=one(db,'SELECT output_json FROM job_steps WHERE id=%s FOR UPDATE',(step_id,))
    return step['output_json'].get('applied',False)


def mark_applied(db,step_id,ids):
    db.execute("UPDATE job_steps SET output_json=jsonb_set(jsonb_set(output_json,'{applied}','true'),'{issue_ids}',%s) WHERE id=%s",(Jsonb(ids),step_id))


def candidate_pool(db,group_id):
    candidates=rows(db,"""SELECT i.*, a.anchors FROM issues i LEFT JOIN LATERAL
        (SELECT jsonb_agg(x) AS anchors FROM
          (SELECT m.id AS message_id,left(m.raw_text,220) AS text FROM issue_messages im
           JOIN messages m ON m.id=im.message_id WHERE im.issue_id=i.id AND im.active
           ORDER BY (im.relation='question') DESC,m.sent_at NULLS LAST,m.source_index LIMIT 2) x) a ON true
        WHERE i.customer_id=(SELECT customer_id FROM chat_groups WHERE id=%s) AND i.lifecycle='active' AND i.message_version>0
        AND NOT EXISTS(SELECT 1 FROM tickets t WHERE t.issue_id=i.id AND """+D.deleted('ticket','t')+""")
        ORDER BY i.updated_at DESC,i.id""",(group_id,))
    return [dict(issue_id=str(i['id']),version=i['version'],message_version=i['message_version'],title=i['label'],
                 summary='\n'.join(a['text'] for a in (i['anchors'] or [])) or i['label'],
                 support_message_ids=[a['message_id'] for a in (i['anchors'] or [])]) for i in candidates]


def checkpoint(db,job_id,**values):
    current=one(db,'SELECT checkpoint FROM extraction_jobs WHERE id=%s FOR UPDATE',(job_id,))['checkpoint']
    current.update(values)
    db.execute('UPDATE extraction_jobs SET checkpoint=%s WHERE id=%s',(Jsonb(current),job_id))
    return current


def classify(job,token,user):
    all_ids=job['input_manifest']['main_message_ids']
    with connect() as db:
        current=live(db,job['id'],token)
        if one(db,'SELECT m.id FROM messages m WHERE id=ANY(%s::uuid[]) AND '+D.deleted('message','m')+' LIMIT 1',(all_ids,)):
            raise dify.DifyError('source_changed','来源消息已删除，请创建新任务')
        messages=wf_messages(db,rows(db,'SELECT * FROM messages WHERE id=ANY(%s::uuid[]) ORDER BY sent_at NULLS LAST,source_index,id',(all_ids,)))
        limits=job['model_profile_snapshot'].get('budget') or budget.policy()
        plan=current['topic_plan']
        if plan is None:
            plan=pipeline.parts(messages,limits['fragment_tokens'],limits)
            db.execute('UPDATE extraction_jobs SET topic_plan=%s WHERE id=%s',(Jsonb(plan),job['id']))
            checkpoint(db,job['id'],phase='topic_assignment',topic_cursor=0,topic_batches=0,topic_parts_total=len(plan),messages_total=len(all_ids),messages_done=0)
    while True:
        with connect() as db:
            current=live(db,job['id'],token);cp=current['checkpoint'];cursor=cp.get('topic_cursor',0)
            if cursor>=len(plan):return current['result_issue_ids']
            target='topic:'+str(cp.get('topic_batches',0)).zfill(6)
            cap=cp.get('topic_packet_cap',0)
            if cap:target+=':max'+str(cap)
            cached=one(db,"SELECT input_manifest FROM job_steps WHERE job_id=%s AND stage='topic_assignment' AND target_key=%s",(job['id'],target))
            if cached:payload=cached['input_manifest']
            else:
                payload=pipeline.topic_packet(common(db,job),messages,plan,cursor,candidate_pool(db,job['input_manifest']['group_id']),limits,plan[max(0,cursor-2):cursor],max_parts=cap)
        try:
            step,payload,result=call_step(job,token,'topic_assignment',target,payload)
        except dify.DifyError as exc:
            if exc.code not in ('workflow_invalid','schema_invalid','message_coverage','unknown_issue','duplicate_topic','invalid_topic','message_scope'):raise
            with connect() as db:
                current=live(db,job['id'],token)
                size=len(payload['main_message_ids'])
                if size>1:
                    checkpoint(db,job['id'],topic_packet_cap=max(1,size//2),topic_success_streak=0)
                    continue
                # Exhausted the model's bounded correction even for one part.
                # Review only substantive business content when the model fails.
                group=S.entity(db,'chat_groups',job['input_manifest']['group_id'],user,True)
                if group['ingestion_version']!=job['input_manifest']['ingestion_version']:
                    raise dify.DifyError('source_changed','群已有新导入，请重新创建任务')
                mid=payload['main_message_ids'][0]
                expected={**job['input_manifest']['disposition_versions'],**current['checkpoint'].get('owned_disposition_versions',{})}
                disposition=one(db,'SELECT * FROM message_dispositions WHERE message_id=%s FOR UPDATE',(mid,))
                if disposition['version']!=expected[mid]:raise dify.DifyError('source_changed','消息归属已被人工修改')
                review=insert(db,'job_steps',dict(id=uid(),customer_id=job['customer_id'],job_id=job['id'],stage='validation',
                    target_key='review:'+str(cursor),state='succeeded',input_hash=digest(payload),workflow_version='manual-review-v1',
                    input_manifest=payload,output_json={'applied':True,'issue_ids':[],'reason':exc.code},finished_at=datetime.now(timezone.utc)))
                state,reason=T.disposition('AI分批归属未通过校验，请人工确认；原文完整保留',next(m for m in messages if m['message_id']==mid))
                db.execute("UPDATE message_dispositions SET state=%s,decision_source='rule',reason=%s,version=version+1,source_job_step_id=%s WHERE message_id=%s",(state,reason,review['id'],mid))
                owned=dict(current['checkpoint'].get('owned_disposition_versions',{}));owned[mid]=disposition['version']+1
                end=payload['processing']['cursor_end'];remaining={p['message_id'] for p in plan[end:]}
                reviews=sorted(set(current['checkpoint'].get('review_message_ids',[])+([mid] if state=='needs_review' else [])))
                checkpoint(db,job['id'],topic_cursor=end,topic_batches=current['checkpoint'].get('topic_batches',0)+1,
                    messages_done=len(set(all_ids)-remaining),owned_disposition_versions=owned,topic_packet_cap=1,topic_success_streak=0,review_message_ids=reviews)
                S.watermark(db,group['id'])
            continue
        with connect() as db:
            current=live(db,job['id'],token)
            existing_ids=sorted({a['existing_issue_id'] for a in result['assignments'] if a.get('existing_issue_id') and a['decision']!='needs_review'})
            uncertain={m['message_id'] for a in result['assignments'] if a['decision']=='needs_review' for m in a['message_links']}|{m['message_id'] for m in result['unassigned_messages']}
            existing_ids=sorted(set(existing_ids)|{iid for m in messages if m['message_id'] in uncertain if (iid:=T.suggest_issue(db,job['customer_id'],m))})
            if existing_ids:S.lock_sources(db,existing_ids,user,payload['main_message_ids'])
            group=S.entity(db,'chat_groups',job['input_manifest']['group_id'],user,True)
            if group['ingestion_version']!=job['input_manifest']['ingestion_version']:raise dify.DifyError('source_changed','群已有新导入，请重新创建任务')
            if applied(db,step['id']):continue
            expected={**job['input_manifest']['disposition_versions'],**current['checkpoint'].get('owned_disposition_versions',{})}
            dispositions=rows(db,'SELECT * FROM message_dispositions WHERE message_id=ANY(%s::uuid[]) ORDER BY message_id FOR UPDATE',(payload['main_message_ids'],))
            if any(d['version']!=expected[str(d['message_id'])] for d in dispositions):raise dify.DifyError('source_changed','消息归属已被人工修改，请重新创建任务')
            ids=[]
            for item in result['assignments']:
                links=[m for m in item['message_links'] if m['message_id'] in payload['main_message_ids']]
                if not links:continue
                if item['decision']=='needs_review':
                    for link in links:
                        mid=link['message_id']
                        if one(db,'SELECT 1 FROM issue_messages WHERE message_id=%s AND active',(mid,)):continue
                        state,reason,iid=T.apply(db,user,job['customer_id'],next(m for m in messages if m['message_id']==mid),item['decision_note'])
                        if iid:ids.append(iid)
                        else:db.execute("UPDATE message_dispositions SET state=%s,decision_source='rule',reason=%s,version=version+1 WHERE message_id=%s",(state,reason,mid))
                        db.execute('UPDATE message_dispositions SET source_job_step_id=%s WHERE message_id=%s',(step['id'],mid))
                    continue
                if item['decision']=='new_issue':
                    issue=A.existing_issue(db,job['customer_id'],links)
                    if issue:
                        S.lock_sources(db,[str(issue['id'])],user,[m['message_id'] for m in links])
                        S.assign_messages(db,user,issue,links,ai=True)
                    else:issue=S.create_issue(db,user,group,item['candidate_title'],links,ai=True)['issue']
                else:
                    issue=S.entity(db,'issues',item['existing_issue_id'],user,True)
                    old=next(i for i in payload['candidate_issues'] if i['issue_id']==str(issue['id']))
                    if str(issue['id']) not in ids and issue['message_version']!=old['message_version']:raise dify.DifyError('source_changed','候选问题已变化')
                    S.assign_messages(db,user,issue,links,ai=True)
                ids.append(str(issue['id']))
            for item in result['unassigned_messages']:
                # A later fragment cannot erase a verified link from an earlier
                # fragment of the same original message.
                linked=one(db,'SELECT 1 FROM issue_messages WHERE message_id=%s AND active',(item['message_id'],))
                if not linked:
                    state,reason,iid=T.apply(db,user,job['customer_id'],next(m for m in messages if m['message_id']==item['message_id']),item['reason'])
                    if iid:ids.append(iid)
                    else:db.execute("UPDATE message_dispositions SET state=%s,decision_source='rule',reason=%s,version=version+1 WHERE message_id=%s",(state,reason,item['message_id']))
                    db.execute('UPDATE message_dispositions SET source_job_step_id=%s WHERE message_id=%s',(step['id'],item['message_id']))
            owned=dict(current['checkpoint'].get('owned_disposition_versions',{}))
            for mid in set(payload['main_message_ids'])&set(current['checkpoint'].get('review_message_ids',[])):
                db.execute("UPDATE message_dispositions SET state='needs_review',decision_source='rule',reason='长消息有未确认片段，请人工核对归属',version=version+1 WHERE message_id=%s",(mid,))
            owned.update({str(d['message_id']):d['version'] for d in rows(db,'SELECT message_id,version FROM message_dispositions WHERE message_id=ANY(%s::uuid[])',(payload['main_message_ids'],))})
            end=payload['processing']['cursor_end']
            remaining={p['message_id'] for p in plan[end:]}
            done=len(set(all_ids)-remaining)
            all_issues=sorted(set(current['result_issue_ids']+ids))
            cap=current['checkpoint'].get('topic_packet_cap',0)
            streak=current['checkpoint'].get('topic_success_streak',0)+1 if cap else 0
            if cap and streak>=3:
                cap=min(cap+1,max(1,(limits['topic_output']-100)//150));streak=0
            checkpoint(db,job['id'],topic_cursor=end,topic_batches=current['checkpoint'].get('topic_batches',0)+1,
                       messages_done=done,owned_disposition_versions=owned,topic_packet_cap=cap,topic_success_streak=streak)
            db.execute('UPDATE extraction_jobs SET result_issue_ids=%s WHERE id=%s',(Jsonb(all_issues),job['id']))
            S.watermark(db,group['id']);mark_applied(db,step['id'],ids)


def extraction_payload(db,job,issue):
    payload=common(db,job);messages=S.issue_messages(db,issue['id'])
    payload['participants']=[dict(participant_id=str(p['id']),display_name=p['display_name'],role=p['role']) for p in
        rows(db,'SELECT * FROM participants WHERE id=ANY(%s::uuid[]) ORDER BY id',
             (sorted({str(m['sender_participant_id']) for m in messages if m['sender_participant_id']}),))]
    payload.update(mode=job['mode'],issue=dict(issue_id=str(issue['id']),version=issue['version'],message_version=issue['message_version'],title=issue['label'],input_complete=True),
        allowed_message_ids=[str(m['id']) for m in messages],messages=wf_messages(db,messages),current_ticket=None,related_qa=[])
    ticket=one(db,'SELECT * FROM tickets WHERE issue_id=%s',(issue['id'],))
    if ticket['current_revision_id']:
        r=S.entity(db,'ticket_revisions',ticket['current_revision_id'])
        payload['current_ticket']=dict(ticket_id=str(ticket['id']),revision_id=str(r['id']),object_version=ticket['version'],title=r['title'],content=r['problem_text']+'\n'+r['handling_summary']+'\n'+r['current_conclusion'])
    for q in rows(db,'''SELECT DISTINCT q.* FROM qa_entries q JOIN qa_revisions qr ON qr.qa_id=q.id JOIN qa_issue_links l ON l.qa_revision_id=qr.id
        WHERE l.issue_id=%s AND q.lifecycle='active' AND NOT '''+D.deleted('qa','q'),(issue['id'],)):
        r=A.latest(db,'qa',q['id'])
        # Unfinished human drafts have no reusable answer and cannot satisfy the
        # workflow's related_qa contract. Keep them in storage for edit protection.
        if not r or not (r['answer'] or '').strip():continue
        payload['related_qa'].append(dict(qa_id=str(q['id']),revision_id=str(r['id']),object_version=q['version'],question=r['question'],answer=r['answer'],support_message_ids=[],
            source_issue_ids=[str(i['issue_id']) for i in rows(db,'SELECT issue_id FROM qa_issue_links WHERE qa_revision_id=%s ORDER BY issue_id',(r['id'],))]))
    return payload


def extract_issue(job,token,user,issue_id):
    with connect() as db:
        current=live(db,job['id'],token)
        issue=S.entity(db,'issues',issue_id,user)
        done=one(db,"SELECT id FROM job_steps WHERE job_id=%s AND stage='record_extraction' AND output_json->>'applied'='true' AND issue_id=%s",(job['id'],issue_id))
        if done:return
        versions=dict(current['checkpoint'].get('issue_versions',{}))
        if issue_id in versions and versions[issue_id]!=issue['message_version']:
            raise dify.DifyError('source_changed','问题来源已发生变更，请重新创建任务')
        versions[issue_id]=issue['message_version']
        checkpoint(db,job['id'],phase='record_extraction',current_issue_id=issue_id,issue_versions=versions)
        full=extraction_payload(db,job,issue)
    limits=job['model_profile_snapshot'].get('budget') or budget.policy()
    if budget.measure('record_extraction',full,limits)['fits']:
        step,payload,result=call_step(job,token,'record_extraction',issue_id,full)
    else:
        messages=full['messages']
        source_ranges=pipeline.parts(messages,limits['fragment_tokens'],limits)
        ranges=pipeline.view_parts(messages,source_ranges,limits['fragment_tokens'],limits)
        mapped=[];level_results=[];part_steps=[]
        for level in range(4):
            packets=list(pipeline.record_packets(full,messages,ranges,limits,phase='map' if level==0 else 'reduce_map'))
            level_results=[]
            for index,part in enumerate(packets):
                with connect() as db:
                    live(db,job['id'],token)
                    checkpoint(db,job['id'],map_level=level,map_parts_done=index,map_parts_total=len(packets))
                part['processing']['source_part_count']=len(source_ranges)
                part_step,part_payload,part_result=call_step(job,token,'record_extraction',f'{issue_id}:map-facts:{level}:{index}',part)
                level_results.append(pipeline.globalize(part_result,part_payload,messages));part_steps.append(part_step['id'])
            if level==0:mapped=list(level_results)
            windows=pipeline.evidence_windows(level_results,messages,limits)
            if not windows:
                windows=ranges[:1]
            payload=pipeline.packet(full,messages,windows,'reduce_final',source_parts_complete=True,source_part_count=len(source_ranges),
                reduction_note='All original source parts were inspected. These are verbatim evidence windows; intermediate claims remain in the draft audit trail.')
            payload['allowed_message_ids']=[m['message_id'] for m in payload['messages']]
            if budget.measure('record_extraction',payload,limits)['fits']:
                final_key=issue_id+':final:'+digest({k:v for k,v in payload.items() if k!='run'})[:16]
                step,payload,result=call_step(job,token,'record_extraction',final_key,payload)
                result=pipeline.globalize(result,payload,messages)
                result=pipeline.merge_ticket_claims(result,mapped)
                # Validate restored full-source evidence again before persistence.
                dify.validate_extraction(full,result)
                payload=full
                break
            ranges=pipeline.view_parts(messages,windows,limits['fragment_tokens'],limits)
        else:
            raise dify.DifyError('reduction_budget','已保存全部分段结果，证据归纳仍超预算；请人工拆分此问题后继续')
    with connect() as db:
        live(db,job['id'],token)
        if not applied(db,step['id']):
            save_extraction(db,user,job,step,payload,result)
            mark_applied(db,step['id'],[issue_id])


def save_extraction(db,user,job,step,payload,result):
    issue_id=payload['issue']['issue_id'];issues,groups=S.lock_sources(db,[issue_id],user)
    source_group=next(g for g in groups if str(g['id'])==job['input_manifest']['group_id'])
    if issues[0]['message_version']!=payload['issue']['message_version'] or source_group['ingestion_version']!=job['input_manifest']['ingestion_version']:
        raise dify.DifyError('source_changed','抽取期间来源已变化，请重新创建任务')
    def anchor(e):return S.evidence(db,user,e['message_id'],e['exact_excerpt'],e['occurrence'])['id']
    def bind(evidence,key):return [dict(evidence_span_id=str(anchor(e)),field_key=key,relation='supports') for e in evidence]
    ticket_result=result['ticket']
    if ticket_result:
        # Model claim keys are local labels, not database identifiers. Assign
        # stable ASCII keys and use the same keys in evidence bindings.
        claims=[dict(c,claim_key=f'c{i}') for i,c in enumerate(ticket_result['claims'],1)]
        t=one(db,'SELECT * FROM tickets WHERE issue_id=%s',(issue_id,));base=payload['current_ticket']
        source=S.issue_messages(db,issue_id)
        first=next((m for m in source if m['sent_at'] is not None),source[0])
        expected=base['object_version'] if base else t['version']
        if not base and t['current_revision_id']:raise dify.DifyError('source_changed','工单正式版本已变化，请重新抽取')
        content=dict(title=ticket_result['title'],first_visible_message_id=str(first['id']),first_question_message_id=ticket_result['first_question_message_id'],date_basis=ticket_result['date_basis'],
            problem=ticket_result['problem'],impact='',handling_summary=ticket_result['processing_summary'],current_conclusion=ticket_result['current_conclusion'],status=ticket_result['proposed_status'],
            claims=[dict(claim_key=c['claim_key'],text=c['text']) for c in claims],next_actions=[])
        bindings=bind(ticket_result['status_evidence'],'status')
        for c in claims:bindings+=bind(c['evidence'],'claims.'+c['claim_key'])
        # Fact evidence supports review of the whole ticket. Do not manufacture
        # duplicate problem/conclusion bindings from unrelated generic claims.
        for action in ticket_result['next_actions']:
            content['next_actions'].append(dict(text=action['text'],basis=action['basis'],evidence_span_ids=[str(anchor(e)) for e in action['evidence']]))
        parsed=M.TicketContent.model_validate(content)
        if t['version']!=expected:raise dify.DifyError('source_changed','工单版本已变化，请重新抽取')
        A.save(db,user,job,step,'ticket',t,plain(parsed.model_dump()),bindings,[issue_id])
    for qa in result['qa_candidates']:
        claims=[dict(c,claim_key=f'a{i}') for i,c in enumerate(qa['answer_claims'],1)]
        bindings=bind(qa['question_evidence'],'question')
        for c in claims:bindings+=bind(c['evidence'],'answer_claims.'+c['claim_key'])+bind(c['evidence'],'answer')
        q=A.find_qa(db,issue_id,qa['question'],bindings)
        if qa['action']!='create':q=S.entity(db,'qa_entries',qa['existing_qa_id'],user)
        if q is None:q=insert(db,'qa_entries',dict(id=uid(),customer_id=job['customer_id'],qa_no='QA-'+uid()[:12].upper()))
        content=dict(question=qa['question'],answer=qa['answer'],answer_state='supported',applicability=qa['applicability'],
            answer_claims=[dict(claim_key=c['claim_key'],text=c['text']) for c in claims],
            contributors=[dict(participant_id=c['participant_id'],contribution=c['contribution'],evidence_span_ids=[str(anchor(e)) for e in c['evidence']]) for c in qa['contributors']])
        # Roles come from registered accounts; direct-source evidence remains required.
        parsed=M.QAContent.model_validate(content)
        unique={(b['field_key'],b['evidence_span_id']):b for b in bindings}
        A.save(db,user,job,step,'qa',q,plain(parsed.model_dump()),list(unique.values()),[issue_id])


@celery.task(name='records.run_job')
def run_job(job_id):
    with connect() as db:
        job=one(db,'SELECT * FROM extraction_jobs WHERE id=%s FOR UPDATE',(job_id,))
        if not job:return
        if job['state']=='cancel_requested':
            db.execute("UPDATE extraction_jobs SET state='cancelled',finished_at=now(),version=version+1 WHERE id=%s",(job_id,));return
        if job['state'] not in ('queued','running') or (job['state']=='running' and job['lease_until'] and job['lease_until']>datetime.now(timezone.utc)):return
        job=one(db,"""UPDATE extraction_jobs SET state='running',started_at=coalesce(started_at,now()),lease_owner=%s,
            lease_until=now()+interval '15 minutes',fencing_token=fencing_token+1,version=version+1 WHERE id=%s RETURNING *""",(uid(),job_id))
    token=job['fencing_token']
    try:
        with connect() as db:
            if not job['model_profile_snapshot'].get('budget'):
                job['model_profile_snapshot']['budget']=budget.policy(job['model_profile_snapshot']['id'])
                db.execute('UPDATE extraction_jobs SET model_profile_snapshot=%s WHERE id=%s',(Jsonb(job['model_profile_snapshot']),job_id))
            user=one(db,'SELECT * FROM users WHERE id=%s AND disabled_at IS NULL',(job['requested_by'],))
            if not user:raise dify.DifyError('permission_changed','请求用户已停用')
            scope(db,user,job['customer_id'])
        if job['batch_id'] and not job['classification_committed']:
            ids=classify(job,token,user)
            with connect() as db:
                live(db,job_id,token)
                db.execute('UPDATE extraction_jobs SET classification_committed=true,result_issue_ids=%s WHERE id=%s',(Jsonb(ids),job_id))
        else:ids=job['result_issue_ids'] if job['batch_id'] else [str(job['target_issue_id'])]
        failures=[]
        with connect() as db:
            checkpoint(db,job_id,extraction_total=len(ids),extraction_done=0)
        done=0
        for issue_id in ids:
            try:
                extract_issue(job,token,user,issue_id)
                done+=1
            except dify.DifyError as exc:
                if exc.code in ('source_changed','job_cancelled','permission_changed','workflow_changed','identity_changed'):raise
                failures.append({'issue_id':issue_id,'code':exc.code,'message':exc.message})
            with connect() as db:
                live(db,job_id,token)
                checkpoint(db,job_id,extraction_done=done,failed_issues=failures)
        with connect() as db:
            live(db,job_id,token)
            unresolved=one(db,"""SELECT count(*) AS n FROM message_dispositions d JOIN messages m ON m.id=d.message_id
                WHERE m.batch_id=%s AND d.state IN ('pending','needs_review')""",(job['batch_id'],))['n'] if job['batch_id'] else 0
            checkpoint(db,job_id,phase='finished' if not failures else 'partial_failed',needs_review_messages=unresolved)
            db.execute("UPDATE extraction_jobs SET state=%s,error_code=%s,error_summary=%s,finished_at=now(),lease_until=NULL,version=version+1 WHERE id=%s",
                ('partial_failed' if failures else 'succeeded','issues_failed' if failures else None,
                 f'{len(failures)} 个问题抽取失败；已保存其余草稿，重试将从断点继续' if failures else None,job_id))
    except Exception as exc:
        log.exception('Job %s failed',job_id)
        if isinstance(exc,HTTPException):code=exc.detail.get('code','validation_failed');message=exc.detail.get('message','数据校验失败')
        else:code=getattr(exc,'code','job_failed');message=getattr(exc,'message','任务失败，请检查服务日志')
        with connect() as db:
            current=one(db,'SELECT * FROM extraction_jobs WHERE id=%s FOR UPDATE',(job_id,))
            if current['fencing_token']==token:
                state='cancelled' if current['state']=='cancel_requested' else 'partial_failed' if one(db,"SELECT 1 FROM job_steps WHERE job_id=%s AND output_json->>'applied'='true' LIMIT 1",(job_id,)) else 'failed'
                db.execute('UPDATE extraction_jobs SET state=%s,error_code=%s,error_summary=%s,finished_at=now(),lease_until=NULL,version=version+1 WHERE id=%s',(state,code,message,job_id))
